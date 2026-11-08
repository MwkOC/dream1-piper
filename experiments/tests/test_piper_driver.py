from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import numpy as np
import pytest


def test_read_only_driver_does_not_send_targets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calibration = tmp_path / "grippers.yaml"
    calibration.write_text("left: {closed_microm: 1000, open_microm: 71000}\n", encoding="utf-8")
    monkeypatch.setenv("XHUMAN_PIPER_GRIPPER_CALIBRATION", str(calibration))

    joints = SimpleNamespace(**{f"joint_{i}": 1000 * i for i in range(1, 7)})
    sdk = Mock()
    sdk.GetArmJointMsgs.return_value = SimpleNamespace(time_stamp=10.0, joint_state=joints)
    sdk.GetArmGripperMsgs.return_value = SimpleNamespace(
        time_stamp=10.0,
        gripper_state=SimpleNamespace(grippers_angle=36000),
    )
    monkeypatch.setitem(sys.modules, "piper_sdk", SimpleNamespace(C_PiperInterface_V2=lambda _: sdk))

    pytest.importorskip("robots")
    from piper.piper_driver import PiperArm

    arm = PiperArm(SimpleNamespace(can_channel="can0", home=[0.0] * 6), "left")
    reading = arm.read()
    np.testing.assert_allclose(reading.positions_rad, np.deg2rad([1, 2, 3, 4, 5, 6]))
    assert reading.gripper == 0.5
    with pytest.raises(Exception, match="read-only"):
        arm.write(np.zeros(6), 1.0)
    arm.close()
    assert all(call[0] in {"ConnectPort", "GetArmJointMsgs", "GetArmGripperMsgs", "DisconnectPort"}
               for call in sdk.method_calls)

