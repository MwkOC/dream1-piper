"""Native Piper CAN primitives used by MU.

All public joint values are radians. The conversion to the Piper SDK's
milli-degree and micrometre units happens only at this hardware boundary.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np

ARM_JOINT_COUNT = 6
RAD_TO_MDEG = 1000.0 * 180.0 / np.pi
MDEG_TO_RAD = 1.0 / RAD_TO_MDEG


@dataclass(frozen=True)
class PiperGripperRange:
    min_microm: int
    max_microm: int
    source: str = "sdk"

    def __post_init__(self) -> None:
        if self.max_microm <= self.min_microm:
            raise ValueError("Piper gripper range must have positive travel")

    def command_for_opening(self, opening: float) -> int:
        fraction = float(np.clip(opening, 0.0, 1.0))
        return int(round(self.min_microm + fraction * (self.max_microm - self.min_microm)))

    def normalize(self, position_microm: int) -> float:
        span = self.max_microm - self.min_microm
        return float(np.clip((position_microm - self.min_microm) / span, 0.0, 1.0))


class PiperFeedbackArm:
    """Read Piper feedback without enabling motors or sending targets."""

    def __init__(self, port: str, gripper_range: PiperGripperRange) -> None:
        from piper_sdk import C_PiperInterface_V2

        self.port = port
        self.gripper_range = gripper_range
        self.arm = C_PiperInterface_V2(port)
        self.arm.ConnectPort(piper_init=False)

    def read(self) -> tuple[np.ndarray, float]:
        joints = self.arm.GetArmJointMsgs()
        gripper = self.arm.GetArmGripperMsgs()
        if float(joints.time_stamp) <= 0 or float(gripper.time_stamp) <= 0:
            raise RuntimeError(f"{self.port}: Piper feedback has not arrived")
        values = np.asarray(
            [getattr(joints.joint_state, f"joint_{index}") for index in range(1, 7)],
            dtype=np.float64,
        ) * MDEG_TO_RAD
        raw_opening = float(gripper.gripper_state.grippers_angle)
        opening = (
            raw_opening - self.gripper_range.min_microm
        ) / (self.gripper_range.max_microm - self.gripper_range.min_microm)
        if not np.isfinite(values).all() or not np.isfinite(opening) or not -0.02 <= opening <= 1.02:
            raise RuntimeError(f"{self.port}: invalid Piper feedback")
        return values, float(np.clip(opening, 0.0, 1.0))

    def disconnect(self) -> None:
        self.arm.DisconnectPort()


class PiperSdkArm:
    """A feedback-seeded connection to one Piper arm."""

    def __init__(
        self,
        port: str,
        *,
        startup_speed_percent: int = 10,
        speed_percent: int = 80,
        enable_timeout_s: float = 10.0,
        gripper_effort: int = 1000,
        gripper_range: PiperGripperRange | None = None,
    ) -> None:
        try:
            from piper_sdk import C_PiperInterface_V2
        except ImportError as exc:
            raise RuntimeError("piper_sdk is required for Piper teleoperation") from exc

        self.port = port
        self.startup_speed_percent = int(startup_speed_percent)
        if not 1 <= self.startup_speed_percent <= 100:
            raise ValueError("startup_speed_percent must be in [1, 100]")
        self.speed_percent = int(speed_percent)
        self.gripper_effort = int(gripper_effort)
        self.arm = C_PiperInterface_V2(port)
        self.arm.ConnectPort()
        try:
            self._wait_for_feedback()
            initial = self.read_joints_rad()
            status = self.arm.GetArmStatus().arm_status
            if self._requires_reset(status):
                self.arm.ResetPiper()
                time.sleep(0.1)

            # Piper retains its last native joint target across process
            # restarts. Preload measured feedback before selecting MOVE_J and
            # once more before enabling, so neither transition can execute a
            # stale go-zero target. JointCtrl frames are safe while disabled:
            # they only replace the controller's pending position target.
            self.send_joints_rad(initial)
            self._set_joint_mode(self.startup_speed_percent)
            self.send_joints_rad(initial)
            deadline = time.monotonic() + float(enable_timeout_s)
            while not self.arm.EnablePiper():
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"{port}: Piper did not enable")
                time.sleep(0.02)
            # Reassert the hold after enable in case the controller ignored
            # position frames while its motors were disabled.
            self.send_joints_rad(initial)
            time.sleep(0.05)
            self._set_joint_mode(self.speed_percent)
            self.send_joints_rad(initial)
            self.gripper_range = gripper_range or self._read_gripper_range()
        except BaseException:
            self.disconnect()
            raise

    def _wait_for_feedback(self, timeout_s: float = 1.5) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if float(self.arm.GetArmJointMsgs().time_stamp) > 0.0:
                return
            time.sleep(0.02)
        raise TimeoutError(
            f"{self.port}: no Piper feedback; check power, CAN mapping, and 1 Mbps bitrate"
        )

    def _requires_reset(self, status: object) -> bool:
        if int(getattr(status, "ctrl_mode", 0)) == 0x02:
            return True
        if int(getattr(status, "arm_status", 0)) != 0:
            return True
        get_mode = getattr(self.arm, "GetArmModeCtrl", None)
        if get_mode is None:
            return False
        feedback = get_mode()
        mode = getattr(feedback, "ctrl_151", None)
        return (
            float(getattr(feedback, "time_stamp", 0.0)) > 0.0
            and int(getattr(mode, "mit_mode", 0)) == 0xAD
        )

    def _set_joint_mode(self, speed_percent: int | None = None) -> None:
        self.arm.MotionCtrl_2(0x01, 0x01, int(speed_percent or self.speed_percent), 0x00)

    def _read_gripper_range(self) -> PiperGripperRange:
        minimum_m, maximum_m = self.arm.GetSDKGripperRangeParam()
        return PiperGripperRange(
            int(round(float(minimum_m) * 1_000_000.0)),
            int(round(float(maximum_m) * 1_000_000.0)),
        )

    def read_joints_rad(self) -> np.ndarray:
        state = self.arm.GetArmJointMsgs().joint_state
        return (
            np.asarray(
                [
                    state.joint_1,
                    state.joint_2,
                    state.joint_3,
                    state.joint_4,
                    state.joint_5,
                    state.joint_6,
                ],
                dtype=np.float64,
            )
            * MDEG_TO_RAD
        )

    def read_gripper_opening(self) -> float | None:
        feedback = self.arm.GetArmGripperMsgs()
        if float(getattr(feedback, "time_stamp", 0.0)) <= 0.0:
            return None
        return self.gripper_range.normalize(int(feedback.gripper_state.grippers_angle))

    def read_motor_diagnostics(self) -> dict[str, np.ndarray | int]:
        """Expose the Piper telemetry needed by the deterministic safety layer."""
        high_speed = self.arm.GetArmHighSpdInfoMsgs()
        motors = [getattr(high_speed, f"motor_{index}") for index in range(1, 7)]
        low_speed = self.arm.GetArmLowSpdInfoMsgs()
        drivers = [getattr(low_speed, f"motor_{index}") for index in range(1, 7)]
        status = self.arm.GetArmStatus().arm_status
        result: dict[str, np.ndarray | int] = {
            "motor_velocity": np.asarray(
                [motor.motor_speed * 0.001 for motor in motors], dtype=np.float64
            ),
            "motor_current_a": np.asarray(
                [motor.current * 0.001 for motor in motors], dtype=np.float64
            ),
            "motor_effort_nm": np.asarray(
                [motor.effort * 0.001 for motor in motors], dtype=np.float64
            ),
            "motor_temperature_c": np.asarray(
                [motor.motor_temp for motor in drivers], dtype=np.float64
            ),
            "driver_temperature_c": np.asarray(
                [motor.foc_temp for motor in drivers], dtype=np.float64
            ),
            "collision": np.asarray(
                [motor.foc_status.collision_status for motor in drivers], dtype=np.bool_
            ),
            "stall": np.asarray(
                [motor.foc_status.stall_status for motor in drivers], dtype=np.bool_
            ),
            "motor_overtemperature": np.asarray(
                [motor.foc_status.motor_overheating for motor in drivers], dtype=np.bool_
            ),
            "driver_overtemperature": np.asarray(
                [motor.foc_status.driver_overheating for motor in drivers], dtype=np.bool_
            ),
            "driver_overcurrent": np.asarray(
                [motor.foc_status.driver_overcurrent for motor in drivers], dtype=np.bool_
            ),
            "driver_error": np.asarray(
                [motor.foc_status.driver_error_status for motor in drivers], dtype=np.bool_
            ),
            "arm_status": int(status.arm_status),
        }
        return result

    def send_joints_rad(self, joints: np.ndarray) -> None:
        values = np.asarray(joints, dtype=np.float64).reshape(ARM_JOINT_COUNT)
        if not np.isfinite(values).all():
            raise ValueError("Piper joint command must be finite")
        command = np.rint(values * RAD_TO_MDEG).astype(np.int64)
        self.arm.JointCtrl(*(int(value) for value in command))

    def send_gripper_opening(self, opening: float) -> None:
        self.arm.GripperCtrl(
            self.gripper_range.command_for_opening(opening),
            self.gripper_effort,
            0x01,
            0x00,
        )

    def disconnect(self) -> None:
        disconnect = getattr(self.arm, "DisconnectPort", None)
        if disconnect is not None:
            disconnect()


class PiperJointStreamer:
    """Stream the latest target at 100 Hz with velocity/acceleration bounds."""

    def __init__(
        self,
        arm: PiperSdkArm,
        *,
        command_rate_hz: float = 100.0,
        max_joint_speed_deg_s: float = 180.0,
        max_joint_acceleration_deg_s2: float = 720.0,
    ) -> None:
        if min(command_rate_hz, max_joint_speed_deg_s, max_joint_acceleration_deg_s2) <= 0.0:
            raise ValueError("Piper streamer rates and limits must be positive")
        self.arm = arm
        self.command_rate_hz = float(command_rate_hz)
        self.max_velocity = np.deg2rad(float(max_joint_speed_deg_s))
        self.max_acceleration = np.deg2rad(float(max_joint_acceleration_deg_s2))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._error: BaseException | None = None
        measured = arm.read_joints_rad()
        self._command = measured.copy()
        self._target = measured.copy()
        self._velocity = np.zeros(ARM_JOINT_COUNT, dtype=np.float64)
        self._gripper_target: float | None = None
        self._thread = threading.Thread(
            target=self._run, name=f"piper-{arm.port}-stream", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.raise_if_failed()

    def set_target(self, joints: np.ndarray, gripper_opening: float | None = None) -> None:
        values = np.asarray(joints, dtype=np.float64).reshape(ARM_JOINT_COUNT)
        if not np.isfinite(values).all():
            raise ValueError("Piper target must be finite")
        with self._lock:
            self._target = values.copy()
            if gripper_opening is not None:
                self._gripper_target = float(np.clip(gripper_opening, 0.0, 1.0))
        self.raise_if_failed()

    def set_max_joint_speed_deg_s(self, value: float) -> None:
        if value <= 0.0:
            raise ValueError("joint speed must be positive")
        with self._lock:
            self.max_velocity = float(np.deg2rad(value))

    def raise_if_failed(self) -> None:
        if self._error is not None:
            raise RuntimeError(f"Piper streaming failed: {self._error}") from self._error

    def snapshot(self) -> dict[str, np.ndarray]:
        """Return a coherent copy of the current trajectory-generator state."""
        with self._lock:
            return {
                "target": self._target.copy(),
                "command": self._command.copy(),
                "velocity": self._velocity.copy(),
            }

    def _run(self) -> None:
        dt = 1.0 / self.command_rate_hz
        deadline = time.perf_counter()
        try:
            while not self._stop.is_set():
                with self._lock:
                    target = self._target.copy()
                    max_velocity = self.max_velocity
                    gripper = self._gripper_target
                desired_velocity = np.clip(
                    (target - self._command) / dt, -max_velocity, max_velocity
                )
                velocity_delta = np.clip(
                    desired_velocity - self._velocity,
                    -self.max_acceleration * dt,
                    self.max_acceleration * dt,
                )
                with self._lock:
                    self._velocity += velocity_delta
                    step = self._velocity * dt
                    error = target - self._command
                    reached = np.abs(step) >= np.abs(error)
                    self._command += np.where(reached, error, step)
                    self._velocity[reached] = 0.0
                    command = self._command.copy()
                self.arm.send_joints_rad(command)
                if gripper is not None:
                    self.arm.send_gripper_opening(gripper)
                deadline += dt
                wait = deadline - time.perf_counter()
                if wait > 0.0:
                    self._stop.wait(wait)
                else:
                    deadline = time.perf_counter()
        except BaseException as exc:
            self._error = exc
            self._stop.set()


__all__ = [
    "ARM_JOINT_COUNT",
    "MDEG_TO_RAD",
    "RAD_TO_MDEG",
    "PiperFeedbackArm",
    "PiperGripperRange",
    "PiperJointStreamer",
    "PiperSdkArm",
]
