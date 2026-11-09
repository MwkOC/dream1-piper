"""Probe Dream actions and optionally execute a validated Piper EEF chunk."""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
from contextlib import ExitStack
from pathlib import Path

import numpy as np

from .active_config import PiperConfig
from .active_driver import PiperFeedbackArm, PiperJointStreamer, PiperSdkArm
from .gripper_calibration import load_piper_gripper_calibrations
from .kinematics import PiperKinematics


def _frame(capture, spec: dict) -> str:
    import cv2

    ok, image = capture.read()
    if not ok or image is None:
        raise RuntimeError(f"No frame from {spec['index_or_path']}")
    if spec.get("type") == "zedmini":
        width = int(spec["width"])
        if image.shape[1] != width * 2:
            raise RuntimeError(f"Unexpected ZED stereo width: {image.shape[1]}")
        image = image[:, :width]
    image = cv2.resize(image, (320, 176), interpolation=cv2.INTER_AREA)
    ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return base64.b64encode(jpeg.tobytes()).decode("ascii")


def _open_camera(spec: dict):
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


def _require_key(settings: dict[str, str]) -> str:
    key = settings.get("DREAM_API_KEY", os.environ.get("DREAM_API_KEY", "")).strip()
    if not key or any(char.isspace() for char in key):
        raise ValueError("Set DREAM_API_KEY in .env or the environment")
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--models", action="store_true")
    choice.add_argument("--infer", action="store_true")
    parser.add_argument("--prompt")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
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

        config = PiperConfig.from_file(Path(__file__).resolve().parents[2] / "configs" / "bipiper.yaml")
        calibrations = load_piper_gripper_calibrations(config.calibration_path)
        if set(calibrations) != {"left", "right"}:
            raise ValueError(f"Both grippers require calibration at {config.calibration_path}")
        cameras, readers, captures = {}, {}, {}
        kinematics = {
            side: PiperKinematics(config.urdf, config.frames[f"{side}_base"], config.frames[f"{side}_tcp"], side)
            for side in ("left", "right")
        }
        with ExitStack() as stack:
            for side, port in (("left", config.left_port), ("right", config.right_port)):
                readers[side] = PiperFeedbackArm(port, calibrations[side])
                stack.callback(readers[side].disconnect)
            for name, spec in config.cameras.items():
                captures[name] = _open_camera(spec)
                stack.callback(captures[name].release)
                cameras[name] = spec
            time.sleep(0.2)
            state = {side: readers[side].read() for side in ("left", "right")}
            frames = {
                f"video.{role}": _frame(captures[name], cameras[name])
                for name, role in (("left", "wrist_l"), ("top", "overhead"), ("right", "wrist_r"))
            }
            observation = {"prompt": args.prompt}
            for side in ("left", "right"):
                joints, opening = state[side]
                pose = kinematics[side].forward_matrix(joints)
                observation[f"state.{side}_arm"] = [0.0] * 6
                observation[f"state.{side}_gripper"] = [opening]
                observation[f"state.{side}_eef_xyz"] = pose[:3, 3].tolist()
                observation[f"state.{side}_eef_rot6"] = pose[:3, :2].T.reshape(-1).tolist()

            checkpoint = settings.get("DREAM_CHECKPOINT", os.environ.get("DREAM_CHECKPOINT", "dreamlabs/dream-1-beta"))
            client.policy({"checkpoint": checkpoint, "robot": "other_embodiment", "strict": False})
            client.set_observation(frames, observation)
            action = client.get_action()["per_key"]
            report = {"checkpoint": checkpoint, "action_keys": sorted(action)}
            solved: dict[str, list[tuple[np.ndarray, float, float]]] = {"left": [], "right": []}
            grippers: dict[str, np.ndarray] = {}
            for side in ("left", "right"):
                xyz = np.asarray(action[f"action.{side}_eef_xyz"], dtype=float)
                rot6 = np.asarray(action[f"action.{side}_eef_rot6"], dtype=float)
                if xyz.ndim != 2 or xyz.shape[1] != 3 or rot6.shape != (len(xyz), 6) or len(xyz) == 0:
                    raise ValueError(f"Unexpected {side} EEF action shapes: {xyz.shape}, {rot6.shape}")
                if not np.isfinite(xyz).all() or not np.isfinite(rot6).all():
                    raise ValueError(f"Non-finite {side} EEF action")
                report[side] = {"steps": len(xyz), "first_eef_xyz_m": xyz[0].tolist()}
                if args.execute:
                    seed = state[side][0].copy()
                    for point, orientation in zip(xyz, rot6):
                        solved[side].append(kinematics[side].solve(point, orientation, seed))
                        seed = solved[side][-1][0]
                    for key in (f"action.{side}_gripper", f"action.{side}_grip"):
                        if key in action:
                            values = np.asarray(action[key], dtype=float).reshape(-1)
                            if len(values) != len(xyz) or not np.isfinite(values).all():
                                raise ValueError(f"Invalid gripper action for {side}")
                            if np.min(values) < -0.02 or np.max(values) > 1.02:
                                raise ValueError(f"Gripper action for {side} is outside [0, 1]")
                            grippers[side] = np.clip(values, 0.0, 1.0)
                            break
            if not args.execute:
                print(json.dumps(report, indent=2))
                return 0
            if len(solved["left"]) != len(solved["right"]):
                raise ValueError("Dream returned different chunk lengths")
            for side in ("left", "right"):
                readers[side].disconnect()
                readers[side] = None
                arm = PiperSdkArm(
                    config.left_port if side == "left" else config.right_port,
                    startup_speed_percent=config.startup_speed_percent,
                    speed_percent=40,
                    enable_timeout_s=config.enable_timeout_s,
                    gripper_effort=config.gripper_effort,
                    gripper_range=calibrations[side],
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
                readers[side] = streamer
            period = 1.0 / 30.0
            for index in range(len(solved["left"])):
                started = time.monotonic()
                for side in ("left", "right"):
                    target = solved[side][index][0]
                    grip = float(grippers[side][index]) if side in grippers else None
                    readers[side].set_target(target, grip)
                time.sleep(max(0.0, period - (time.monotonic() - started)))
            report["execution"] = {"status": "action chunk streamed", "steps": len(solved["left"])}
            print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
