"""LeRobot-compatible Piper robot with MU-native CAN control."""

from __future__ import annotations

import logging
import time
from contextlib import suppress
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar, Literal

import numpy as np

try:
    from lerobot.cameras import CameraConfig
    from lerobot.robots import Robot, RobotConfig
    from mu.hardware.cameras.utils import (
        camera_config_from_dict,
        make_mu_camera_from_configs,
    )
except ImportError:
    # The Dream API test captures cameras with OpenCV. Keep native Piper
    # joint control usable when the optional LeRobot/MU stack is absent.
    CameraConfig = Any

    @dataclass(kw_only=True)
    class RobotConfig:
        id: str | None = None
        registry: ClassVar[dict[str, type]] = {}

        @classmethod
        def register_subclass(cls, name: str):
            def decorator(subclass: type) -> type:
                cls.registry[name] = subclass
                return subclass

            return decorator

        def __post_init__(self) -> None:
            pass

    class Robot:
        def __init__(self, config: RobotConfig) -> None:
            self.config = config

    def camera_config_from_dict(_config: dict[str, Any]) -> Any:
        raise RuntimeError("Camera configuration requires lerobot and mu")

    def make_mu_camera_from_configs(configs: dict[str, Any]) -> dict[str, Any]:
        if configs:
            raise RuntimeError("Cameras in PiperConfig require lerobot and mu")
        return {}
from .active_driver import ARM_JOINT_COUNT, PiperJointStreamer, PiperSdkArm
from .gripper_calibration import load_piper_gripper_calibrations
from .initial_pose import (
    PiperInitialJointPose,
    load_piper_initial_joint_pose,
)

logger = logging.getLogger(__name__)

# The teleoperation home belongs to Piper itself, not a rig or HandUMI config.
# Joint order is J1..J6; the gripper always starts fully closed.
PIPER_HOME_POSITION_RAD: dict[str, tuple[float, ...]] = {
    # Use the right arm's preferred wrist posture on both sides.
    "left": (0.0, 0.0, 0.0, 0.0, float(np.deg2rad(25.0)), 0.0),
    "right": (0.0, 0.0, 0.0, 0.0, float(np.deg2rad(25.0)), 0.0),
}
PIPER_HOME_GRIPPER_OPENING = 0.0
PIPER_RESET_GRIPPER_OPENING = 1.0
PIPER_GRIPPER_POSITION_TOLERANCE = 0.05


def piper_home_position(side: str) -> np.ndarray:
    try:
        return np.asarray(PIPER_HOME_POSITION_RAD[side], dtype=np.float64).copy()
    except KeyError as exc:
        raise ValueError("Piper side must be 'left' or 'right'") from exc


def piper_inference_home_position() -> np.ndarray:
    """Return the all-zero body target used only after inference rollouts."""
    return np.zeros(ARM_JOINT_COUNT, dtype=np.float64)


@dataclass
class PiperInferenceStartConfig:
    """Optional dataset-derived pose used to prepare Piper for inference."""

    enabled: bool = False
    pose_file: Path | None = None
    pose: Literal["mean", "median", "nearest_to_mean"] = "nearest_to_mean"
    max_joint_speed_deg_s: float = 10.0
    timeout_s: float = 45.0
    tolerance_deg: float = 2.0

    def __post_init__(self) -> None:
        if self.enabled and self.pose_file is None:
            raise ValueError("inference_start.pose_file is required when enabled")
        motion_limits = (
            self.max_joint_speed_deg_s,
            self.timeout_s,
            self.tolerance_deg,
        )
        if not all(np.isfinite(value) and value > 0.0 for value in motion_limits):
            raise ValueError("inference_start motion limits must be positive")


