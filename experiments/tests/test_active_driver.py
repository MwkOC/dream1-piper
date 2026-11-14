import sys
from types import SimpleNamespace

import numpy as np
import pytest


def test_active_driver_seeds_feedback_before_enabling(monkeypatch):
    calls = []
    joints = SimpleNamespace(**{f"joint_{i}": 1000 * i for i in range(1, 7)})
    sdk = SimpleNamespace(
        ConnectPort=lambda: calls.append("connect"),
        DisconnectPort=lambda: calls.append("disconnect"),
        GetArmJointMsgs=lambda: SimpleNamespace(time_stamp=1.0, joint_state=joints),
        EnablePiper=lambda: calls.append("enable") or True,
        MotionCtrl_2=lambda *args: calls.append(("mode", args)),
        JointCtrl=lambda *args: calls.append(("joints", args)),
        GripperCtrl=lambda *args: calls.append(("gripper", args)),
    )
    monkeypatch.setitem(sys.modules, "piper_sdk", SimpleNamespace(C_PiperInterface_V2=lambda _: sdk))

    from piper.active_driver import PiperGripperRange, PiperSdkArm

    arm = PiperSdkArm("can0", PiperGripperRange(1000, 71000), enable_timeout_s=0.1)
    arm.send(np.zeros(6), 0.5)
    arm.close()

    assert calls[0] == "connect"
    assert calls.index("enable") > 0
    assert any(call[0] == "joints" for call in calls if isinstance(call, tuple))
    assert any(call[0] == "gripper" for call in calls if isinstance(call, tuple))
    assert calls[-1] == "disconnect"


def test_transmission_failure_is_raised():
    from piper.active_driver import PiperSdkArm

    transport = SimpleNamespace(
        CAN_STATUS=SimpleNamespace(SEND_MESSAGE_SUCCESS=0),
        SendCanMessage=lambda *args, **kwargs: 100017,
    )
    arm = PiperSdkArm.__new__(PiperSdkArm)
    arm.port = "can0"
    arm.arm = SimpleNamespace(_C_PiperInterface_V2__arm_can=transport)
    arm._check_transmissions()
    with pytest.raises(RuntimeError, match="100017"):
        transport.SendCanMessage(1, b"")


def test_feedback_connection_transfers_without_reconnect(monkeypatch):
    from piper.active_driver import PiperFeedbackArm, PiperGripperRange, PiperSdkArm

    calls = []
    joints = SimpleNamespace(**{f"joint_{i}": 0 for i in range(1, 7)})
    sdk = SimpleNamespace(
        ConnectPort=lambda **kw: calls.append("connect"),
        DisconnectPort=lambda: calls.append("disconnect"),
        GetArmJointMsgs=lambda: SimpleNamespace(time_stamp=1.0, joint_state=joints),
        EnablePiper=lambda: True,
        MotionCtrl_2=lambda *args: None,
        JointCtrl=lambda *args: None,
    )
    monkeypatch.setitem(sys.modules, "piper_sdk", SimpleNamespace(C_PiperInterface_V2=lambda _: sdk))
    calibration = PiperGripperRange(0, 1000)
    feedback = PiperFeedbackArm("can0", calibration)
    arm = PiperSdkArm("can0", calibration, feedback=feedback)
    feedback.disconnect()
    assert calls == ["connect"]
    arm.disconnect()
    assert calls == ["connect", "disconnect"]
