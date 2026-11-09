"""Validation and loading for the extracted bimanual Piper configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PiperConfig:
    robot_id: str
    left_port: str
    right_port: str
    calibration_path: Path
    urdf: Path
    frames: dict[str, str]
    cameras: dict[str, dict[str, Any]]
    command_rate_hz: float
    max_joint_speed_deg_s: float
    max_joint_acceleration_deg_s2: float
    startup_speed_percent: int
    speed_percent: int
    enable_timeout_s: float
    gripper_effort: int
    gripper_action_tolerance: float
    home_max_joint_speed_deg_s: float
    home_timeout_s: float
    home_tolerance_deg: float
    inference_start: dict[str, Any]

    @classmethod
    def from_file(cls, path: Path) -> PiperConfig:
        source = Path(path).expanduser().resolve()
        document = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        robot = document.get("robot")
        if not isinstance(robot, dict) or robot.get("type") != "bi_piper":
            raise ValueError("configuration must declare robot.type=bi_piper")
        left, right = robot.get("left_port"), robot.get("right_port")
        if not left or not right or left == right:
            raise ValueError("left_port and right_port must be distinct")
        cameras = robot.get("cameras") or {}
        if set(cameras) != {"left", "right", "top"}:
            raise ValueError("configuration must define left, top and right cameras")
        frames = document.get("frames") or {}
        required_frames = {"left_base", "left_tcp", "right_base", "right_tcp"}
        if set(frames) != required_frames or any(not value for value in frames.values()):
            raise ValueError("configuration must define all Piper base/TCP frames")
        urdf = Path(document.get("urdf", "")).expanduser()
        if not urdf.is_absolute():
            urdf = source.parent / urdf
        calibration = Path(str(robot.get("gripper_calibration_path", ""))).expanduser()
        return cls(
            robot_id=str(robot.get("id", "")),
            left_port=str(left),
            right_port=str(right),
            calibration_path=calibration,
            urdf=urdf,
            frames={str(k): str(v) for k, v in frames.items()},
            cameras=cameras,
            command_rate_hz=float(robot.get("command_rate_hz", 100.0)),
            max_joint_speed_deg_s=float(robot.get("max_joint_speed_deg_s", 180.0)),
            max_joint_acceleration_deg_s2=float(robot.get("max_joint_acceleration_deg_s2", 720.0)),
            startup_speed_percent=int(robot.get("startup_speed_percent", 10)),
            speed_percent=int(robot.get("speed_percent", 80)),
            enable_timeout_s=float(robot.get("enable_timeout_s", 10.0)),
            gripper_effort=int(robot.get("gripper_effort", 1000)),
            gripper_action_tolerance=float(robot.get("gripper_action_tolerance", 0.1)),
            home_max_joint_speed_deg_s=float(robot.get("home_max_joint_speed_deg_s", 20.0)),
            home_timeout_s=float(robot.get("home_timeout_s", 30.0)),
            home_tolerance_deg=float(robot.get("home_tolerance_deg", 3.0)),
            inference_start=document.get("inference", {}).get("start", {}) or {},
        )


__all__ = ["PiperConfig"]
