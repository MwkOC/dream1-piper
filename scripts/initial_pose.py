"""Load a dataset-derived initial joint pose for Piper inference."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .constants import (
    PIPER_JOINT_LOWER_RAD,
    PIPER_JOINT_UPPER_RAD,
)

SIDES = ("left", "right")


@dataclass(frozen=True)
class PiperInitialJointPose:
    """Validated joint targets selected from one dataset artifact."""

    joints: dict[str, np.ndarray]


def _mapping(value: Any, description: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Initial-pose YAML {description} must be a mapping")
    return value


def _sequence(value: Any, description: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"Initial-pose YAML {description} must be a sequence")
    return value


def load_piper_initial_joint_pose(
    path: Path,
    *,
    selection: str = "nearest_to_mean",
    required_sides: tuple[str, ...] = SIDES,
) -> PiperInitialJointPose:
    """Load and validate a named pose without relying on positional layout."""
    source_path = Path(path).expanduser().resolve()
    try:
        document = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Could not load Piper initial pose: {source_path}") from exc

    root = _mapping(document, "root")
    if root.get("schema_version") != 1 or root.get("kind") != "handumi_initial_joint_distribution":
        raise ValueError(f"Unsupported initial-pose schema: {source_path}")

    source = _mapping(root.get("source"), "source")
    if source.get("robot") != "piper":
        raise ValueError(f"Initial pose is not for Piper: {source_path}")

    layout = _mapping(root.get("layout"), "layout")
    names = [str(value) for value in _sequence(layout.get("names"), "layout.names")]
    units = [str(value) for value in _sequence(layout.get("units"), "layout.units")]
    if len(names) != len(units) or len(set(names)) != len(names):
        raise ValueError(f"Initial-pose names and units are inconsistent: {source_path}")

    recommended = _mapping(root.get("recommended"), "recommended")
    selected = _mapping(recommended.get(selection), f"recommended.{selection}")
    values = np.asarray(
        _sequence(selected.get("values"), f"recommended.{selection}.values"),
        dtype=np.float64,
    )
    if values.shape != (len(names),) or not np.isfinite(values).all():
        raise ValueError(f"Initial pose contains invalid values: {source_path}")
    named = dict(zip(names, zip(units, values, strict=True), strict=True))

    unknown_sides = set(required_sides) - set(SIDES)
    if unknown_sides:
        raise ValueError(f"Unknown Piper sides requested: {sorted(unknown_sides)}")

    joints: dict[str, np.ndarray] = {}
    for side in required_sides:
        joint_values = []
        for index in range(1, 7):
            name = f"{side}_joint{index}.pos"
            try:
                unit, value = named[name]
            except KeyError as exc:
                raise ValueError(f"Initial pose is missing {name}: {source_path}") from exc
            if unit != "rad":
                raise ValueError(f"Initial pose {name} must use radians: {source_path}")
            joint_values.append(float(value))
        arm = np.asarray(joint_values, dtype=np.float64)
        if np.any(arm < PIPER_JOINT_LOWER_RAD) or np.any(arm > PIPER_JOINT_UPPER_RAD):
            raise ValueError(f"Initial pose exceeds Piper joint limits for {side}: {source_path}")
        joints[side] = arm

    return PiperInitialJointPose(joints=joints)


__all__ = ["PiperInitialJointPose", "load_piper_initial_joint_pose"]
