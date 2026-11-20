from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.piper_station_worker.config import EXPERIMENT_ROOT, load_dream, load_robot
from experiments.piper_station_worker.protocol import (
    Observation,
    action_message,
    observation_message,
    parse_action,
    parse_observation,
)
from experiments.piper_station_worker.worker import (
    DreamPiperPolicy,
    _fresh_chunk_rows,
    _observation_payload,
    _policy_config,
)


def test_source_profile_preserves_camera_and_can_mapping() -> None:
    robot = load_robot(EXPERIMENT_ROOT / "config/robot.yaml")
    assert robot.options["left_port"] == "can0"
    assert robot.options["right_port"] == "can1"
    assert [camera.name for camera in robot.cameras] == ["left", "top", "right"]
    assert robot.cameras[1].device.endswith("usb-0:3:1.0-video-index0")


def test_observation_wire_round_trip() -> None:
    message = observation_message(Observation(3, 4, tuple(float(index) for index in range(14)), {"left": b"image"}))
    assert parse_observation(json.loads(json.dumps(message))).images == {"left": b"image"}


def test_worker_uses_dream_137_compatible_embodiment_contract() -> None:
    config = load_dream(EXPERIMENT_ROOT / "config/dream.yaml")
    policy = _policy_config(config)
    assert policy["robot"] == "other_embodiment"
    assert policy["embodiment"]["video"] == {"wrist_l": "observation.images.left", "overhead": "observation.images.top", "wrist_r": "observation.images.right"}
    payload = _observation_payload(tuple(range(14)), "task")
    assert payload["state.right_arm"] == [7, 8, 9, 10, 11, 12]
    assert payload["state.left_gripper"] == [6]
    assert payload["state.right_gripper"] == [13]
    assert payload["state.left_grip"] == [6]
    assert payload["state.right_grip"] == [13]


def test_final_worker_observation_contains_every_declared_state_key() -> None:
    class Client:
        def set_observation(self, frames, payload, timestamp):
            self.frames, self.payload, self.timestamp = frames, payload, timestamp

    config = load_dream(EXPERIMENT_ROOT / "config/dream.yaml")
    robot = load_robot(EXPERIMENT_ROOT / "config/robot.yaml")
    policy = object.__new__(DreamPiperPolicy)
    policy.config = config
    policy.client = Client()
    from experiments.piper_station_worker.dream_policy import DreamDls

    # The source-compatible adapter adds EEF state locally from the copied,
    # confirmed URDF; it no longer calls the legacy global SciPy IK.
    policy._local_ik = DreamDls(config)
    state = tuple((limit.minimum + limit.maximum) / 2 for limit in robot.schema.joint_limits)
    policy.set_observation(Observation(1, 1, state, {name: b"image" for name in ("left", "top", "right")}))
    declared = {f"state.{name}" for name in _policy_config(config)["embodiment"]["state"]}
    assert declared <= set(policy.client.payload)


def test_worker_rejects_a_chunk_that_expired_during_inference() -> None:
    rows = [(0.0,) * 14] * 30
    with pytest.raises(TimeoutError, match="complete action horizon"):
        _fresh_chunk_rows(rows, elapsed_s=2.0, action_hz=20.0)
    assert len(_fresh_chunk_rows(rows, elapsed_s=1.0, action_hz=20.0)) == 10


def test_control_worker_configuration_is_available_for_an_explicitly_started_station() -> None:
    config = load_dream(EXPERIMENT_ROOT / "config/dream.yaml", dry_run=False)
    assert config.dry_run is False


