"""Active Piper CAN driver extracted from the project's temasA integration.

This module owns only the project-specific hardware boundary. Dream policy,
observation contracts, pacing and inference remain in installed packages or in
the experiment adapters. Instantiating ``PiperSdkArm`` enables the arm and may
send CAN commands; use it only on the robot host.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import numpy as np

ARM_JOINT_COUNT = 6
RAD_TO_MDEG = 1000.0 * 180.0 / np.pi
MDEG_TO_RAD = 1.0 / RAD_TO_MDEG


@dataclass(frozen=True)
class PiperGripperRange:
    min_microm: int
    max_microm: int

    def __post_init__(self) -> None:
        if self.max_microm <= self.min_microm:
            raise ValueError("Piper gripper range must have positive travel")

    def command_for_opening(self, opening: float) -> int:
        if not np.isfinite(opening):
            raise ValueError("Piper gripper opening must be finite")
        return int(round(self.min_microm + np.clip(opening, 0.0, 1.0) * (self.max_microm - self.min_microm)))

    def normalize(self, position_microm: int) -> float:
        return float(np.clip((position_microm - self.min_microm) / (self.max_microm - self.min_microm), 0.0, 1.0))


class PiperSdkArm:
    """One actively controlled Piper arm using the public piper_sdk API."""

    def __init__(
        self,
        port: str,
        gripper_range: PiperGripperRange,
        *,
        speed_percent: int = 80,
        startup_speed_percent: int = 10,
        enable_timeout_s: float = 10.0,
        gripper_effort: int = 1000,
    ) -> None:
        if not 1 <= startup_speed_percent <= 100 or not 1 <= speed_percent <= 100:
            raise ValueError("Piper speed percentages must be in [1, 100]")
        from piper_sdk import C_PiperInterface_V2

        self.port = port
        self.gripper_range = gripper_range
        self.gripper_effort = int(gripper_effort)
        self._sdk = C_PiperInterface_V2(port)
        self._closed = False
        self._sdk.ConnectPort()
        try:
            initial = self._wait_for_feedback()
            self._send_joints(initial)
            self._sdk.MotionCtrl_2(0x01, 0x01, int(startup_speed_percent), 0x00)
            self._send_joints(initial)
            deadline = time.monotonic() + float(enable_timeout_s)
            while not self._sdk.EnablePiper():
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"{port}: Piper did not enable")
                time.sleep(0.02)
            self._send_joints(initial)
            self._sdk.MotionCtrl_2(0x01, 0x01, int(speed_percent), 0x00)
        except BaseException:
            self.close()
            raise

    def _wait_for_feedback(self, timeout_s: float = 1.5) -> np.ndarray:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            feedback = self._sdk.GetArmJointMsgs()
            if float(getattr(feedback, "time_stamp", 0.0)) > 0.0:
                return self._read_joints(feedback)
            time.sleep(0.02)
        raise TimeoutError(f"{self.port}: Piper feedback did not arrive")

    @staticmethod
    def _read_joints(feedback: Any) -> np.ndarray:
        state = feedback.joint_state
        values = np.asarray([getattr(state, f"joint_{i}") for i in range(1, 7)], dtype=np.float64) * MDEG_TO_RAD
        if not np.isfinite(values).all():
            raise ValueError("Piper feedback contains non-finite joints")
        return values

    def read(self) -> tuple[np.ndarray, float]:
        if self._closed:
            raise RuntimeError("Piper connection is closed")
        joints = self._sdk.GetArmJointMsgs()
        gripper = self._sdk.GetArmGripperMsgs()
        if float(joints.time_stamp) <= 0 or float(gripper.time_stamp) <= 0:
            raise RuntimeError("Piper feedback has not arrived")
        positions = self._read_joints(joints)
        opening = self.gripper_range.normalize(int(gripper.gripper_state.grippers_angle))
        return positions, opening

    def _send_joints(self, positions_rad: np.ndarray) -> None:
        values = np.asarray(positions_rad, dtype=np.float64).reshape(ARM_JOINT_COUNT)
        if not np.isfinite(values).all():
            raise ValueError("Piper joint command must be finite")
        command = np.rint(values * RAD_TO_MDEG).astype(np.int64)
        self._sdk.JointCtrl(*(int(value) for value in command))

    def send(self, positions_rad: np.ndarray, opening: float) -> None:
        self._send_joints(positions_rad)
        self._sdk.GripperCtrl(self.gripper_range.command_for_opening(opening), self.gripper_effort, 0x01, 0x00)

    def close(self) -> None:
        if not self._closed:
            disconnect = getattr(self._sdk, "DisconnectPort", None)
            if disconnect is not None:
                disconnect()
            self._closed = True


class BiPiperController:
    """Bimanual controller matching ``bi_piper`` configuration semantics."""

    def __init__(self, left: PiperSdkArm, right: PiperSdkArm) -> None:
        self.left = left
        self.right = right

    def read(self) -> dict[str, tuple[np.ndarray, float]]:
        return {"left": self.left.read(), "right": self.right.read()}

    def send(self, action: dict[str, Any]) -> None:
        for side, arm in (("left", self.left), ("right", self.right)):
            joints = np.asarray([action[f"{side}_joint{i}"] for i in range(1, 7)], dtype=np.float64)
            arm.send(joints, float(action[f"{side}_gripper"]))

    def close(self) -> None:
        self.right.close()
        self.left.close()


__all__ = ["BiPiperController", "PiperGripperRange", "PiperSdkArm"]
