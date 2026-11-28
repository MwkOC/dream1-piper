import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ros2_ws/src/dream1_piper_ros"))

from dream1_piper_ros.tracking_metrics import (  # noqa: E402
    match_feedback_target,
    orientation_error_deg,
    position_error_mm,
)


def test_feedback_matches_latest_command_not_newer_command():
    history = [
        {"issued_stamp_sec": 10.0, "issued_at": 100.0, "sequence": 7},
        {"issued_stamp_sec": 10.2, "issued_at": 100.2, "sequence": 8},
    ]
    matched = match_feedback_target(history, 10.1, 100.25, 0.25)
    assert matched["sequence"] == 7


@pytest.mark.parametrize(
    ("feedback_stamp", "received_at"),
    [(9.9, 100.1), (10.1, 99.9), (10.3, 100.1), (10.1, 100.3)],
)
def test_feedback_rejects_future_or_stale_timestamp_pairs(feedback_stamp, received_at):
    history = [{"issued_stamp_sec": 10.0, "issued_at": 100.0}]
    assert match_feedback_target(history, feedback_stamp, received_at, 0.25) is None


def test_tcp_pose_error_units_and_quaternion_angle():
    assert position_error_mm([0.0, 0.0, 0.0], [0.003, 0.004, 0.0]) == pytest.approx(5.0)
    rotated = [0.0, 0.0, 2**-0.5, 2**-0.5]
    assert orientation_error_deg([0.0, 0.0, 0.0, 1.0], rotated) == pytest.approx(90.0)