@RobotConfig.register_subclass("piper")
@dataclass
class PiperConfig(RobotConfig):
    port: str
    side: Literal["left", "right"] = "left"
    cameras: dict[str, CameraConfig] = field(default_factory=dict)
    command_rate_hz: float = 100.0
    max_joint_speed_deg_s: float = 180.0
    max_joint_acceleration_deg_s2: float = 720.0
    home_max_joint_speed_deg_s: float = 20.0
    home_timeout_s: float = 30.0
    home_tolerance_deg: float = 3.0
    startup_speed_percent: int = 10
    speed_percent: int = 80
    enable_timeout_s: float = 10.0
    gripper_effort: int = 1000
    gripper_action_tolerance: float = 0.1
    gripper_calibration_path: Path | None = None
    inference_start: PiperInferenceStartConfig = field(default_factory=PiperInferenceStartConfig)

    def __post_init__(self) -> None:
        if isinstance(self.inference_start, dict):
            self.inference_start = PiperInferenceStartConfig(**self.inference_start)
        if self.side not in ("left", "right"):
            raise ValueError("side must be 'left' or 'right'")
        if not np.isfinite(self.gripper_action_tolerance) or self.gripper_action_tolerance < 0.0:
            raise ValueError("gripper_action_tolerance must be finite and >= 0")
        for key, value in list(self.cameras.items()):
            if isinstance(value, dict):
                self.cameras[key] = camera_config_from_dict(value)
        super().__post_init__()


