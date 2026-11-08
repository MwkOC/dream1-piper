"""Local ``bi_piper`` registration and controller factory.

LeRobot is optional: the project registry remains usable for configuration and
hardware tests even when the optional LeRobot package is not installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from .active_config import PiperConfig

try:
    from lerobot.robots import RobotConfig
except ImportError:
    class RobotConfig:
        registry: ClassVar[dict[str, type]] = {}

        @classmethod
        def register_subclass(cls, name: str):
            def decorator(subclass: type) -> type:
                cls.registry[name] = subclass
                return subclass

            return decorator


@RobotConfig.register_subclass("bi_piper")
@dataclass
class BiPiperConfig(RobotConfig):
    """Configuration object matching the extracted ``bi_piper`` robot ID."""

    config_path: Path = Path(__file__).with_name("hardware_config.yaml")
    robot_type: str = "bi_piper"

    def load(self) -> PiperConfig:
        config = PiperConfig.from_file(self.config_path)
        if config.robot_id != self.robot_type:
            raise ValueError(f"expected robot id {self.robot_type!r}, got {config.robot_id!r}")
        return config


def registered_robot_types() -> dict[str, type]:
    return dict(getattr(RobotConfig, "registry", {}))


__all__ = ["BiPiperConfig", "registered_robot_types"]
