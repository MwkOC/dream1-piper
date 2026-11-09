"""Dream Labs API probe with opt-in EEF-to-joint Piper execution.

Usage: python tests/test_dream_api.py --models
       python tests/test_dream_api.py --infer --prompt "..."
       python tests/test_dream_api.py --infer --execute --prompt "..."
"""

import argparse
import base64
from concurrent.futures import Future, ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time
from contextlib import ExitStack

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.driver import PiperFeedbackArm, PiperJointStreamer, PiperSdkArm
from scripts.constants import PIPER_JOINT_LOWER_RAD, PIPER_JOINT_UPPER_RAD
from scripts.gripper_calibration import load_piper_gripper_calibrations
from scripts.kinematics import PiperKinematics
from scripts.piper import BiPiperConfig


def settings():
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, sep, value = line.partition("=")
            if not sep:
                raise ValueError(f"Invalid .env line: {key}")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def key_from_config(config):
    key = config.get("DREAM_API_KEY", "").strip()
    if not key or any(c.isspace() for c in key):
        raise ValueError("Set DREAM_API_KEY in .env")
    return key


def open_camera(spec):
    import cv2

    backend = cv2.CAP_V4L2 if spec.get("backend") == "V4L2" else cv2.CAP_ANY
    capture = cv2.VideoCapture(str(spec["index_or_path"]), backend)
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open camera: {spec['index_or_path']}")
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, int(spec["width"]))
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, int(spec["height"]))
    capture.set(cv2.CAP_PROP_FPS, int(spec["fps"]))
    return capture