class Piper(Robot):
    config_class = PiperConfig
    name = "piper"

    def __init__(self, config: PiperConfig):
        super().__init__(config)
        self.config = config
        self.cameras = make_mu_camera_from_configs(config.cameras)
        self._arm: PiperSdkArm | None = None
        self._streamer: PiperJointStreamer | None = None
        self._last_gripper_opening = PIPER_HOME_GRIPPER_OPENING
        self._home_deadline_s: float | None = None
        self._home_target: np.ndarray | None = None
        self._home_label = "joint pose"
        self._initial_pose = self._load_initial_pose()

    def _load_initial_pose(self) -> PiperInitialJointPose | None:
        config = self.config.inference_start
        if not config.enabled or config.pose_file is None:
            return None
        return load_piper_initial_joint_pose(
            config.pose_file,
            selection=config.pose,
            required_sides=(self.config.side,),
        )

    @cached_property
    def action_features(self) -> dict[str, type]:
        return {f"joint_{index}.pos": float for index in range(ARM_JOINT_COUNT + 1)}

    @cached_property
    def observation_features(self) -> dict[str, type | tuple[int, int, int]]:
        images = {name: (camera.height, camera.width, 3) for name, camera in self.cameras.items()}
        return self.action_features | images

    @property
    def is_connected(self) -> bool:
        return self._arm is not None and self._streamer is not None

    @property
    def is_calibrated(self) -> bool:
        return True

    def connect(self, calibrate: bool = True) -> None:
        del calibrate
        if self.is_connected:
            raise RuntimeError(f"{self} already connected")
        gripper_range = load_piper_gripper_calibrations(self.config.gripper_calibration_path).get(
            self.config.side
        )
        arm = PiperSdkArm(
            self.config.port,
            startup_speed_percent=self.config.startup_speed_percent,
            speed_percent=self.config.speed_percent,
            enable_timeout_s=self.config.enable_timeout_s,
            gripper_effort=self.config.gripper_effort,
            gripper_range=gripper_range,
        )
        streamer = PiperJointStreamer(
            arm,
            command_rate_hz=self.config.command_rate_hz,
            max_joint_speed_deg_s=self.config.max_joint_speed_deg_s,
            max_joint_acceleration_deg_s2=self.config.max_joint_acceleration_deg_s2,
        )
        try:
            streamer.start()
            for camera in self.cameras.values():
                camera.connect()
        except BaseException:
            with suppress(Exception):
                streamer.stop()
            arm.disconnect()
            raise
        self._arm, self._streamer = arm, streamer

    def disconnect(self) -> None:
        if self._streamer is not None:
            with suppress(Exception):
                self._streamer.stop()
        if self._arm is not None:
            with suppress(Exception):
                self._arm.disconnect()
        for camera in self.cameras.values():
            with suppress(Exception):
                camera.disconnect()
        self._arm = self._streamer = None
        self._home_deadline_s = None
        self._home_target = None

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        pass

    def read_joints_rad(self) -> np.ndarray:
        arm, streamer = self._require_connected()
        streamer.raise_if_failed()
        return arm.read_joints_rad()

    def get_observation(self) -> dict[str, Any]:
        arm, _ = self._require_connected()
        joints = self.read_joints_rad()
        opening = arm.read_gripper_opening()
        if opening is not None:
            self._last_gripper_opening = opening
        observation: dict[str, Any] = {
            **{f"joint_{index}.pos": float(value) for index, value in enumerate(joints)},
            "joint_6.pos": self._last_gripper_opening,
        }
        for name, camera in self.cameras.items():
            observation[name] = camera.async_read()
        return observation

    def send_joints(self, joints: np.ndarray, gripper_opening: float) -> None:
        _, streamer = self._require_connected()
        values = np.asarray(joints, dtype=np.float64).reshape(ARM_JOINT_COUNT)
        if not np.isfinite(values).all() or not np.isfinite(gripper_opening):
            raise ValueError("Piper action must contain finite values")
        tolerance = self.config.gripper_action_tolerance
        if not -tolerance <= gripper_opening <= 1.0 + tolerance:
            raise ValueError(
                "Piper gripper opening is too far outside [0, 1]: "
                f"got {gripper_opening:.6g}, tolerated range is "
                f"[{-tolerance:.6g}, {1.0 + tolerance:.6g}]"
            )
        clipped_opening = float(np.clip(gripper_opening, 0.0, 1.0))
        streamer.set_target(values, clipped_opening)
        self._last_gripper_opening = clipped_opening

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        joints = np.asarray([action[f"joint_{index}.pos"] for index in range(6)], dtype=np.float64)
        self.send_joints(joints, float(action["joint_6.pos"]))
        return {key: float(value) for key, value in action.items()}

    def control_snapshot(self) -> dict[str, dict[str, float | bool | int]]:
        """Return control state plus temperature, collision, torque and fault telemetry."""
        arm, streamer = self._require_connected()
        state = streamer.snapshot()
        measured = arm.read_joints_rad()
        result = {
            "stream_target": {
                f"joint_{index}.pos": float(value) for index, value in enumerate(state["target"])
            },
            "stream_command": {
                f"joint_{index}.pos": float(value) for index, value in enumerate(state["command"])
            },
            "stream_velocity": {
                f"joint_{index}.pos": float(value) for index, value in enumerate(state["velocity"])
            },
            "measured": {
                f"joint_{index}.pos": float(value) for index, value in enumerate(measured)
            },
        }
        diagnostics = arm.read_motor_diagnostics()
        for stage, values in diagnostics.items():
            if stage == "arm_status":
                result[stage] = {"arm": int(values)}
            else:
                result[stage] = {
                    f"joint_{index}.pos": bool(value)
                    if np.issubdtype(np.asarray(values).dtype, np.bool_)
                    else float(value)
                    for index, value in enumerate(values)
                }
        return result

    def stop_motion(self) -> None:
        """Soft-stop at measured feedback while keeping the arm enabled."""
        arm, streamer = self._require_connected()
        opening = arm.read_gripper_opening()
        streamer.set_target(arm.read_joints_rad(), opening)
        if opening is not None:
            self._last_gripper_opening = opening

    def to_home(self) -> None:
        self.start_home()
        try:
            while True:
                if self.poll_home():
                    return
                time.sleep(0.05)
        finally:
            self.cancel_home()

    def start_home(self) -> None:
        """Start a home trajectory without blocking the caller's control loop."""
        self._start_home(PIPER_HOME_GRIPPER_OPENING)

    def start_home_preserving_gripper(self) -> None:
        """Start an inference home trajectory without changing the aperture."""
        arm, _ = self._require_connected()
        opening = arm.read_gripper_opening()
        if opening is None:
            opening = self._last_gripper_opening
        self._last_gripper_opening = float(opening)
        self._start_home(float(opening), target=piper_inference_home_position())

    def _start_home(self, gripper_opening: float, *, target: np.ndarray | None = None) -> None:
        self.start_joint_move(
            piper_home_position(self.config.side) if target is None else target,
            gripper_opening=gripper_opening,
            max_joint_speed_deg_s=self.config.home_max_joint_speed_deg_s,
            timeout_s=self.config.home_timeout_s,
            label="teleoperation home",
        )

    def start_joint_move(
        self,
        joints: np.ndarray,
        *,
        gripper_opening: float | None,
        max_joint_speed_deg_s: float,
        timeout_s: float,
        label: str,
    ) -> None:
        """Start a bounded joint-space move from the current stream command."""
        _, streamer = self._require_connected()
        target = np.asarray(joints, dtype=np.float64).reshape(ARM_JOINT_COUNT)
        if not np.isfinite(target).all():
            raise ValueError("Piper joint target must contain finite values")
        streamer.set_max_joint_speed_deg_s(max_joint_speed_deg_s)
        try:
            streamer.set_target(target, gripper_opening)
            self._home_target = target.copy()
            self._home_label = label
            self._home_deadline_s = time.monotonic() + timeout_s
        except BaseException:
            self._home_deadline_s = None
            self._home_target = None
            streamer.set_max_joint_speed_deg_s(self.config.max_joint_speed_deg_s)
            raise

    def poll_home(self) -> bool:
        """Return whether an active non-blocking home trajectory has finished."""
        return self.poll_joint_move(self.config.home_tolerance_deg)

    def poll_joint_move(self, tolerance_deg: float) -> bool:
        """Poll measured feedback for the active bounded joint-space move."""
        arm, _ = self._require_connected()
        if self._home_deadline_s is None or self._home_target is None:
            return True
        tolerance = np.deg2rad(tolerance_deg)
        if np.max(np.abs(arm.read_joints_rad() - self._home_target)) <= tolerance:
            self.cancel_joint_move()
            return True
        if time.monotonic() >= self._home_deadline_s:
            label = self._home_label
            self.stop_motion()
            self.cancel_joint_move()
            raise TimeoutError(f"{self.config.port}: Piper did not reach {label}")
        return False

    def cancel_home(self) -> None:
        """Restore normal streaming limits after a home trajectory."""
        self.cancel_joint_move()

    def cancel_joint_move(self) -> None:
        """Restore normal streaming limits after a bounded joint-space move."""
        if self._home_deadline_s is None:
            return
        _, streamer = self._require_connected()
        self._home_deadline_s = None
        self._home_target = None
        streamer.set_max_joint_speed_deg_s(self.config.max_joint_speed_deg_s)

    def start_gripper_reset_stage(self, opening: float) -> None:
        """Command one gripper stage while holding the arm at home."""
        _, streamer = self._require_connected()
        streamer.set_target(piper_inference_home_position(), opening)
        self._last_gripper_opening = float(opening)
        self._home_deadline_s = time.monotonic() + self.config.home_timeout_s

    def poll_gripper_reset_stage(self, opening: float) -> bool:
        """Return whether the gripper reached the requested reset aperture."""
        arm, _ = self._require_connected()
        measured = arm.read_gripper_opening()
        reached = (
            measured is not None
            and abs(float(measured) - opening) <= PIPER_GRIPPER_POSITION_TOLERANCE
        )
        if reached:
            self._home_deadline_s = None
            return True
        if self._home_deadline_s is not None and time.monotonic() >= self._home_deadline_s:
            self._home_deadline_s = None
            raise TimeoutError(f"{self.config.port}: Piper gripper did not reach {opening:.1f}")
        return False

    def move_to_initial_pose(self) -> None:
        if self._initial_pose is None:
            raise RuntimeError("Piper inference initial pose is not enabled")
        config = self.config.inference_start
        self.start_joint_move(
            self._initial_pose.joints[self.config.side],
            gripper_opening=None,
            max_joint_speed_deg_s=config.max_joint_speed_deg_s,
            timeout_s=config.timeout_s,
            label=f"dataset initial pose ({config.pose})",
        )
        try:
            while not self.poll_joint_move(config.tolerance_deg):
                time.sleep(0.05)
        finally:
            self.cancel_joint_move()

    def prepare_for_inference(self) -> None:
        config = self.config.inference_start
        if not config.enabled:
            return
        logger.info("Preparing Piper at dataset initial pose %s", config.pose)
        self.to_home()
        self.move_to_initial_pose()

    def to_inference_home(self) -> None:
        """Home the arm at its current aperture, then fully open and close it."""
        try:
            self.start_home_preserving_gripper()
            while not self.poll_home():
                time.sleep(0.05)
            for opening in (PIPER_RESET_GRIPPER_OPENING, PIPER_HOME_GRIPPER_OPENING):
                self.start_gripper_reset_stage(opening)
                while not self.poll_gripper_reset_stage(opening):
                    time.sleep(0.05)
        finally:
            self.cancel_home()
        if getattr(self, "_initial_pose", None) is not None:
            self.move_to_initial_pose()

    def to_zero(self) -> None:
        self.to_home()

    def _require_connected(self) -> tuple[PiperSdkArm, PiperJointStreamer]:
        if self._arm is None or self._streamer is None:
            raise RuntimeError(f"{self} is not connected")
        return self._arm, self._streamer


