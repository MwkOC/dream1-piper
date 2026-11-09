"""Active Piper robot exports consolidated from the temasA implementation."""

from __future__ import annotations

from .robot import BiPiper, BiPiperConfig, RobotConfig


def registered_robot_types() -> dict[str, type]:
    return dict(getattr(RobotConfig, "registry", {}))


__all__ = ["BiPiper", "BiPiperConfig", "registered_robot_types"]
