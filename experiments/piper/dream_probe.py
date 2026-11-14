"""Run Dream-1 with Dream Labs' official client-side Piper IK path."""

from __future__ import annotations

import argparse
import base64
from concurrent.futures import Future, ThreadPoolExecutor
import json
import os
from contextlib import ExitStack
from pathlib import Path
import time
from typing import Any

import numpy as np

from .active_config import PiperConfig
from .active_driver import PiperFeedbackArm, PiperJointStreamer, PiperSdkArm
from .gripper_calibration import load_piper_gripper_calibrations
from .custom_policy import PiperPolicy
from .rectification import rectify, letterbox


ACTION_KEYS = {"left": "q_l_chunk", "right": "q_r_chunk"}


def _commanded_payload(commanded: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Translate internal side names to Dream's official chunk keys."""
    return {ACTION_KEYS[side]: row.copy() for side, row in commanded.items()}


class RunLogger:
    """Append execution evidence without storing camera pixels locally."""

    def __init__(self, path: Path | None) -> None:
        self._stream = None
        if path is not None:
            path = path.expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            self._stream = path.open("a", encoding="utf-8")
            self.path = path
        else:
            self.path = None

    def write(self, event: str, **values: Any) -> None:
        if self._stream is None:
            return
        record = {"event": event, "timestamp_monotonic": time.monotonic(), **values}
        self._stream.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
        self._stream.flush()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()


def _frame(capture: Any, spec: dict[str, Any]) -> str:
    import cv2

    ok, image = capture.read()
    if not ok or image is None:
        raise RuntimeError(f"No frame from {spec['index_or_path']}")
    if spec.get("type") == "zedmini":
        width = int(spec["width"])
        if image.shape[1] != width:
            raise RuntimeError(f"Unexpected ZED stereo width: {image.shape[1]} != {width}")
        image = image[:, : image.shape[1] // 2]
    image = letterbox(rectify(image, spec))
    ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return base64.b64encode(jpeg.tobytes()).decode("ascii")


def _open_camera(spec: dict[str, Any]) -> Any:
    import cv2

    backend = cv2.CAP_V4L2 if spec.get("backend") == "V4L2" else cv2.CAP_ANY
    capture = cv2.VideoCapture(str(spec["index_or_path"]), backend)
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open camera: {spec['index_or_path']}")
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, int(spec["width"]))
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, int(spec["height"]))
    capture.set(cv2.CAP_PROP_FPS, int(spec["fps"]))
    return capture


def _settings() -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path(os.environ.get("DREAM_PIPER_ENV", ".env"))
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, separator, value = line.partition("=")
            if separator:
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _value(settings: dict[str, str], key: str, default: str = "") -> str:
    return settings.get(key, os.environ.get(key, default)).strip()


def _require_key(settings: dict[str, str]) -> str:
    key = _value(settings, "DREAM_API_KEY")
    if not key or any(char.isspace() for char in key):
        raise ValueError("Set DREAM_API_KEY in .env or the environment")
    return key


def _capture_observation(
    captures: dict[str, Any],
    cameras: dict[str, dict[str, Any]],
    readers: dict[str, Any],
    prompt: str,
) -> tuple[dict[str, tuple[np.ndarray, float]], dict[str, str], dict[str, Any], float]:
    state = {side: readers[side].read() for side in ("left", "right")}
    frames = {
        f"video.{role}": _frame(captures[name], cameras[name])
        for name, role in (("left", "wrist_l"), ("top", "overhead"), ("right", "wrist_r"))
    }
    observation: dict[str, Any] = {"prompt": prompt}
    for side in ("left", "right"):
        joints, opening = state[side]
        # The official Dream IK client adds EEF poses from these measured radians.
        observation[f"state.{side}_arm"] = joints.tolist()
        observation[f"state.{side}_grip"] = [opening]
    return state, frames, observation, time.monotonic()