@RobotConfig.register_subclass("bi_piper")
@dataclass
class BiPiperConfig(RobotConfig):
    """Two native Piper arms plus the cameras used by a bimanual policy."""

    left_port: str = "can0"
    right_port: str = "can1"
    cameras: dict[str, CameraConfig] = field(default_factory=dict)
    command_rate_hz: float = 100.0
    max_joint_speed_deg_s: float = 180.0
    max_joint_acceleration_deg_s2: float = 720.0
    startup_speed_percent: int = 10
    speed_percent: int = 80
    enable_timeout_s: float = 10.0
    gripper_effort: int = 1000
    gripper_action_tolerance: float = 0.1
    gripper_calibration_path: Path | None = None
    inference_start: PiperInferenceStartConfig = field(default_factory=PiperInferenceStartConfig)
    config_path: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2] / "configs" / "bipiper.yaml")
    robot_type: str = "bi_piper"

    def load(self):
        """Load the repository hardware schema for validation and tooling."""
        from .active_config import PiperConfig as HardwareConfig

        config = HardwareConfig.from_file(self.config_path)
        if config.robot_id != self.robot_type:
            raise ValueError(f"expected robot id {self.robot_type!r}, got {config.robot_id!r}")
        return config

    def __post_init__(self) -> None:
        if isinstance(self.inference_start, dict):
            self.inference_start = PiperInferenceStartConfig(**self.inference_start)
        if self.left_port == self.right_port:
            raise ValueError("left_port and right_port must identify different CAN interfaces")
        if not np.isfinite(self.gripper_action_tolerance) or self.gripper_action_tolerance < 0.0:
            raise ValueError("gripper_action_tolerance must be finite and >= 0")
        for key, value in list(self.cameras.items()):
            if isinstance(value, dict):
                self.cameras[key] = camera_config_from_dict(value)
        super().__post_init__()


