"""Offline checks; fake CAN and camera sources only, no API calls."""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import numpy as np
import pytest
import yaml


HERE = Path(__file__).parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_zed_crops_exactly_one_eye_and_retains_bgr(monkeypatch):
    module = load("zed_left")
    camera = Mock()
    frame = np.zeros((376, 1344, 3), dtype=np.uint8)
    frame[:, :672, 0] = 17
    frame[:, 672:, 2] = 29
    camera.read.return_value = True, frame
    monkeypatch.setattr(module.cv2, "VideoCapture", lambda *args: camera)
    source = module.ZedLeft(SimpleNamespace(width=672, height=376, fps=30))
    ok, eye = source.read()
    assert ok and eye.shape == (376, 672, 3)
    assert np.all(eye[:, :, 0] == 17) and np.all(eye[:, :, 2] == 0)
    camera.read.return_value = True, eye
    with pytest.raises(RuntimeError, match="Expected stereo"):
        source.read()
    source.release()
    camera.release.assert_called_once()


def fake_arm(monkeypatch, tmp_path):
    module = load("piper_readonly")
    calibration = tmp_path / "grippers.yaml"
    calibration.write_text("left: {closed_microm: 1000, open_microm: 71000}\n")
    monkeypatch.setenv("XHUMAN_PIPER_GRIPPER_CALIBRATION", str(calibration))
    joint_state = SimpleNamespace(**{f"joint_{i}": 1000 * i for i in range(1, 7)})
    sdk = Mock()
    sdk.GetArmJointMsgs.return_value = SimpleNamespace(time_stamp=10.0, joint_state=joint_state)
    sdk.GetArmGripperMsgs.return_value = SimpleNamespace(
        time_stamp=10.0, gripper_state=SimpleNamespace(grippers_angle=36000)
    )
    monkeypatch.setitem(sys.modules, "piper_sdk", SimpleNamespace(C_PiperInterface_V2=lambda port: sdk))
    cfg = SimpleNamespace(can_channel="can0", home=[0] * 6)
    return module, module.ReadOnlyArm(cfg, "left"), sdk


def test_feedback_units_gripper_and_no_motor_commands(monkeypatch, tmp_path):
    module, arm, sdk = fake_arm(monkeypatch, tmp_path)
    reading = arm.read()
    np.testing.assert_allclose(reading.positions_rad, np.deg2rad([1, 2, 3, 4, 5, 6]))
    assert reading.gripper == 0.5
    with pytest.raises(module.errors.ArmError, match="refuses"):
        arm.write(np.zeros(6), 1.0)
    arm.torque_off()
    arm.close()
    assert sdk.method_calls[0][0] == "ConnectPort"
    sdk.ConnectPort.assert_called_once_with(piper_init=False)
    sdk.DisconnectPort.assert_called_once()
    allowed = {"ConnectPort", "GetArmJointMsgs", "GetArmGripperMsgs", "DisconnectPort"}
    assert all(call[0] in allowed for call in sdk.method_calls)


def test_stale_feedback_and_nonfinite_values_are_refused(monkeypatch, tmp_path):
    module, arm, sdk = fake_arm(monkeypatch, tmp_path)
    monkeypatch.setattr(module.time, "monotonic", lambda: max(arm._received) + 0.3)
    with pytest.raises(module.errors.ArmError, match="stale"):
        arm.read()
    sdk.GetArmJointMsgs.return_value.time_stamp = 11.0
    sdk.GetArmGripperMsgs.return_value.time_stamp = 11.0
    sdk.GetArmJointMsgs.return_value.joint_state.joint_1 = float("nan")
    with pytest.raises(module.errors.ArmError, match="Invalid"):
        arm.read()
    arm.close()


def test_template_uses_custom_roles_and_refuses_unmeasured_home(tmp_path):
    from robots import config, errors

    template = yaml.safe_load((HERE / "station.readonly.yaml").read_text())
    assert template["body"] == "custom"
    assert {camera["name"] for camera in template["cameras"]} == {"overhead", "wrist_l", "wrist_r"}
    assert template["follower_l"]["home"] is None
    with pytest.raises(errors.ConfigError, match="home"):
        config.load(HERE / "station.readonly.yaml")
    # Synthetic poses check the rest of the upstream schema; they are never saved as station calibration.
    for side in ("l", "r"):
        template[f"follower_{side}"]["home"] = [0.0] * 6
    completed = tmp_path / "schema-only.yaml"
    completed.write_text(yaml.safe_dump(template))
    loaded = config.load(completed)
    assert loaded.body == "custom" and loaded.control_hz == 20


def test_local_urdf_chain_has_six_arm_joints():
    import json

    arm = json.loads((HERE / "arm.pending.json").read_text())
    assert all(arm[key] is None for key in ("tcp", "approach", "jaw", "rest"))
    source = Path(arm["urdf"])
    if not source.exists():
        pytest.skip("XHUMAN workspace is not present on this machine")
    root = ET.parse(source).getroot()
    parents = {joint.find("child").get("link"): joint for joint in root.findall("joint")}
    moving = []
    link = arm["flange"]
    while link != arm["base"]:
        joint = parents[link]
        if joint.get("type") != "fixed":
            moving.append(joint.get("name"))
        link = joint.find("parent").get("link")
    assert moving[::-1] == [f"left_joint{i}" for i in range(1, 7)]