def _chunk(action: dict[str, Any]) -> dict[str, np.ndarray]:
    if not isinstance(action, dict):
        raise ValueError(f"Dream action must be a mapping, got {type(action).__name__}")
    chunks: dict[str, np.ndarray] = {}
    for side, key in ACTION_KEYS.items():
        if key not in action:
            raise ValueError(f"Dream response is missing {key}; configure official IK with head=eef")
        values = np.asarray(action[key], dtype=np.float64)
        if values.ndim != 2 or values.shape[1] != 7 or values.shape[0] == 0:
            raise ValueError(f"Unexpected {key} shape: {values.shape}; expected [H, 7]")
        if not np.isfinite(values).all():
            raise ValueError(f"Dream response {key} contains non-finite values")
        if np.any(values[:, 6] < -0.02) or np.any(values[:, 6] > 1.02):
            raise ValueError(f"Dream gripper values for {side} are outside [0, 1]")
        chunks[side] = values.copy()
    if len(chunks["left"]) != len(chunks["right"]):
        raise ValueError("Dream returned different chunk lengths for left and right arms")
    return chunks


def _print_latency(cycle: int, wall_ms: float, timing: dict[str, Any] | None, mode: str) -> None:
    timing = timing or {}
    print(
        json.dumps(
            {
                "dream_request": cycle,
                "latency_wall_ms": round(wall_ms, 1),
                "latency_http_rtt_ms": timing.get("rtt_ms"),
                "model_inference_ms": timing.get("serve_infer_ms"),
                "gateway_ms": timing.get("gateway_ms"),
                "network_ms": timing.get("network_ms"),
                "pacing_mode": mode,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def _get_action(client: Any, commanded: dict[str, np.ndarray] | None) -> tuple[dict[str, Any], dict[str, Any] | None, float]:
    import dream

    started = time.monotonic()
    attempts = 0
    while True:
        try:
            action = client.get_action(commanded=commanded)
            return action, client.last_timing, (time.monotonic() - started) * 1000.0
        except dream.DreamSessionExpired:
            if attempts >= 1:
                raise
            client.reset_episode()
            attempts += 1
        except (dream.DreamTimeout, dream.DreamServerError) as exc:
            retryable = isinstance(exc, dream.DreamTimeout) or bool(getattr(exc, "retryable", False))
            if not retryable or attempts >= 3:
                raise
            time.sleep(float(getattr(exc, "retry_after_s", None) or 1.0))
            attempts += 1


def _policy_config(
    checkpoint: str,
    arm_file: Path,
    embodiment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "checkpoint": checkpoint,
        "robot": "other_embodiment",
        "strict": True,
        "obs_window": 9,
        "obs_fps": 5,
        "action_hz": 30,
    }
    if embodiment is not None:
        config["embodiment"] = embodiment
    return config


def _embodiment_config(client: Any, settings: dict[str, str]) -> dict[str, Any]:
    requested = _value(settings, "DREAM_EMBODIMENT")
    embodiments = client.get_embodiments()
    if requested:
        matches = [item for item in embodiments if item.name == requested or item.id == requested]
    else:
        matches = embodiments[:1]
    if not matches:
        raise RuntimeError(
            "No Dream embodiment matches DREAM_EMBODIMENT; register the Piper body first"
        )
    return matches[0].embodiment_config


def _stream(
    client: Any,
    captures: dict[str, Any],
    cameras: dict[str, dict[str, Any]],
    readers: dict[str, Any],
    streamers: dict[str, PiperJointStreamer],
    prompt: str,
    chunks: dict[str, np.ndarray],
    commanded: dict[str, np.ndarray] | None,
    cycle: int,
    logger: RunLogger,
    max_duration_s: float = 15.0,
) -> None:
    deadline = time.monotonic() + max_duration_s
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="dream-piper") as workers:
        index = 0
        pending: Future | None = None
        frame_count = len(chunks["left"])
        prepared: dict[str, np.ndarray] | None = None
        while True:
            if time.monotonic() >= deadline:
                for streamer in streamers.values():
                    streamer.stop()
                print("Límite de ejecución alcanzado; streaming detenido.", flush=True)
                return
            started = time.monotonic()
            state, frames, observation, timestamp = _capture_observation(captures, cameras, readers, prompt)
            client.set_observation(frames, observation, timestamp=timestamp)
            logger.write(
                "observation",
                cycle=cycle,
                index=index,
                state={
                    side: {"joints_rad": values[0].tolist(), "gripper": values[1]}
                    for side, values in state.items()
                },
            )
            for side in ("left", "right"):
                row = chunks[side][index]
                streamers[side].set_target(row[:6], float(np.clip(row[6], 0.0, 1.0)))
            commanded = {
                side: np.r_[streamers[side].snapshot()["command"], state[side][1]]
                for side in ("left", "right")
            }
            logger.write(
                "command",
                cycle=cycle,
                index=index,
                model_action={side: chunks[side][index].tolist() for side in ("left", "right")},
                commanded={side: row.tolist() for side, row in commanded.items()},
            )
            index += 1

            remaining = frame_count - index
            if pending is None and prepared is None and client.refill_due(index, remaining):
                pending = workers.submit(_get_action, client, _commanded_payload(commanded))

            if pending is not None and pending.done():
                action, timing, wall_ms = pending.result()
                pending = None
                prepared = _chunk(action)
                _print_latency(cycle + 1, wall_ms, timing, client.mode)
                if client.mode == "async" and index >= client.execution_horizon:
                    chunks = prepared
                    prepared = None
                    frame_count = len(chunks["left"])
                    index = 0
                    cycle += 1
                    continue
                # In async mode, keep the prepared chunk and switch at its horizon.

            if prepared is not None and index >= client.execution_horizon:
                chunks = prepared
                prepared = None
                frame_count = len(chunks["left"])
                index = 0
                cycle += 1
                continue

            if index >= frame_count:
                if prepared is not None:
                    chunks = prepared
                    prepared = None
                    frame_count = len(chunks["left"])
                    index = 0
                    cycle += 1
                    continue
                if pending is None:
                    pending = workers.submit(_get_action, client, _commanded_payload(commanded))
                while not pending.done():
                    for streamer in streamers.values():
                        streamer.raise_if_failed()
                    if time.monotonic() >= deadline:
                        for streamer in streamers.values():
                            streamer.stop()
                        return
                    _, frames, observation, timestamp = _capture_observation(captures, cameras, readers, prompt)
                    client.set_observation(frames, observation, timestamp=timestamp)
                    time.sleep(0.02)
                action, timing, wall_ms = pending.result()
                pending = None
                chunks = _chunk(action)
                _print_latency(cycle + 1, wall_ms, timing, client.mode)
                frame_count = len(chunks["left"])
                index = 0
                cycle += 1
                continue

            time.sleep(max(0.0, 1.0 / 30.0 - (time.monotonic() - started)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--models", action="store_true")
    choice.add_argument("--infer", action="store_true")
    parser.add_argument("--prompt")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-duration-s", type=float, default=15.0,
                        help="Maximum hardware streaming duration in seconds (default: 15)")
    parser.add_argument("--arm-file", type=Path)
    parser.add_argument("--log", type=Path, help="Append observations and commands to a local JSONL file")
    args = parser.parse_args(argv)
    if not np.isfinite(args.max_duration_s) or args.max_duration_s <= 0:
        parser.error("--max-duration-s must be finite and positive")
    if args.infer and not args.prompt:
        parser.error("--infer requires --prompt")
    if args.execute and not args.infer:
        parser.error("--execute requires --infer")

    import dream

    settings = _settings()
    with dream.DreamClient(api_key=_require_key(settings)) as client:
        if args.models:
            models = client.get_models()
            print(json.dumps([{"id": model.id, "servable": getattr(model, "servable", None)} for model in models]))
            return 0

        if args.arm_file is not None:
            parser.error("--arm-file is obsolete for custom bimanual IK; configure robot.urdf")
        arm_file = None
        root = Path(__file__).resolve().parents[2]
        config = PiperConfig.from_file(root / "configs" / "bipiper.yaml")
        calibrations = load_piper_gripper_calibrations(config.calibration_path)
        if set(calibrations) != {"left", "right"}:
            raise ValueError(f"Both grippers require calibration at {config.calibration_path}")
        checkpoint = _value(settings, "DREAM_CHECKPOINT", "dreamlabs/dream-1-beta")
        client.policy(_policy_config(checkpoint, arm_file, _embodiment_config(client, settings)))
        client = PiperPolicy(client, config)
        initial_pose = None
        if args.execute and config.inference_start.get("enabled", False):
            from .initial_pose import load_piper_initial_joint_pose
            start = config.inference_start
            if not start.get("pose_file"):
                raise ValueError("Execution requires the installation's measured inference.start.pose_file")
            if not all(np.isfinite(float(start.get(key, default))) and float(start.get(key, default)) > 0
                       for key, default in (("max_joint_speed_deg_s", 10.0), ("timeout_s", 45.0), ("tolerance_deg", 2.0))):
                raise ValueError("Initial pose motion limits must be finite and positive")
            initial_pose = load_piper_initial_joint_pose(Path(start["pose_file"]), selection=start.get("pose", "nearest_to_mean"))

        captures: dict[str, Any] = {}
        readers: dict[str, Any] = {}
        streamers: dict[str, PiperJointStreamer] = {}
        logger = RunLogger(args.log if args.execute else None)
        try:
            with ExitStack() as stack:
                for side, port in (("left", config.left_port), ("right", config.right_port)):
                    readers[side] = PiperFeedbackArm(port, calibrations[side])
                    stack.callback(readers[side].disconnect)
                for reader in readers.values():
                    reader.wait_ready()
                for name, spec in config.cameras.items():
                    captures[name] = _open_camera(spec)
                    stack.callback(captures[name].release)

                time.sleep(0.2)
                _, frames, observation, timestamp = _capture_observation(
                    captures, config.cameras, readers, args.prompt or ""
                )
                client.set_observation(frames, observation, timestamp=timestamp)
                if not args.execute:
                    action, timing, wall_ms = _get_action(client, None)
                    _print_latency(1, wall_ms, timing, client.mode)
                    print(json.dumps({"checkpoint": checkpoint, "action_keys": sorted(action),
                                      "solver": "custom_bimanual_piper", "ik_report": action["ik_report"]}, indent=2))
                    return 0

                print("URDF/TCP y calibración locales cargados. Revisa las vistas y mantén disponible el paro de emergencia.")
                input("Pulsa Enter para ejecutar la trayectoria limitada...")
                action, timing, wall_ms = _get_action(client, None)
                _print_latency(1, wall_ms, timing, client.mode)
                chunks = _chunk(action)
                for side in ("left", "right"):
                    arm = PiperSdkArm(
                        getattr(config, f"{side}_port"),
                        gripper_range=calibrations[side],
                        startup_speed_percent=config.startup_speed_percent,
                        speed_percent=40,
                        enable_timeout_s=config.enable_timeout_s,
                        gripper_effort=config.gripper_effort,
                        feedback=readers[side],
                    )
                    stack.callback(arm.disconnect)
                    streamer = PiperJointStreamer(
                        arm,
                        command_rate_hz=config.command_rate_hz,
                        max_joint_speed_deg_s=20.0,
                        max_joint_acceleration_deg_s2=60.0,
                    )
                    streamer.start()
                    stack.callback(streamer.stop)
                    streamers[side] = streamer
                    readers[side] = arm
                if initial_pose is not None:
                    start = config.inference_start
                    speed = float(start.get("max_joint_speed_deg_s", 10.0))
                    timeout = float(start.get("timeout_s", 45.0))
                    tolerance = float(start.get("tolerance_deg", 2.0))
                    if not all(np.isfinite(v) and v > 0 for v in (speed, timeout, tolerance)):
                        raise ValueError("Initial pose motion limits must be finite and positive")
                    for side, streamer in streamers.items():
                        streamer.set_max_joint_speed_deg_s(min(speed, 20.0))
                        streamer.set_target(initial_pose.joints[side])
                    deadline = time.monotonic() + timeout
                    while True:
                        for streamer in streamers.values():
                            streamer.raise_if_failed()
                        if all(np.max(np.abs(readers[side].read_joints_rad() - initial_pose.joints[side])) <= np.deg2rad(tolerance)
                               for side in streamers):
                            break
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Initial pose not reached by both Piper arms")
                        time.sleep(0.05)
                    for streamer in streamers.values():
                        streamer.set_max_joint_speed_deg_s(20.0)
                    # Discard actions from before the initial-pose transition.
                    _, frames, observation, timestamp = _capture_observation(captures, config.cameras, readers, args.prompt or "")
                    client.reset_episode()
                    client.set_observation(frames, observation, timestamp=timestamp)
                    action, _, _ = _get_action(client, None)
                    chunks = _chunk(action)
                print("Ejecución Dream activa; Ctrl-C detiene el ciclo.", flush=True)
                try:
                    _stream(
                        client,
                        captures,
                        config.cameras,
                        readers,
                        streamers,
                        args.prompt or "",
                        chunks,
                        None,
                        1,
                        logger,
                        args.max_duration_s,
                    )
                except KeyboardInterrupt:
                    print("\nEjecución detenida por el operador.")
        finally:
            logger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
