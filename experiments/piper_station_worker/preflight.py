from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .config import EXPERIMENT_ROOT, load_dream, load_robot
from .dream_policy import validate_arm_file, validate_dream_schema
from scripts.joint_calibration import load_piper_joint_calibrations


def check(robot_path: Path, dream_path: Path, *, check_devices: bool) -> dict[str, object]:
    robot, dream = load_robot(robot_path), load_dream(dream_path)
    validate_dream_schema(robot.schema, dream)
    arm = validate_arm_file(dream.arm_file, require_confirmation=dream.require_tcp_confirmation)
    if check_devices:
        load_piper_joint_calibrations(robot.options.get("joint_calibration_path"))
        missing = [camera.device for camera in robot.cameras if not Path(camera.device).exists()]
        if missing:
            raise ValueError(f"camera device paths do not exist: {', '.join(missing)}")
        for port in (str(robot.options["left_port"]), str(robot.options["right_port"])):
            result = subprocess.run(["ip", "-details", "-json", "link", "show", port], capture_output=True, text=True, check=True, timeout=5)
            link = json.loads(result.stdout)[0]
            bitrate = link.get("linkinfo", {}).get("info_data", {}).get("bittiming", {}).get("bitrate")
            if "UP" not in link.get("flags", []) or bitrate != 1_000_000:
                raise ValueError(f"{port} must be UP at 1000000 bitrate")
    return {"robot": robot.name, "cameras": {camera.name: camera.device for camera in robot.cameras}, "can": {"left": robot.options["left_port"], "right": robot.options["right_port"]}, "arm": arm, "dream": {"checkpoint": dream.checkpoint, "dry_run": dream.dry_run, "solver": dream.solver}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the experimental Piper station and Dream worker")
    parser.add_argument("--robot-config", type=Path, default=EXPERIMENT_ROOT / "config/robot.yaml")
    parser.add_argument("--dream-config", type=Path, default=EXPERIMENT_ROOT / "config/dream.yaml")
    parser.add_argument("--check-devices", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(check(args.robot_config, args.dream_config, check_devices=args.check_devices), indent=2))
    except (
        OSError,
        RuntimeError,
        ValueError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        print(f"piper-station-worker preflight: failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
