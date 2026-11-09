"""Persistence helpers for machine-local Piper gripper limits."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .active_driver import PiperGripperRange

SIDES = ("left", "right")
CALIBRATION_ENV_VAR = "MU_PIPER_GRIPPER_CALIBRATION"


def default_piper_gripper_calibration_path() -> Path:
    """Return the per-machine calibration path, allowing an env override."""
    override = os.environ.get(CALIBRATION_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".mu-robotics" / "bipiper.yaml"


def _validated_range(side: str, value: Any) -> PiperGripperRange:
    if not isinstance(value, Mapping):
        raise ValueError(f"Piper gripper calibration for {side} must be a mapping")  # noqa: TRY004
    try:
        closed = int(value["closed_microm"])
        opened = int(value["open_microm"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"Piper gripper calibration for {side} requires integer "
            "closed_microm and open_microm values"
        ) from exc
    return PiperGripperRange(closed, opened, source="measured calibration")


def load_piper_gripper_calibrations(
    path: Path | None = None,
) -> dict[str, PiperGripperRange]:
    """Load every complete per-side measured range from YAML."""
    source = Path(path or default_piper_gripper_calibration_path()).expanduser()
    if not source.exists():
        return {}
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Could not load Piper gripper calibration: {source}") from exc
    if not isinstance(data, Mapping):
        raise ValueError(f"Piper gripper calibration must be a mapping: {source}")  # noqa: TRY004
    return {side: _validated_range(side, data[side]) for side in SIDES if side in data}


def save_piper_gripper_calibrations(
    calibrations: Mapping[str, PiperGripperRange],
    path: Path | None = None,
) -> Path:
    """Merge and persist measured ranges while preserving unselected sides."""
    destination = Path(path or default_piper_gripper_calibration_path()).expanduser()
    merged = load_piper_gripper_calibrations(destination)
    for side, gripper_range in calibrations.items():
        if side not in SIDES:
            raise ValueError(f"Invalid Piper side: {side!r}")
        merged[side] = PiperGripperRange(
            int(gripper_range.min_microm),
            int(gripper_range.max_microm),
            source="measured calibration",
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = {
        side: {
            "closed_microm": merged[side].min_microm,
            "open_microm": merged[side].max_microm,
        }
        for side in SIDES
        if side in merged
    }
    destination.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    return destination


__all__ = [
    "CALIBRATION_ENV_VAR",
    "default_piper_gripper_calibration_path",
    "load_piper_gripper_calibrations",
    "save_piper_gripper_calibrations",
]
