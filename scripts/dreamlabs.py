#!/usr/bin/env python3
"""Dream-1 -> Piper: measured feedback, URDF FK, EEF chunks, bounded IK and CAN.

Run from the repository: python -m scripts.dreamlabs --prompt "put the cup on the plate"
Only --execute enables motors. No Dream joint head is ever sent to Piper.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
import sys
import threading
import time

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from scripts.constants import validate_joint_target
from scripts.driver import PiperFeedbackArm
from scripts.gripper_calibration import load_piper_gripper_calibrations
from scripts.kinematics import PiperKinematics
from hardware.cameras.crop_fisheye import crop_center, rectification_maps

SIDES = ("left", "right")
ROLES = {"top": "overhead", "left": "wrist_l", "right": "wrist_r"}
LOG = logging.getLogger("piper.dreamlabs")


def configure_logging(verbose: bool, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    LOG.setLevel(logging.DEBUG if verbose else logging.INFO)
    LOG.propagate = False
    for handler in LOG.handlers[:]:
        LOG.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(path, encoding="utf-8")):
        handler.setFormatter(formatter)
        LOG.addHandler(handler)
    LOG.info("Registro de esta ejecución: %s", path)


def log_reply(reply: dict) -> None:
    LOG.info("Respuesta recibida. Claves: %s", list(reply))
    parts = reply.get("per_key")
    if not isinstance(parts, dict):
        LOG.warning("La respuesta no contiene un diccionario per_key válido")
        return
    for key, value in parts.items():
        if value is None:
            LOG.info("  %s: null", key)
            continue
        array = np.asarray(value)
        LOG.info("  %s: forma=%s; primera=%s; última=%s", key, array.shape,
                 array[0].tolist() if array.ndim and array.size else None,
                 array[-1].tolist() if array.ndim and array.size else None)
        LOG.debug("  Respuesta completa %s: %s", key, array.tolist())


def action_interval(previous: dict, action: dict, action_hz: float,
                    speed_scale: float, max_speed_deg_s: float) -> float:
    """Stretch row times as needed; never discard intermediate model targets."""
    delta = max(abs(action[f"{s}_joint{i}"] - previous[f"{s}_joint{i}"])
                for s in SIDES for i in range(1, 7))
    return max(1.0 / (action_hz * speed_scale), delta / np.deg2rad(max_speed_deg_s))


def read_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        document = yaml.safe_load(stream)
    if not isinstance(document, dict):
        raise ValueError(f"Expected YAML mapping: {path}")
    return document


def repository_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def make_observation(states: dict, solvers: dict, prompt: str) -> dict:
    """Build the base YAM checkpoint's wire observation using measured Piper FK.

    Mirror the installed SDK's dream.client_ik.ClientIK.observe: when
    yam_joints is set, it computes FK from measured body joints, then replaces
    state.<side>_arm with zeros for the YAM-trained checkpoint. This loop uses
    its own IK, so it performs that wire adaptation itself. These joint slots
    are not Piper telemetry; the measured Piper joints remain local to FK/IK.
    A checkpoint trained on Piper needs its own observation contract instead.
    """
    observation = {"prompt": prompt}
    for side in SIDES:
        joints, opening = states[side]
        if not np.isfinite(opening) or not 0 <= opening <= 1:
            raise ValueError(f"Invalid {side} measured aperture")
        transform = solvers[side].forward_matrix(joints)
        observation.update({
            f"state.{side}_arm": [0.0] * 6,
            f"state.{side}_gripper": [float(opening)],
            f"state.{side}_grip": [float(opening)],
            f"state.{side}_eef_xyz": transform[:3, 3].tolist(),
            f"state.{side}_eef_rot6": transform[:3, :2].T.reshape(6).tolist(),
        })
    return observation


def validate_eef_chunk(reply: dict) -> dict:
    """Validate every EEF array before any row is allowed to move the robot."""
    parts = reply.get("per_key")
    if not isinstance(parts, dict):
        raise ValueError("Dream reply lacks per_key EEF actions")
    arrays = {}
    length = None
    for side in SIDES:
        for part, width in (("eef_xyz", 3), ("eef_rot6", 6), ("grip", 1)):
            key = f"action.{side}_{part}"
            value = np.asarray(parts.get(key), dtype=np.float64)
            if part == "grip" and value.ndim == 1:
                value = value[:, None]
            if value.ndim != 2 or value.shape[1] != width or not np.isfinite(value).all():
                raise ValueError(f"{key}: expected finite [H,{width}] values")
            if length is None:
                length = len(value)
            if not length or len(value) != length:
                raise ValueError("Dream action parts have empty or different horizons")
            if part == "grip" and np.any((value < 0) | (value > 1)):
                raise ValueError(f"{key}: aperture outside [0,1]")
            arrays[side, part] = value
    return arrays


def iter_solved_actions(arrays: dict, solvers: dict, seeds: dict, start: int = 0):
    """Solve only the next row, validating both arms before yielding a command."""
    seeds = {side: np.asarray(seeds[side]).copy() for side in SIDES}
    for row in range(start, len(arrays["left", "eef_xyz"])):
        action = {}
        for side in SIDES:
            joints, _, _ = solvers[side].solve(
                arrays[side, "eef_xyz"][row], arrays[side, "eef_rot6"][row], seeds[side])
            joints = validate_joint_target(joints)
            seeds[side] = joints
            action.update({f"{side}_joint{i + 1}": float(q) for i, q in enumerate(joints)})
            action[f"{side}_gripper"] = float(arrays[side, "grip"][row, 0])
        yield action


def solve_chunk(reply: dict, solvers: dict, seeds: dict) -> list[dict]:
    """Offline validation helper; live execution solves one row at a time."""
    return list(iter_solved_actions(validate_eef_chunk(reply), solvers, seeds))


def stream_rollout(client, solvers, read_states, observe, robot, args, max_speed,
                   refresh_observation=None):
    """Replan from fresh feedback during playback; never queue whole horizons.

    One request may be in flight. New horizons replace the old remainder, with
    rows already elapsed since the request omitted. IK is evaluated per row.
    """
    period = 1.0 / (args.action_hz * args.speed_scale)
    replan_rows = getattr(args, "replan_rows", 8)
    request_count = executed = 0
    pending = None
    actions = None
    request_time = retry_at = 0.0
    retry_deadline = None
    refused = 0
    next_tick = time.monotonic()
    next_observation = next_tick
    previous = None
    # Explicit shutdown below lets the robot stop before waiting for a network
    # worker on exceptions or Ctrl+C.
    pool = ThreadPoolExecutor(max_workers=1)
    camera_pool = ThreadPoolExecutor(max_workers=1)
    observation_future = None
    try:
        while True:
            now = time.monotonic()
            if observation_future is not None and observation_future.done():
                observation_future.result()  # Surface capture errors before further motion.
                observation_future = None
            if now >= next_observation and observation_future is None:
                observation_future = camera_pool.submit(observe)
                next_observation = now + 0.2
            now = time.monotonic()
            if pending is not None and pending.done():
                try:
                    reply = pending.result()
                except Exception as error:
                    import dream
                    if not isinstance(error, dream.DreamServerError):
                        raise
                    # The local verifier ends the session with a non-retryable
                    # refusal. Preserve other non-retryable errors as failures.
                    if "has finished: its lines are in the terminal" in str(error):
                        LOG.info("El verificador terminó la prueba")
                        break
                    refused = refused + 1 if error.reason == "error" else 0
                    if retry_deadline is None:
                        retry_deadline = now + args.retry_timeout
                    delay = error.retry_after_s or 1.0
                    if not error.retryable or refused >= 3 or now + delay >= retry_deadline:
                        raise
                    LOG.warning("Solicitud rechazada: %s; reintentando en %.1f s", error, delay)
                    pending = None
                    request_count -= 1
                    retry_at = now + delay
                    # Do not keep executing an old plan after a server refusal.
                    actions = None
                    if robot is not None:
                        robot.stop_motion()
                else:
                    pending = None
                    refused = 0
                    retry_deadline = None
                    log_reply(reply)
                    arrays = validate_eef_chunk(reply)
                    states = read_states()
                    length = len(arrays["left", "eef_xyz"])
                    # The first horizon establishes the start. Later replies
                    # refer to request-time state, not arrival-time state.
                    start = 0 if previous is None else int((now - request_time) / period)
                    if start >= length:
                        LOG.warning("Horizonte caducado: %.3f s de latencia; solicitando uno nuevo",
                                    now - request_time)
                        actions = None
                        if robot is not None:
                            robot.stop_motion()
                    else:
                        if actions is None:
                            next_tick = now
                        actions = iter_solved_actions(arrays, solvers,
                                                      {s: states[s][0] for s in SIDES}, start)
                        executed = 0
                        if previous is None:
                            previous = {f"{s}_joint{i + 1}": float(q)
                                        for s in SIDES for i, q in enumerate(states[s][0])}
                            next_tick = now
                        LOG.info("Horizonte %d: %d filas; inicio en fila %d; latencia %.3f s",
                                 request_count, length, start, now - request_time)
            now = time.monotonic()
            if (pending is None and request_count < args.chunks and now >= retry_at
                    and (actions is None or executed >= replan_rows)):
                # The capture worker continuously updates measured state and
                # real images at 5 Hz while requests and playback proceed.
                if refresh_observation is not None:
                    refresh_observation()
                request_time = time.monotonic()
                request_count += 1
                pending = pool.submit(client.get_action)
                LOG.info("Solicitando horizonte %d/%d durante reproducción", request_count, args.chunks)
            if actions is not None and now >= next_tick:
                try:
                    action = next(actions)
                except StopIteration:
                    actions = None
                    # Hold the last target while a delayed reply arrives. Do
                    # not reset to measured position between healthy horizons.
                else:
                    interval = action_interval(previous, action, args.action_hz,
                                               args.speed_scale, max_speed)
                    read_states()  # Propagate feedback/streamer errors before writing.
                    lateness = time.monotonic() - next_tick
                    if lateness > 0.25:
                        raise RuntimeError(f"Control loop delayed by {lateness:.3f} s")
                    if robot is not None:
                        robot.send_action(action)
                    LOG.debug("Objetivo %d: %s", executed + 1, action)
                    previous = action
                    executed += 1
                    # Keep the nominal clock when on time; after an overrun
                    # wait a full interval instead of sending catch-up bursts.
                    next_tick += interval
                    if next_tick <= time.monotonic():
                        next_tick = time.monotonic() + interval
            if actions is None and pending is None and request_count >= args.chunks:
                break
            time.sleep(max(0.001, min(0.005, next_tick - time.monotonic()))
                       if actions is not None else 0.005)
    finally:
        try:
            if robot is not None:
                robot.stop_motion()
        finally:
            if pending is not None:
                pending.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            # Complete camera reads before ExitStack closes cameras and client.
            camera_pool.shutdown(wait=True, cancel_futures=True)


def prepare_dream_frame(frame: np.ndarray) -> np.ndarray:
    """Center-crop to 16:9, then resize to Dream-1's 320x176 input.

    Apply after camera rectification. Do not duplicate the model's own 2.5%
    edge trim or add padding. See https://platform.dreamlabs.ai/docs/.
    """
    import cv2

    height, width = frame.shape[:2]
    if width * 9 > height * 16:
        crop_width = max(1, height * 16 // 9)
        left = (width - crop_width) // 2
        frame = frame[:, left:left + crop_width]
    else:
        crop_height = max(1, width * 9 // 16)
        top = (height - crop_height) // 2
        frame = frame[top:top + crop_height, :]
    return cv2.resize(frame, (320, 176), interpolation=cv2.INTER_AREA)


class Cameras:
    """Rectified, centrally cropped wrists and SDK-rectified ZED overhead."""

    def __init__(self, configs: dict, stack: ExitStack):
        import cv2
        from hardware.zedmini.zedmini import ZedMiniCameraDevice

        self.devices = {}
        calibrations = read_config(ROOT / 'outputs/calibration/spatial.yaml')['cameras']
        self.wrist_maps = {
            ROLES[name]: rectification_maps(name, calibrations[name])
            for name in ('left', 'right')
        }
        for name, role in ROLES.items():
            config = configs[name]
            if config["type"] == "zedmini":
                device = ZedMiniCameraDevice(fps=config.get("fps", 30),
                                           serial_number=config.get("serial_number"))
                stack.callback(device.disconnect)
                device.connect()
            elif config["type"] == "opencv":
                backend = getattr(cv2, "CAP_" + str(config.get("backend", "V4L2")).upper())
                device = cv2.VideoCapture(config["index_or_path"], backend)
                stack.callback(device.release)
                if not device.isOpened():
                    raise RuntimeError(f"Cannot open camera {name}")
                device.set(cv2.CAP_PROP_FRAME_WIDTH, int(config["width"]))
                device.set(cv2.CAP_PROP_FRAME_HEIGHT, int(config["height"]))
                device.set(cv2.CAP_PROP_FPS, int(config.get("fps", 30)))
                device.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            else:
                raise ValueError(f"Unsupported camera type for {name}: {config['type']}")
            self.devices[role] = (config["type"], device)

    def frames(self) -> dict:
        import cv2

        frames = {}
        for role, (kind, device) in self.devices.items():
            if kind == "zedmini":
                frame = device.read()
            else:
                ok, frame = device.read()
                if not ok or frame is None:
                    raise RuntimeError(f"Cannot read camera {role}")
            if role in self.wrist_maps:
                size, (map_x, map_y) = self.wrist_maps[role]
                if (frame.shape[1], frame.shape[0]) != size:
                    raise RuntimeError(f'{role}: resolución capturada {frame.shape[1]}x{frame.shape[0]} '
                                       f'distinta de la calibración {size[0]}x{size[1]}')
                frame = crop_center(cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR))
            frame = prepare_dream_frame(frame)
            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ok:
                raise RuntimeError(f"Cannot encode camera {role}")
            frames[f"video.{role}"] = base64.b64encode(jpeg.tobytes()).decode("ascii")
        return frames


def run(args: argparse.Namespace) -> None:
    import dream
    from scripts.piper import BiPiper, BiPiperConfig

    config = read_config(args.config)["robot"].copy()
    if args.execute:
        start = config.get("inference_start", {}).copy()
        start["enabled"] = True
        if start.get("pose_file"):
            start["pose_file"] = repository_path(start["pose_file"])
        start["max_joint_speed_deg_s"] = min(
            start.get("max_joint_speed_deg_s", 10.0), args.max_joint_speed)
        config["inference_start"] = start
    LOG.info("Inicio: modo=%s; modelo=%s", "EJECUCIÓN" if args.execute else "SIN MOVIMIENTO", args.checkpoint)
    LOG.info("Prompt local: %s", args.prompt)
    LOG.info("Cargando URDF y TCP: %s", args.urdf)
    # Base and TCP names refer to the updated URDF, including its fixed TCP offset.
    solvers = {side: PiperKinematics(args.urdf, f"{side}_base_link", f"{side}_tcp", side)
               for side in SIDES}
    calibration_path = repository_path(config.get(
        "gripper_calibration_path", "outputs/calibration/bipiper-gripper-calibration.yaml"))
    ranges = load_piper_gripper_calibrations(calibration_path)
    if any(side not in ranges for side in SIDES):
        raise ValueError(f"Calibrate both grippers first: {calibration_path}")

    with ExitStack() as stack:
        LOG.info("Conectando cámaras: %s", args.cameras)
        cameras = Cameras(read_config(args.cameras)["cameras"], stack)
        LOG.info("Cámaras abiertas: top→overhead, left→wrist_l, right→wrist_r")
        robot = None
        if args.execute:
            config.pop("type", None)
            config.pop("urdf", None)
            config["gripper_calibration_path"] = calibration_path
            # Cameras are captured here, independently of optional LeRobot/MU.
            config["cameras"] = {}
            # These overrides apply only to this inference session, not teleoperation.
            config["max_joint_speed_deg_s"] = min(config.get("max_joint_speed_deg_s", 180), args.max_joint_speed)
            config["max_joint_acceleration_deg_s2"] = min(
                config.get("max_joint_acceleration_deg_s2", 720), args.max_joint_acceleration)
            config["speed_percent"] = min(config.get("speed_percent", 80), 20)
            config["startup_speed_percent"] = min(config.get("startup_speed_percent", 10), 10)
            LOG.info("Conectando Piper y habilitando motores. Límite=%.1f °/s; aceleración=%.1f °/s²; SDK=%s%%",
                     config["max_joint_speed_deg_s"], config["max_joint_acceleration_deg_s2"], config["speed_percent"])
            robot = BiPiper(BiPiperConfig(**config))
            stack.callback(robot.disconnect)
            robot.connect()
            LOG.info("Ambos brazos conectados")
            LOG.info("Moviendo a la postura inicial de scripts/initial_pose.py")
            try:
                robot.move_to_initial_pose()
            except BaseException:
                robot.stop_motion()
                raise
            LOG.info("Postura inicial alcanzada; comenzando observaciones para Dream")

            def read_states():
                states = {}
                for side in SIDES:
                    arm = getattr(robot, side)
                    joints = arm.read_joints_rad()
                    opening = arm._arm.read_gripper_opening()
                    if opening is None:
                        raise RuntimeError(f"{side}: gripper feedback unavailable")
                    states[side] = (joints, opening)
                return states
        else:
            arms = {}
            for side in SIDES:
                LOG.info("Conectando feedback %s en %s (sin habilitar motores)", side, config[f"{side}_port"])
                arm = PiperFeedbackArm(config[f"{side}_port"], ranges[side])
                stack.callback(arm.disconnect)
                arms[side] = arm

            def read_states():
                return {side: arms[side].read() for side in SIDES}

        LOG.info("Abriendo cliente y configurando política Dream Labs…")
        client = stack.enter_context(dream.DreamClient())
        client.policy({"checkpoint": args.checkpoint, "robot": "other_embodiment",
                       "obs_window": 9, "obs_fps": 5.0, "action_hz": args.action_hz})
        LOG.info("Política configurada; la conexión de inferencia se confirma al recibir respuesta")
        observation_count = 0
        last_observation = None
        observation_lock = threading.Lock()
        latest_frames = None
        frame_timestamp = None

        def refresh_observation():
            # Reuse the actual frame timestamp: updating joint feedback must
            # not manufacture a new camera tick or duplicate the image window.
            with observation_lock:
                states = read_states()
                observation = make_observation(states, solvers, args.prompt)
                client.set_observation(latest_frames, observation, timestamp=frame_timestamp)

        def observe():
            nonlocal observation_count, last_observation, latest_frames, frame_timestamp
            frames = cameras.frames()
            with observation_lock:
                states = read_states()
                observation = make_observation(states, solvers, args.prompt)
                frame_timestamp = time.monotonic()
                latest_frames = frames
                client.set_observation(frames, observation, timestamp=frame_timestamp)
            observation_count += 1
            last_observation = observation
            if observation_count == 1:
                LOG.info("Feedback e imágenes disponibles. Observación preparada: %s", json.dumps(observation))
                LOG.info("Vídeo preparado: %s (longitudes JPEG base64, sin imprimir imágenes)",
                         {key: len(value) for key, value in frames.items()})
            if observation_count % 5 == 0:
                LOG.debug("Observación local #%d: %s", observation_count, json.dumps(observation))
            return states

        def collect_for(duration):
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                start = time.monotonic()
                observe()
                time.sleep(max(0, min(0.2 - (time.monotonic() - start), deadline - time.monotonic())))

        # Real, temporally spaced images: never nine copies with invented timestamps.
        LOG.info("Recopilando ventana inicial: 9 imágenes por cámara a 5 Hz…")
        collect_for(1.8)
        try:
            stream_rollout(client, solvers, read_states, observe, robot, args,
                           config.get("max_joint_speed_deg_s", args.max_joint_speed),
                           refresh_observation=refresh_observation)
        finally:
            if robot is not None:
                try:
                    robot.stop_motion()
                    LOG.info("Parada solicitada antes de desconectar")
                except Exception:
                    LOG.exception("No se pudo solicitar la parada de Piper")
        LOG.info("Prueba finalizada; cerrando conexiones")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", required=True, help="Task instruction sent to Dream Labs")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/bipiper.yaml")
    parser.add_argument("--cameras", type=Path, default=ROOT / "configs/cameras.yaml")
    parser.add_argument("--urdf", type=Path, default=ROOT / "assets/piper/piper.urdf")
    parser.add_argument("--checkpoint", default="dreamlabs/dream-1-beta")
    parser.add_argument("--chunks", type=int, default=1, help="Maximum number of action requests (overlapping horizons)")
    parser.add_argument("--replan-rows", type=int, default=8,
                        help="Request a fresh horizon after this many executed rows (default 8)")
    parser.add_argument("--action-hz", type=float, default=20.0)
    parser.add_argument("--speed-scale", type=float, default=0.5, help="Playback speed (0 < scale <= 1; default half speed)")
    parser.add_argument("--max-joint-speed", type=float, default=30.0, help="Joint speed cap in deg/s (default 30)")
    parser.add_argument("--max-joint-acceleration", type=float, default=120.0, help="Joint acceleration cap in deg/s² (default 120)")
    parser.add_argument("--verbose", action="store_true", help="Log complete numeric responses and every commanded target")
    parser.add_argument("--log-file", type=Path, default=ROOT / "outputs/dreamlabs/dreamlabs.log")
    parser.add_argument("--retry-timeout", type=float, default=180.0, help="Maximum retry window in seconds")
    parser.add_argument("--execute", action="store_true", help="Enable motors and execute validated joint targets")
    args = parser.parse_args(argv)
    if not args.prompt.strip() or args.chunks < 1 or args.replan_rows < 1:
        parser.error("--prompt must be nonempty; --chunks and --replan-rows must be >= 1")
    if any(not np.isfinite(v) or v <= 0 for v in (
            args.action_hz, args.retry_timeout, args.speed_scale, args.max_joint_speed, args.max_joint_acceleration)):
        parser.error("Rates, speed limits and timeouts must be finite and positive")
    if args.speed_scale > 1:
        parser.error("--speed-scale must be <= 1")
    try:
        configure_logging(args.verbose, args.log_file)
        run(args)
    except KeyboardInterrupt:
        LOG.warning("Interrumpido por el usuario (Ctrl+C)")
        return 130
    except Exception as error:
        LOG.exception("Error en Dream/Piper: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
