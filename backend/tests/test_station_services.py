from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from dream1_piper.domain.contracts import ControlSource, RunState
from dream1_piper.services.auth import SessionAuth
from dream1_piper.services.events import MetricsService
from dream1_piper.services.station import StationService
from dream1_piper.services.teleop import TeleopService, TwistInput
from dream1_piper.services.worker_bridge import WorkerBridge
from dream1_piper.worker.config import load_robot
from dream1_piper.worker.control import PolicyAction
from dream1_piper.worker.dream_policy import DreamDls
from dream1_piper.worker.kinematics import UrdfArm
from dream1_piper.worker.protocol import action_message, parse_action

ROOT = Path(__file__).resolve().parents[2]


class Gateway:
    def __init__(self):
        self.commands = []

    async def command(self, name, payload):
        self.commands.append((name, payload))
        return {"accepted": True}


def ready_station():
    station = StationService()
    station.state = RunState.READY
    station.arms = {"left": {"connected": True}, "right": {"connected": True}}
    station.cameras = {name: {"connected": True} for name in ("left", "top", "right")}
    return station


def test_app_robot_yaml_is_accepted_by_worker_protocol():
    robot = load_robot(ROOT / "configs/app_robot.yaml")
    assert robot.name == "bipiper-dream1-v1"
    assert len(robot.cameras) == 3
    assert len(robot.schema.joint_limits) == 14


def test_station_lifecycle_is_idempotent_and_generates_new_control_epoch():
    station = ready_station()
    request_id = uuid4()
    validated = station.validate(request_id)
    assert station.validate(request_id) == validated
    station.worker_connected = True
    station.arm(uuid4(), ControlSource.DREAM)
    generation = station.control_generation
    station.start(uuid4())
    assert station.state == RunState.RUNNING
    station.pause(uuid4())
    assert station.state == RunState.PAUSED
    assert station.control_generation == generation + 1


@pytest.mark.asyncio
async def test_worker_bridge_rejects_unsafe_actions_and_publishes_valid_action():
    station = ready_station()
    station.hardware_validated = True
    station.worker_connected = True
    station.arm(uuid4(), ControlSource.DREAM)
    station.start(uuid4())
    gateway = Gateway()
    limits = [{"minimum": -1.0, "maximum": 1.0, "max_speed": 1.0}] * 14
    bridge = WorkerBridge(
        station,
        gateway,
        MetricsService(),
        SimpleNamespace(publish=lambda *_: None),
        "action",
        limits,
        [f"joint_{index}" for index in range(14)],
    )

    invalid = await bridge.handle({"type": "action", "values": [0.0] * 13})
    assert invalid["accepted"] is False
    assert not gateway.commands

    action = {
        "type": "action",
        "values": [0.0] * 14,
        "control_generation": station.control_generation,
        "sequence_id": 1,
    }
    accepted = await bridge.handle(action)
    assert accepted["accepted"] is True
    assert gateway.commands[-1][0] == "dream_action"


def test_teleop_requires_selected_arm_fresh_sequence_and_vector_limits():
    station = ready_station()
    station.control_source = ControlSource.TELEOP
    station.selected_arm = "left"
    station.state = RunState.ARMED
    settings = SimpleNamespace(teleop_max_hz=30)
    service = TeleopService(
        station, Gateway(), settings, MetricsService(), SimpleNamespace(publish=lambda *_: None)
    )
    message = TwistInput(
        type="heartbeat",
        sequence=1,
        control_generation=station.control_generation,
        arm="left",
        deadman=True,
        linear=[0.0, 0.0, 0.0],
        angular=[0.0, 0.0, 0.0],
    )
    service._validate_state(message)
    assert service.deadman_active is True
    with pytest.raises(ValueError, match="stale"):
        service._validate_state(message)


def test_auth_session_can_be_revoked_and_metrics_separate_control_sources():
    auth = SessionAuth("operator-secret", "a-secure-test-secret-with-at-least-32-chars", 60)
    cookie = auth.login("operator-secret")
    assert auth.validate(cookie)
    auth.revoke(cookie)
    assert not auth.validate(cookie)

    metrics = MetricsService()
    metrics.record({"control_source": "dream", "stage": "dream_inference", "duration_ms": 20.0})
    metrics.record({"control_source": "teleop", "stage": "input_to_ros", "duration_ms": 5.0})
    snapshot = metrics.snapshot()
    assert snapshot["by_source"] == {"dream": 1, "teleop": 1, "home": 0}
    assert "dream.dream_inference" in snapshot["stages"]
    assert "teleop.input_to_ros" in snapshot["stages"]


def test_urdf_arm_exposes_forward_pose_and_jacobian():
    arm_file = (
        Path(__file__).resolve().parents[2]
        / "experiments/piper_station_worker/assets/piper/piper_arm.json"
    )
    arm = UrdfArm(arm_file)
    pose = arm.forward(arm.rest)
    jacobian = arm.jacobian(arm.rest)
    assert pose.shape == (4, 4)
    assert jacobian.shape == (6, 6)
    assert np.isfinite(pose).all()


def test_tcp_targets_are_forward_kinematics_for_both_arm_frames():
    arm = UrdfArm(
        ROOT / "experiments/piper_station_worker/assets/piper/piper_arm.json"
    )
    target = DreamDls.tcp_targets(SimpleNamespace(arm=arm), tuple([*arm.rest, 0, *arm.rest, 0]))
    assert target["left"]["frame_id"] == "left_base_link"
    assert target["right"]["frame_id"] == "right_base_link"
    np.testing.assert_allclose(target["left"]["position"], arm.forward(arm.rest)[:3, 3])
    assert np.isclose(np.linalg.norm(target["right"]["orientation"]), 1.0)


def test_action_protocol_carries_optional_tcp_targets():
    targets = {"left": {"frame_id": "left_base_link", "position": [0.1, 0.2, 0.3]}}
    action = PolicyAction("session", 3, 2, 10, 1, tuple([0.0] * 14), tcp_targets=targets)
    assert parse_action(action_message(action)).tcp_targets == targets


def test_tcp_tracking_summary_uses_millimeter_units():
    metrics = MetricsService()
    for error in (5.0, 10.0):
        metrics.record({
            "control_source": "dream",
            "stage": "tcp_tracking_error",
            "result": "measured",
            "arm": "left",
            "position_error_mm": error,
            "orientation_error_deg": 2.0,
            "target_age_ms": 15.0,
        })
    left = metrics.snapshot()["tcp_tracking"]["left"]
    assert left["sample_count"] == 2
    assert left["mean_mm"] == 7.5
    assert left["p95_mm"] == 10.0
    assert left["last_mm"] == 10.0
    assert metrics.snapshot()["tcp_tracking"]["right"]["sample_count"] == 0
