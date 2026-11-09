"""Validation and loading for the extracted bimanual Piper configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


_DEFAULT_URDF = Path(__file__).with_name("assets") / "piper.urdf"


def _urdf_frames(urdf: Path) -> dict[str, str]:
    """Return the nominal Piper frames exposed by the repository URDF."""
    import xml.etree.ElementTree as ET

    links = {node.get("name") for node in ET.parse(urdf).getroot().findall("link")}
    frames = {
        "left_base": "left_base_link",
        "left_tcp": "left_tcp",
        "right_base": "right_base_link",
        "right_tcp": "right_tcp",
    }
    missing = [name for name in frames.values() if name not in links]
    if missing:
        raise ValueError(f"URDF is missing Piper frames: {missing}")
    return frames


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
        inference_robot = (document.get("inference") or {}).get("robot") or {}
        if not isinstance(inference_robot, dict):
            raise ValueError("configuration inference.robot must be a mapping")
        effective_robot = {**robot, **inference_robot}
        left, right = effective_robot.get("left_port"), effective_robot.get("right_port")
        if not left or not right or left == right:
            raise ValueError("left_port and right_port must be distinct")
        cameras = effective_robot.get("cameras") or {}
        if set(cameras) != {"left", "right", "top"}:
            raise ValueError("configuration must define left, top and right cameras")
        urdf = _DEFAULT_URDF
        frames = _urdf_frames(urdf)
        calibration = Path(str(effective_robot.get("gripper_calibration_path", ""))).expanduser()
        return cls(
            robot_id=str(effective_robot.get("id", "")),
            left_port=str(left),
            right_port=str(right),
            calibration_path=calibration,
            urdf=urdf,
            frames={str(k): str(v) for k, v in frames.items()},
            cameras=cameras,
            command_rate_hz=float(effective_robot.get("command_rate_hz", 100.0)),
            max_joint_speed_deg_s=float(effective_robot.get("max_joint_speed_deg_s", 180.0)),
            max_joint_acceleration_deg_s2=float(effective_robot.get("max_joint_acceleration_deg_s2", 720.0)),
            startup_speed_percent=int(effective_robot.get("startup_speed_percent", 10)),
            speed_percent=int(effective_robot.get("speed_percent", 80)),
            enable_timeout_s=float(effective_robot.get("enable_timeout_s", 10.0)),
            gripper_effort=int(effective_robot.get("gripper_effort", 1000)),
            gripper_action_tolerance=float(effective_robot.get("gripper_action_tolerance", 0.1)),
            home_max_joint_speed_deg_s=float(effective_robot.get("home_max_joint_speed_deg_s", 20.0)),
            home_timeout_s=float(effective_robot.get("home_timeout_s", 30.0)),
            home_tolerance_deg=float(effective_robot.get("home_tolerance_deg", 3.0)),
            inference_start=document.get("inference", {}).get("start", {}) or {},
        )


__all__ = ["PiperConfig"]
