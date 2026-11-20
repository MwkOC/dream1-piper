"""Explicit conversion between Piper SDK feedback and canonical joint space."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .constants import validate_joint_feedback, validate_joint_target

SIDES = ("left", "right")
CALIBRATION_ENV_VAR = "MU_PIPER_JOINT_CALIBRATION"


@dataclass(frozen=True)
class PiperJointCalibration:
    """A reversible SDK-radian to canonical-radian calibration for one arm."""

    signs: np.ndarray
    offsets_rad: np.ndarray
    source: str = "measured calibration"

    def __post_init__(self) -> None:
        signs = np.asarray(self.signs, dtype=np.float64)
        offsets = np.asarray(self.offsets_rad, dtype=np.float64)
        if signs.shape != (6,) or not np.all(np.isin(signs, (-1.0, 1.0))):
            raise ValueError("Piper joint calibration signs must be six values of -1 or 1")
        if offsets.shape != (6,) or not np.isfinite(offsets).all():
            raise ValueError("Piper joint calibration offsets_rad must contain six finite radians")
        object.__setattr__(self, "signs", signs.copy())
        object.__setattr__(self, "offsets_rad", offsets.copy())

    @classmethod
    def identity(cls) -> "PiperJointCalibration":
        """Return a test-only identity calibration.

        Production hardware must load a confirmed calibration YAML instead.
        """
        return cls(np.ones(6), np.zeros(6), source="test identity calibration")

    def normalize_feedback(self, raw_sdk_radians: np.ndarray) -> np.ndarray:
        raw = validate_joint_feedback(raw_sdk_radians)
        canonical = self.signs * raw + self.offsets_rad
        try:
            return validate_joint_target(canonical)
        except ValueError as exc:
            raise ValueError(
                f"calibrated Piper feedback from {self.source} is outside command coordinates: {exc}"
            ) from exc

    def sdk_target(self, canonical_radians: np.ndarray) -> np.ndarray:
        canonical = validate_joint_target(canonical_radians)
        return self.signs * (canonical - self.offsets_rad)


def default_piper_joint_calibration_path() -> Path:
    override = os.environ.get(CALIBRATION_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[1] / "outputs" / "calibration" / "bipiper-joint-calibration.yaml"


def _calibration_path(path: Path | None) -> Path:
    source = Path(path or default_piper_joint_calibration_path()).expanduser()
    return source if source.is_absolute() else Path(__file__).resolve().parents[1] / source


def _arm_calibration(side: str, value: Any, source: Path) -> PiperJointCalibration:
    if not isinstance(value, Mapping):
        raise ValueError(f"Piper joint calibration for {side} must be a mapping: {source}")
    try:
        signs = value["signs"]
        offsets_rad = value["offsets_rad"]
    except KeyError as exc:
        raise ValueError(
            f"Piper joint calibration for {side} requires signs and offsets_rad: {source}"
        ) from exc
    return PiperJointCalibration(signs, offsets_rad, source=f"{source} ({side})")


def load_piper_joint_calibrations(path: Path | None = None) -> dict[str, PiperJointCalibration]:
    """Load a complete, human-confirmed calibration for both physical arms."""
    source = _calibration_path(path)
    if not source.exists():
        raise RuntimeError(
            "Piper joint calibration is required before motors can be enabled; "
            f"expected a confirmed file at {source}"
        )
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Could not load Piper joint calibration: {source}") from exc
    if not isinstance(data, Mapping):
        raise ValueError(f"Piper joint calibration must be a mapping: {source}")
    if data.get("schema_version") != 1 or data.get("kind") != "piper_joint_calibration":
        raise ValueError(f"Unsupported Piper joint calibration schema: {source}")
    if data.get("confirmed") is not True:
        raise RuntimeError(
            f"Piper joint calibration is not confirmed: {source}. "
            "Verify signs and offsets with the robot supported, then set confirmed: true."
        )
    arms = data.get("arms")
    if not isinstance(arms, Mapping):
        raise ValueError(f"Piper joint calibration requires an arms mapping: {source}")
    missing = [side for side in SIDES if side not in arms]
    if missing:
        raise ValueError(f"Piper joint calibration is missing sides {missing}: {source}")
    return {side: _arm_calibration(side, arms[side], source) for side in SIDES}


__all__ = [
    "CALIBRATION_ENV_VAR",
    "PiperJointCalibration",
    "default_piper_joint_calibration_path",
    "load_piper_joint_calibrations",
]