def test_worker_defaults_to_action_mode_and_reads_env_overrides(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RSTACK_DREAM_MODE", raising=False)
    monkeypatch.delenv("RSTACK_DREAM_MODEL", raising=False)
    config_path = EXPERIMENT_ROOT / "config/dream.yaml"
    assert load_dream(config_path).dry_run is False
    (tmp_path / ".env").write_text("RSTACK_DREAM_MODE=observe\nRSTACK_DREAM_MODEL=local/model\n")
    config = load_dream(config_path)
    assert config.dry_run is True
    assert config.checkpoint == "local/model"
    monkeypatch.setenv("RSTACK_DREAM_MODE", "action")
    assert load_dream(config_path).dry_run is False


def test_runtime_metrics_expose_bounded_latency_distribution() -> None:
    from experiments.piper_station_worker.metrics import RuntimeMetrics

    metrics = RuntimeMetrics(window_size=10)
    for sample in range(1, 13):
        metrics.inference(sample / 1000, {"rtt_ms": sample * 2, "network_ms": 3})
    metrics.count("observations", 20)
    metrics.queue_depth(4)
    metrics.queue_depth(2)
    snapshot = metrics.snapshot()
    assert snapshot["samples"] == 10
    assert snapshot["inference_last_ms"] == 12
    assert snapshot["inference_mean_ms"] == pytest.approx(7.5)
    assert snapshot["inference_p95_ms"] > snapshot["inference_p50_ms"]
    assert snapshot["rtt_ms"] == 24
    assert snapshot["counts"]["observations"] == 20
    assert snapshot["queue_high_water"] == 4


def test_metrics_window_rejects_unusable_size() -> None:
    from experiments.piper_station_worker.metrics import RuntimeMetrics

    with pytest.raises(ValueError, match="at least 10"):
        RuntimeMetrics(window_size=9)


def test_streamer_failure_faults_station_and_requests_hold() -> None:
    import asyncio
    import time

    from experiments.piper_station_worker.control import PolicyAction, RunState
    from experiments.piper_station_worker.station import Station

    config = load_robot(EXPERIMENT_ROOT / "config/robot.yaml")
    station = Station(config)
    calls = {"hold": 0}

    class FailingRobot:
        def set_target(self, values):
            raise OSError("CAN write failed")

        def hold(self):
            calls["hold"] += 1

    station.robot = FailingRobot()
    station.supervisor.connected()
    session = station.supervisor.arm()
    station.supervisor.start()
    action = PolicyAction(
        session, 1, 1, time.monotonic_ns(), config.schema.version,
        tuple((limit.minimum + limit.maximum) / 2 for limit in config.schema.joint_limits),
        control_generation=station.supervisor.control_generation,
    )
    asyncio.run(station._handle_action_message(action_message(action), observe_only=False))
    assert station.supervisor.state == RunState.FAULT
    assert "CAN write failed" in station.supervisor.last_fault
    assert calls["hold"] == 1
    assert station.rejected_actions == 1


def test_station_requires_successful_hardware_validation_before_arming() -> None:
    from experiments.piper_station_worker.control import RunState
    from experiments.piper_station_worker.station import Station

    config = load_robot(EXPERIMENT_ROOT / "config/robot.yaml")
    station = Station(config)
    values = tuple((limit.minimum + limit.maximum) / 2 for limit in config.schema.joint_limits)

    class IdleRobot:
        def observation(self):
            return values

    station.robot = IdleRobot()
    station.supervisor.connected()
    try:
        with pytest.raises(RuntimeError, match="validate robot feedback"):
            station.arm()
        station.hardware_validated = True
        station.arm()
        assert station.supervisor.state == RunState.ARMED
    finally:
        station.cameras.disconnect()


def test_worker_clears_queued_actions_without_exiting_when_station_pauses() -> None:
    import asyncio

    from experiments.piper_station_worker.worker_runtime import WorkerRuntime

    class Socket:
        async def send(self, value):
            pass

    class Policy:
        config = type("Config", (), {"task": "test"})()

    schema = load_robot(EXPERIMENT_ROOT / "config/robot.yaml").schema
    runtime = WorkerRuntime(Socket(), Policy(), schema, observe=False)
    runtime.queue.extend([(0.0,) * 14, (0.1,) * 14])
    runtime.epoch = ("session", 1, "task")
    asyncio.run(runtime._handle_control_message({"type": "control_state", "state": "paused"}))
    assert not runtime.queue
    assert runtime.epoch is None
    assert runtime.fatal is None


def test_station_supervisor_accepts_only_current_session_actions() -> None:
    from experiments.piper_station_worker.control import MotionSupervisor, PolicyAction, RunState

    robot = load_robot(EXPERIMENT_ROOT / "config/robot.yaml")
    supervisor = MotionSupervisor(robot.schema, action_age_ms=500, scheduled_action_age_ms=6500)
    supervisor.connected()
    session = supervisor.arm()
    supervisor.start()
    action = PolicyAction(
        session, 1, 1, 1_000_000_000, robot.schema.version,
        tuple((limit.minimum + limit.maximum) / 2 for limit in robot.schema.joint_limits),
        scheduled=True, control_generation=supervisor.control_generation,
    )
    assert supervisor.validate(action, now_ns=1_001_000_000) is None
    assert supervisor.state == RunState.RUNNING
    assert parse_action(action_message(action)).values == action.values


def test_pause_does_not_clear_a_station_fault() -> None:
    from experiments.piper_station_worker.control import MotionSupervisor, RunState

    schema = load_robot(EXPERIMENT_ROOT / "config/robot.yaml").schema
    supervisor = MotionSupervisor(schema, action_age_ms=500, scheduled_action_age_ms=6500)
    supervisor.connected()
    supervisor.fault("streamer failed")
    supervisor.pause("operator requested hold")
    assert supervisor.state == RunState.FAULT
    assert "streamer failed" in supervisor.last_fault


def test_piper_connection_never_resets_a_faulted_controller(monkeypatch) -> None:
    import numpy as np
    import piper_sdk

    calls = {"reset": False, "disconnected": False}

    class FakeSdk:
        def __init__(self, port):
            self.port = port

        def ConnectPort(self):
            pass

        def GetArmJointMsgs(self):
            return type("Message", (), {"time_stamp": 1.0, "joint_state": type("Joints", (), {f"joint_{index}": 0 for index in range(1, 7)})()})()

        def GetArmStatus(self):
            return type("Status", (), {"arm_status": type("Arm", (), {"ctrl_mode": 2, "arm_status": 1})()})()

        def ResetPiper(self):
            calls["reset"] = True

        def DisconnectPort(self):
            calls["disconnected"] = True

    monkeypatch.setattr(piper_sdk, "C_PiperInterface_V2", FakeSdk)
    from scripts.driver import PiperSdkArm

    with pytest.raises(RuntimeError, match="automatic ResetPiper is disabled"):
        PiperSdkArm("can-test")
    assert calls == {"reset": False, "disconnected": True}


def test_piper_connection_blocks_before_enable_without_joint_calibration(monkeypatch) -> None:
    import piper_sdk

    calls = {"enabled": False, "disconnected": False}

    class FakeSdk:
        def __init__(self, port):
            self.port = port

        def ConnectPort(self):
            pass

        def GetArmJointMsgs(self):
            return type("Message", (), {"time_stamp": 1.0, "joint_state": type("Joints", (), {f"joint_{index}": 0 for index in range(1, 7)})()})()

        def GetArmStatus(self):
            return type("Status", (), {"arm_status": type("Arm", (), {"ctrl_mode": 0, "arm_status": 0})()})()

        def EnablePiper(self):
            calls["enabled"] = True
            return True

        def DisconnectPort(self):
            calls["disconnected"] = True

    monkeypatch.setattr(piper_sdk, "C_PiperInterface_V2", FakeSdk)
    from scripts.driver import PiperSdkArm

    with pytest.raises(RuntimeError, match="joint calibration is required"):
        PiperSdkArm("can-test")
    assert calls == {"enabled": False, "disconnected": True}
