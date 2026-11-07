"""Dream custom driver for Piper feedback only; never enables or commands motors."""

from __future__ import annotations

import os
from pathlib import Path
import time

import numpy as np
import yaml

from robots import errors, followers


class ReadOnlyArm(followers.Driver):
    """Native J1..J6 radians, following XHUMAN's modern Piper driver.

    This class cannot operate a robot. Use only for feedback/contract checks.
    Gripper endpoints come from XHUMAN's measured calibration, never a guess.
    """

    def __init__(self, cfg, side: str) -> None:
        if side not in ("left", "right"):
            raise errors.ArmError("ReadOnlyArm requires a known side; use manual setup, not arm discovery")
        if len(cfg.home) != 6:
            raise errors.ArmError("Piper requires six joints per arm")
        source = os.environ.get("XHUMAN_PIPER_GRIPPER_CALIBRATION")
        calibration = Path(source).expanduser() if source else (
            Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
            / "xhuman/piper_grippers.yaml"
        )
        ranges = yaml.safe_load(calibration.read_text(encoding="utf-8"))
        self._closed = float(ranges[side]["closed_microm"])
        self._opened = float(ranges[side]["open_microm"])
        if not np.isfinite([self._closed, self._opened]).all() or self._opened <= self._closed:
            raise errors.ArmError("Invalid measured Piper gripper endpoints")

        # The normal XHUMAN constructors enable motors; open the SDK receive path directly.
        from piper_sdk import C_PiperInterface_V2

        self._sdk = C_PiperInterface_V2(cfg.can_channel)
        self._closed_device = False
        self._stamps = [None, None]
        self._received = [time.monotonic(), time.monotonic()]
        try:
            self._sdk.ConnectPort(piper_init=False)
            deadline = time.monotonic() + 1.5
            while True:
                try:
                    self.read()
                    break
                except errors.ArmError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
        except BaseException:
            self.close()
            raise

    def read(self) -> followers.Reading:
        if self._closed_device:
            raise errors.ArmError("Piper feedback connection is closed")
        joints = self._sdk.GetArmJointMsgs()
        grip = self._sdk.GetArmGripperMsgs()
        now = time.monotonic()
        for index, message in enumerate((joints, grip)):
            stamp = float(message.time_stamp)
            if not np.isfinite(stamp) or stamp <= 0:
                raise errors.ArmError("Piper feedback has not arrived")
            if stamp != self._stamps[index]:
                self._stamps[index], self._received[index] = stamp, now
            if now - self._received[index] > 0.2:
                raise errors.ArmError("Piper feedback is stale (>0.2 s)")
        raw = [getattr(joints.joint_state, f"joint_{index}") for index in range(1, 7)]
        positions = np.deg2rad(np.asarray(raw, dtype=np.float64) / 1000.0)
        opening = (float(grip.gripper_state.grippers_angle) - self._closed) / (self._opened - self._closed)
        if not np.isfinite(positions).all() or not np.isfinite(opening) or not -0.02 <= opening <= 1.02:
            raise errors.ArmError("Invalid Piper feedback or gripper outside measured travel")
        # shortcut: velocity is unavailable on this feedback-only path; do not use it for control.
        return followers.Reading(positions, np.zeros(6), float(np.clip(opening, 0, 1)))

    def write(self, positions_rad, gripper: float) -> None:
        raise errors.ArmError("ReadOnlyArm refuses every motor target; use --dry-run")

    def close(self) -> None:
        if not self._closed_device:
            self._sdk.DisconnectPort()
            self._closed_device = True

    def torque_off(self) -> None:
        # A read-only adapter must not change the motor power state on station exit.
        self.close()
