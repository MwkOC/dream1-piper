import time
from pathlib import Path

import numpy as np
from piper.active_driver import PiperJointStreamer
from piper.gripper_calibration import load_piper_gripper_calibrations


class FakeArm:
    port = "fake"

    def __init__(self) -> None:
        self.joints = np.zeros(6)
        self.commands: list[np.ndarray] = []
        self.grippers: list[float] = []

    def read_joints_rad(self) -> np.ndarray:
        return self.joints.copy()

    def send_joints_rad(self, joints: np.ndarray) -> None:
        self.commands.append(np.asarray(joints).copy())

    def send_gripper_opening(self, opening: float) -> None:
        self.grippers.append(opening)


def test_streamer_applies_velocity_and_acceleration_limits() -> None:
    arm = FakeArm()
    streamer = PiperJointStreamer(
        arm,
        command_rate_hz=100.0,
        max_joint_speed_deg_s=10.0,
        max_joint_acceleration_deg_s2=100.0,
    )
    streamer.start()
    try:
        streamer.set_target(np.ones(6), 0.5)
        time.sleep(0.06)
        state = streamer.snapshot()
    finally:
        streamer.stop()
    assert np.all(np.abs(state["velocity"]) <= np.deg2rad(10.0) + 1e-6)
    assert arm.commands
    assert arm.grippers


def test_gripper_calibration_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "bipiper.yaml"
    path.write_text(
        "left: {closed_microm: 1000, open_microm: 71000}\n"
        "right: {closed_microm: 1200, open_microm: 72000}\n",
        encoding="utf-8",
    )
    ranges = load_piper_gripper_calibrations(path)
    assert set(ranges) == {"left", "right"}
    assert ranges["left"].command_for_opening(0.5) == 36000