def frame_b64(capture, spec):
    import cv2

    ok, image = capture.read()
    if not ok or image is None:
        raise RuntimeError(f"No frame from {spec['index_or_path']}")
    if spec["type"] == "zedmini":
        if image.shape[1] != int(spec["width"]):
            raise RuntimeError(f"Unexpected ZED stereo width: {image.shape[1]}")
        image = image[:, :image.shape[1] // 2]
    image = cv2.resize(image, (320, 176), interpolation=cv2.INTER_AREA)
    ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return base64.b64encode(jpeg.tobytes()).decode("ascii")


def capture_observation(captures, cameras, kin, readers, prompt, active_arms=None):
    """Read fresh robot state and camera frames in Dream's expected feature format."""
    active_arms = active_arms or {}
    state = {}
    for side in ("left", "right"):
        if side in active_arms:
            arm = active_arms[side]
            joints = arm.read_joints_rad()
            grip = arm.read_gripper_opening()
            state[side] = (joints, 0.0 if grip is None else grip)
        else:
            state[side] = readers[side].read()
    frames = {
        f"video.{role}": frame_b64(captures[name], cameras[name])
        for name, role in (("left", "wrist_l"), ("top", "overhead"), ("right", "wrist_r"))
    }
    observation = {"prompt": prompt}
    for side in ("left", "right"):
        joints, grip = state[side]
        pose = kin[side].forward_matrix(joints)
        observation[f"state.{side}_arm"] = [0.0] * 6
        observation[f"state.{side}_gripper"] = [grip]
        observation[f"state.{side}_grip"] = [grip]
        observation[f"state.{side}_eef_xyz"] = pose[:3, 3].tolist()
        observation[f"state.{side}_eef_rot6"] = pose[:3, :2].T.reshape(-1).tolist()
    return state, frames, observation


def solve_action_chunk(action, state, kin, checkpoint, timing, execute):
    per_key = action["per_key"]
    report = {
        "checkpoint": checkpoint,
        "action_keys": sorted(per_key),
        "timing": timing,
    }
    solved = {"left": [], "right": []}
    gripper_actions = {}
    for side in ("left", "right"):
        xyz = np.asarray(per_key[f"action.{side}_eef_xyz"], dtype=float)
        rot6 = np.asarray(per_key[f"action.{side}_eef_rot6"], dtype=float)
        if xyz.ndim != 2 or xyz.shape[1] != 3 or len(xyz) == 0 or rot6.shape != (len(xyz), 6):
            raise ValueError(f"Unexpected {side} EEF action shapes: {xyz.shape}, {rot6.shape}")
        if not np.isfinite(xyz).all() or not np.isfinite(rot6).all():
            raise ValueError(f"Non-finite {side} EEF action")
        report[side] = {
            "steps": len(xyz),
            "measured_joints_rad": state[side][0].tolist(),
            "first_eef_xyz_m": xyz[0].tolist(),
            "first_eef_rot6": rot6[0].tolist(),
        }
        if not execute:
            continue
        current_q = state[side][0].copy()
        for point, orientation in zip(xyz, rot6):
            q, position_error, rotation_error = kin[side].solve(point, orientation, current_q)
            if np.any(q < PIPER_JOINT_LOWER_RAD) or np.any(q > PIPER_JOINT_UPPER_RAD):
                raise ValueError(f"{side} IK solution exceeds physical Piper joint limits")
            solved[side].append((q, position_error, rotation_error))
            current_q = q
        for name in (f"action.{side}_gripper", f"action.{side}_grip"):
            if name in per_key:
                values = np.asarray(per_key[name], dtype=float).reshape(-1)
                if len(values) != len(solved[side]) or not np.isfinite(values).all():
                    raise ValueError(f"Unexpected gripper action values for {side}")
                if np.min(values) < -0.02 or np.max(values) > 1.02:
                    raise ValueError(f"Dream gripper action for {side} is outside [0, 1]")
                # Calibration maps [0, 1] aperture to Piper micrometers.
                previous = float(state[side][1])
                limited = []
                for value in np.clip(values, 0.0, 1.0):
                    previous += float(np.clip(value - previous, -0.1, 0.1))
                    limited.append(previous)
                gripper_actions[side] = np.asarray(limited)
                break
    if execute and len(solved["left"]) != len(solved["right"]):
        raise ValueError("Dream returned different action chunk lengths for left and right arms")
    return report, solved, gripper_actions


def request_action(client):
    """Return the chunk, client wire timing, and end-to-end get_action wall time."""
    started = time.monotonic()
    action = client.get_action()
    wall_ms = (time.monotonic() - started) * 1000.0
    return action, client.last_timing, wall_ms


def print_latency(cycle, wall_ms, timing, mode):
    timing = timing or {}
    print(json.dumps({
        "dream_request": cycle,
        "latency_wall_ms": round(wall_ms, 1),
        "latency_http_rtt_ms": timing.get("rtt_ms"),
        "model_inference_ms": timing.get("serve_infer_ms"),
        "gateway_ms": timing.get("gateway_ms"),
        "network_ms": timing.get("network_ms"),
        "pacing_mode": mode,
    }, separators=(",", ":")), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--models", action="store_true", help="Check key and list accessible checkpoints")
    choice.add_argument("--infer", action="store_true", help="Capture an observation and request one action chunk")
    parser.add_argument("--prompt", help="Instruction for the inference observation")
    parser.add_argument("--execute", action="store_true", help="Run continuous inference and control until Ctrl-C")
    args = parser.parse_args()
    if args.infer and (not args.prompt or not args.prompt.strip()):
        parser.error("--infer requires a non-empty --prompt")
    if args.execute and not args.infer:
        parser.error("--execute requires --infer")
    if args.models and args.prompt is not None:
        parser.error("--prompt is only valid with --infer")
    config = settings()
    key = key_from_config(config)
    import dream

    with dream.DreamClient(api_key=key) as client:
        if args.models:
            models = client.get_models()
            print(json.dumps([{"id": model.id, "servable": getattr(model, "servable", None)} for model in models], indent=2))
            return

        bipiper = yaml.safe_load((ROOT / "configs/bipiper.yaml").read_text(encoding="utf-8"))
        robot_cfg = bipiper["robot"]
        cameras = yaml.safe_load((ROOT / "configs/cameras.yaml").read_text(encoding="utf-8"))["cameras"]
        if robot_cfg["type"] != "bi_piper" or set(cameras) != {"left", "right", "top"}:
            raise ValueError("Expected bi_piper and left/top/right cameras")
        control = BiPiperConfig(
            id=robot_cfg["id"],
            left_port=robot_cfg["left_port"],
            right_port=robot_cfg["right_port"],
            command_rate_hz=float(robot_cfg["command_rate_hz"]),
        )
        calibration = Path(robot_cfg["gripper_calibration_path"]).expanduser()
        ranges = load_piper_gripper_calibrations(calibration)
        if set(ranges) != {"left", "right"}:
            raise ValueError(f"Both Piper grippers need calibration in {calibration}")
        urdf = Path(config["PIPER_URDF"]).expanduser()
        if not urdf.is_absolute():
            urdf = ROOT / urdf
        kin, readers, captures, streamers = {}, {}, {}, {}
        with ExitStack() as stack:
            for side in ("left", "right"):
                kin[side] = PiperKinematics(
                    urdf,
                    config[f"PIPER_{side.upper()}_BASE"],
                    config[f"PIPER_{side.upper()}_TCP"],
                    side,
                )
                readers[side] = PiperFeedbackArm(getattr(control, f"{side}_port"), ranges[side])
                stack.callback(
                    lambda side=side: readers[side].disconnect()
                    if readers.get(side) is not None else None
                )
            for name, spec in cameras.items():
                captures[name] = open_camera(spec)
                stack.callback(captures[name].release)

            time.sleep(0.2)
            state, frames, observation = capture_observation(
                captures, cameras, kin, readers, args.prompt
            )
            client.policy({
                "checkpoint": config["DREAM_CHECKPOINT"],
                "robot": "other_embodiment",
                "strict": False,
                "obs_window": 9,
                "obs_fps": 5,
                "action_hz": 30,
            })
            client.set_observation(frames, observation)

            if not args.execute:
                action, api_timing, api_wall_ms = request_action(client)
                print_latency(1, api_wall_ms, api_timing, client.mode)
                report, _, _ = solve_action_chunk(
                    action, state, kin, config["DREAM_CHECKPOINT"], api_timing, False
                )
                print(json.dumps(report, indent=2, default=str))
                return

            active_arms = {}
            cycle = 1
            print("Ejecución continua activa; Ctrl-C detiene el ciclo. Latencias Dream en ms.")
            try:
                with ThreadPoolExecutor(max_workers=2, thread_name_prefix="dream-piper") as workers:
                    action, api_timing, api_wall_ms = request_action(client)
                    print_latency(cycle, api_wall_ms, api_timing, client.mode)
                    report, solved, gripper_actions = solve_action_chunk(
                        action, state, kin, config["DREAM_CHECKPOINT"], api_timing, True
                    )
                    if not active_arms:
                        # Only enable the arms after the first complete chunk passed IK validation.
                        for side in ("left", "right"):
                            readers[side].disconnect()
                            readers[side] = None
                            arm = PiperSdkArm(
                                getattr(control, f"{side}_port"),
                                speed_percent=40,
                                gripper_range=ranges[side],
                            )
                            stack.callback(arm.disconnect)
                            streamer = PiperJointStreamer(
                                arm,
                                command_rate_hz=100.0,
                                max_joint_speed_deg_s=20.0,
                                max_joint_acceleration_deg_s2=60.0,
                            )
                            active_arms[side] = arm
                            streamers[side] = streamer
                            streamer.start()
                            stack.callback(streamer.stop)
                    frame_count = len(solved["left"])
                    index = 0
                    api_future: Future | None = None
                    prepared_future: Future | None = None

                    while True:
                        if index < frame_count:
                            started = time.monotonic()
                            for side in ("left", "right"):
                                q = solved[side][index][0]
                                grip = float(gripper_actions[side][index]) if side in gripper_actions else None
                                streamers[side].set_target(q, grip)
                            # Keep Dream's observation window and latest robot state fresh at 5 Hz.
                            if index % 6 == 0 or index == frame_count - 1:
                                state, frames, observation = capture_observation(
                                    captures, cameras, kin, readers, args.prompt, active_arms
                                )
                                client.set_observation(frames, observation)
                            time.sleep(max(0.0, 1.0 / 30.0 - (time.monotonic() - started)))
                            index += 1

                        remaining = frame_count - index
                        if api_future is None and prepared_future is None and client.refill_due(index, remaining):
                            # The SDK chooses sync/async from measured RTT and schedules the prefetch.
                            api_future = workers.submit(request_action, client)

                        if api_future is not None and api_future.done():
                            next_action, next_timing, next_wall_ms = api_future.result()
                            api_future = None
                            print_latency(cycle + 1, next_wall_ms, next_timing, client.mode)
                            # Solve in parallel with the active chunk so IK preparation consumes runway too.
                            state_snapshot = {
                                side: (joints.copy(), grip) for side, (joints, grip) in state.items()
                            }
                            prepared_future = workers.submit(
                                solve_action_chunk,
                                next_action,
                                state_snapshot,
                                kin,
                                config["DREAM_CHECKPOINT"],
                                next_timing,
                                True,
                            )

                        if prepared_future is not None:
                            async_horizon = client.mode == "async" and index >= client.execution_horizon
                            sync_chunk_done = client.mode == "sync" and index >= frame_count
                            if (async_horizon or sync_chunk_done) and prepared_future.done():
                                next_report, next_solved, next_gripper_actions = prepared_future.result()
                                report["execution"] = {
                                    "status": "action chunk streamed",
                                    "steps": frame_count,
                                    "prefetch_switch_after_steps": index,
                                    "max_position_ik_error_m": max(
                                        (item[1] for values in solved.values() for item in values), default=0.0
                                    ),
                                    "max_orientation_ik_error_deg": float(np.rad2deg(max(
                                        (item[2] for values in solved.values() for item in values), default=0.0
                                    ))),
                                    "gripper_actions": sorted(gripper_actions),
                                    "joint_speed_limit_deg_s": 20.0,
                                }
                                report["cycle"] = cycle
                                report["pacing_mode"] = client.mode
                                print(json.dumps(report, indent=2, default=str), flush=True)
                                cycle += 1
                                action, report = next_report, next_report
                                solved, gripper_actions = next_solved, next_gripper_actions
                                frame_count = len(solved["left"])
                                index = 0
                                prepared_future = None
                                continue

                        if index >= frame_count and prepared_future is not None:
                            # The chunk's runway is exhausted; hold position while IK finishes.
                            state, frames, observation = capture_observation(
                                captures, cameras, kin, readers, args.prompt, active_arms
                            )
                            client.set_observation(frames, observation)
                            time.sleep(0.2)
                            continue

                        if index >= frame_count and prepared_future is None:
                            # In sync mode, refill_due becomes true only here. The streamer holds its last target.
                            if api_future is None:
                                api_future = workers.submit(request_action, client)
                            while not api_future.done():
                                state, frames, observation = capture_observation(
                                    captures, cameras, kin, readers, args.prompt, active_arms
                                )
                                client.set_observation(frames, observation)
                                time.sleep(0.2)
                            next_action, next_timing, next_wall_ms = api_future.result()
                            api_future = None
                            print_latency(cycle + 1, next_wall_ms, next_timing, client.mode)
                            next_report, next_solved, next_gripper_actions = solve_action_chunk(
                                next_action, state, kin, config["DREAM_CHECKPOINT"], next_timing, True
                            )
                            report["execution"] = {"status": "action chunk streamed", "steps": frame_count}
                            report["cycle"] = cycle
                            report["pacing_mode"] = client.mode
                            print(json.dumps(report, indent=2, default=str), flush=True)
                            cycle += 1
                            action, report = next_action, next_report
                            solved, gripper_actions = next_solved, next_gripper_actions
                            frame_count = len(solved["left"])
                            index = 0
                            continue
            except KeyboardInterrupt:
                print("\nEjecución detenida por el operador.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Dream API probe: {exc}") from None