class BiPiper(Robot):
    """Bimanual robot preserving the dataset order: left 7, then right 7."""

    config_class = BiPiperConfig
    name = "bi_piper"

    def __init__(self, config: BiPiperConfig):
        super().__init__(config)
        self.config = config
        arm_kwargs = {
            "command_rate_hz": config.command_rate_hz,
            "max_joint_speed_deg_s": config.max_joint_speed_deg_s,
            "max_joint_acceleration_deg_s2": config.max_joint_acceleration_deg_s2,
            "startup_speed_percent": config.startup_speed_percent,
            "speed_percent": config.speed_percent,
            "enable_timeout_s": config.enable_timeout_s,
            "gripper_effort": config.gripper_effort,
            "gripper_action_tolerance": config.gripper_action_tolerance,
            "gripper_calibration_path": config.gripper_calibration_path,
        }
        self.left = Piper(PiperConfig(port=config.left_port, side="left", **arm_kwargs))
        self.right = Piper(PiperConfig(port=config.right_port, side="right", **arm_kwargs))
        self.cameras = make_mu_camera_from_configs(config.cameras)
        start_config = config.inference_start
        self._initial_pose = (
            load_piper_initial_joint_pose(start_config.pose_file, selection=start_config.pose)
            if start_config.enabled and start_config.pose_file is not None
            else None
        )

    @staticmethod
    def _arm_features(side: str) -> dict[str, type]:
        return {
            **{f"{side}_joint{index + 1}": float for index in range(ARM_JOINT_COUNT)},
            f"{side}_gripper": float,
        }

    @cached_property
    def action_features(self) -> dict[str, type]:
        return self._arm_features("left") | self._arm_features("right")

    @cached_property
    def observation_features(self) -> dict[str, type | tuple[int, int, int]]:
        images = {name: (camera.height, camera.width, 3) for name, camera in self.cameras.items()}
        return self.action_features | images

    @property
    def is_connected(self) -> bool:
        return (
            self.left.is_connected
            and self.right.is_connected
            and all(camera.is_connected for camera in self.cameras.values())
        )

    @property
    def is_calibrated(self) -> bool:
        return True

    def connect(self, calibrate: bool = True) -> None:
        del calibrate
        if self.is_connected:
            raise RuntimeError(f"{self} already connected")
        try:
            self.left.connect(calibrate=False)
            self.right.connect(calibrate=False)
            for camera in self.cameras.values():
                camera.connect()
        except BaseException:
            self.disconnect()
            raise

    def disconnect(self) -> None:
        for camera in self.cameras.values():
            with suppress(Exception):
                camera.disconnect()
        with suppress(Exception):
            self.right.disconnect()
        with suppress(Exception):
            self.left.disconnect()

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        pass

    @staticmethod
    def _prefix_observation(side: str, observation: dict[str, Any]) -> dict[str, Any]:
        return {
            **{
                f"{side}_joint{index + 1}": observation[f"joint_{index}.pos"]
                for index in range(ARM_JOINT_COUNT)
            },
            f"{side}_gripper": observation["joint_6.pos"],
        }

    @staticmethod
    def _arm_action(side: str, action: dict[str, Any]) -> dict[str, Any]:
        return {
            **{
                f"joint_{index}.pos": action[f"{side}_joint{index + 1}"]
                for index in range(ARM_JOINT_COUNT)
            },
            "joint_6.pos": action[f"{side}_gripper"],
        }

    def get_observation(self) -> dict[str, Any]:
        observation = self._prefix_observation("left", self.left.get_observation())
        observation.update(self._prefix_observation("right", self.right.get_observation()))
        for name, camera in self.cameras.items():
            observation[name] = camera.async_read()
        return observation

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        self.left.send_action(self._arm_action("left", action))
        self.right.send_action(self._arm_action("right", action))
        return {key: float(value) for key, value in action.items()}

    @staticmethod
    def _prefix_control(side: str, values: dict[str, float]) -> dict[str, float]:
        return {
            f"{side}_joint{index + 1}": values[f"joint_{index}.pos"]
            for index in range(ARM_JOINT_COUNT)
        }

    def control_snapshot(self) -> dict[str, dict[str, float | bool | int]]:
        left = self.left.control_snapshot()
        right = self.right.control_snapshot()
        joint_stages = (
            "stream_target",
            "stream_command",
            "stream_velocity",
            "measured",
            "motor_velocity",
            "motor_current_a",
            "motor_effort_nm",
            "motor_temperature_c",
            "driver_temperature_c",
            "collision",
            "stall",
            "motor_overtemperature",
            "driver_overtemperature",
            "driver_overcurrent",
            "driver_error",
        )
        result = {
            stage: self._prefix_control("left", left[stage])
            | self._prefix_control("right", right[stage])
            for stage in joint_stages
        }
        result["arm_status"] = {
            "left": int(left["arm_status"]["arm"]),
            "right": int(right["arm_status"]["arm"]),
        }
        return result

    def stop_motion(self) -> None:
        """Soft-stop both arms at their latest measured positions."""
        self.left.stop_motion()
        self.right.stop_motion()

    def to_home(self) -> None:
        try:
            self.left.start_home()
            self.right.start_home()
            left_done = right_done = False
            while not (left_done and right_done):
                if not left_done:
                    left_done = self.left.poll_home()
                if not right_done:
                    right_done = self.right.poll_home()
                time.sleep(0.05)
        except BaseException:
            with suppress(Exception):
                self.stop_motion()
            raise
        finally:
            self.left.cancel_home()
            self.right.cancel_home()

    def move_to_initial_pose(self) -> None:
        if self._initial_pose is None:
            raise RuntimeError("BiPiper inference initial pose is not enabled")
        config = self.config.inference_start
        label = f"dataset initial pose ({config.pose})"
        self.left.start_joint_move(
            self._initial_pose.joints["left"],
            gripper_opening=None,
            max_joint_speed_deg_s=config.max_joint_speed_deg_s,
            timeout_s=config.timeout_s,
            label=label,
        )
        try:
            self.right.start_joint_move(
                self._initial_pose.joints["right"],
                gripper_opening=None,
                max_joint_speed_deg_s=config.max_joint_speed_deg_s,
                timeout_s=config.timeout_s,
                label=label,
            )
            left_done = right_done = False
            while not (left_done and right_done):
                if not left_done:
                    left_done = self.left.poll_joint_move(config.tolerance_deg)
                if not right_done:
                    right_done = self.right.poll_joint_move(config.tolerance_deg)
                time.sleep(0.05)
        except BaseException:
            with suppress(Exception):
                self.stop_motion()
            raise
        finally:
            self.left.cancel_joint_move()
            self.right.cancel_joint_move()

    def prepare_for_inference(self) -> None:
        config = self.config.inference_start
        if not config.enabled:
            return
        logger.info("Preparing BiPiper at dataset initial pose %s", config.pose)
        self.to_home()
        self.move_to_initial_pose()

    def to_inference_home(self) -> None:
        """Reset both inference arms together, then open and close both grippers."""
        arms = (self.left, self.right)
        try:
            for arm in arms:
                arm.start_home_preserving_gripper()
            while not all(arm.poll_home() for arm in arms):
                time.sleep(0.05)
            for opening in (PIPER_RESET_GRIPPER_OPENING, PIPER_HOME_GRIPPER_OPENING):
                for arm in arms:
                    arm.start_gripper_reset_stage(opening)
                while not all(arm.poll_gripper_reset_stage(opening) for arm in arms):
                    time.sleep(0.05)
        finally:
            for arm in arms:
                arm.cancel_home()
        if getattr(self, "_initial_pose", None) is not None:
            self.move_to_initial_pose()

    def to_zero(self) -> None:
        self.to_home()


__all__ = [
    "PIPER_HOME_GRIPPER_OPENING",
    "PIPER_HOME_POSITION_RAD",
    "PIPER_RESET_GRIPPER_OPENING",
    "BiPiper",
    "BiPiperConfig",
    "Piper",
    "PiperConfig",
    "PiperInferenceStartConfig",
    "piper_home_position",
    "piper_inference_home_position",
]
