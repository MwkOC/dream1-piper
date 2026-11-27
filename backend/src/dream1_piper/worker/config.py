from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .control import JointLimit, RobotSchema
from .settings import env_value, resolve_mode

ROOT = Path(__file__).resolve().parents[4]
EXPERIMENT_ROOT = ROOT / "experiments/piper_station_worker"


def load_yaml(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    with source.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream) or {}
    if not isinstance(value, dict):
        raise ValueError(f"{source} must contain a YAML mapping")
    return value


@dataclass(frozen=True)
class Camera:
    name: str
    device: str
    source_width: int
    source_height: int
    width: int
    height: int
    fps: float
    fourcc: str
    crop: str
    jpeg_quality: int = 85


@dataclass(frozen=True)
class RobotConfig:
    name: str
    version: int
    control_hz: float
    action_names: tuple[str, ...]
    joint_limits: tuple[dict[str, float], ...]
    station: dict[str, Any]
    options: dict[str, Any]
    cameras: tuple[Camera, ...]
    schema: RobotSchema


def load_robot(path: str | Path) -> RobotConfig:
    source = Path(path).expanduser()
    if not source.is_absolute() and not source.exists():
        source = ROOT / source
    value = load_yaml(source)
    schema = value["schema"]
    robot = value["robot"]
    if robot.get("driver") != "piper_bimanual":
        raise ValueError("experiment requires robot.driver=piper_bimanual")
    options = dict(robot["options"])
    if options.get("left_port") == options.get("right_port"):
        raise ValueError("left_port and right_port must be distinct")
    cameras = tuple(Camera(**camera) for camera in value["cameras"])
    if {camera.name for camera in cameras} != {"left", "top", "right"}:
        raise ValueError("experiment requires left, top, and right cameras")
    schema_config = dict(schema)
    schema_config.pop("camera_names", None)
    schema_config["action_names"] = tuple(str(name) for name in schema_config["action_names"])
    schema_config["state_names"] = tuple(str(name) for name in schema_config["state_names"])
    schema_config["joint_limits"] = tuple(
        JointLimit(**limit) for limit in schema_config["joint_limits"]
    )
    parsed_schema = RobotSchema(**schema_config)
    return RobotConfig(
        name=str(schema["name"]),
        version=int(schema.get("version", 1)),
        control_hz=float(schema["control_hz"]),
        action_names=tuple(schema["action_names"]),
        joint_limits=tuple(dict(limit) for limit in schema["joint_limits"]),
        station=dict(value["station"]),
        options=options,
        cameras=cameras,
        schema=parsed_schema,
    )


@dataclass(frozen=True)
class DreamConfig:
    station_url: str
    checkpoint: str
    task: str
    camera_roles: dict[str, str]
    timeout_ms: int
    obs_window: int
    obs_fps: float
    action_hz: float
    execution_horizon: int
    sync_above_ms: float
    action_timeout_s: float
    dry_run: bool
    solver: str
    first_chunk_timeout_s: float
    arm_file: Path
    require_tcp_confirmation: bool
    dls: dict[str, float]


def load_dream(path: str | Path, *, dry_run: bool | None = None) -> DreamConfig:
    source = Path(path).resolve()
    value = load_yaml(source)
    roles = {str(key): str(role) for key, role in value["camera_roles"].items()}
    if set(roles.items()) != {("left", "wrist_l"), ("top", "overhead"), ("right", "wrist_r")}:
        raise ValueError("camera_roles must map left/top/right to Dream-1 roles")
    arm_value = value.get("arm_file", "../assets/piper/piper_arm.json")
    arm_file = Path(str(arm_value)).expanduser()
    if not arm_file.is_absolute():
        arm_file = (source.parent / arm_file).resolve()
    dls = dict(value.get("dls") or {})
    return DreamConfig(
        station_url=str(env_value("RSTACK_DREAM_STATION_URL", value["station_url"])),
        checkpoint=str(env_value("RSTACK_DREAM_MODEL", value["checkpoint"])),
        task=str(env_value("RSTACK_DREAM_TASK", value["task"])),
        camera_roles=roles,
        timeout_ms=int(value["timeout_ms"]),
        obs_window=int(value["obs_window"]),
        obs_fps=float(value["obs_fps"]),
        action_hz=float(value["action_hz"]),
        execution_horizon=int(value["execution_horizon"]),
        sync_above_ms=float(value["sync_above_ms"]),
        action_timeout_s=float(value["action_timeout_s"]),
        dry_run=resolve_mode(value, override=dry_run) == "observe",
        solver=str(value.get("ik_solve", value.get("solver", "dls"))),
        first_chunk_timeout_s=float(value.get("first_chunk_timeout_s", 900)),
        arm_file=arm_file,
        require_tcp_confirmation=bool(value.get("require_tcp_confirmation", True)),
        dls={str(key): float(entry) for key, entry in dls.items()},
    )
