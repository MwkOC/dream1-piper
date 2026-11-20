import numpy as np
import pytest

from scripts.constants import (
    PIPER_JOINT_LOWER_RAD,
    PIPER_JOINT_UPPER_RAD,
    validate_joint_feedback,
    validate_joint_target,
)
from scripts.joint_calibration import PiperJointCalibration


def test_raw_startup_feedback_is_diagnostic_not_a_command_target():
    raw = np.array([0.0, -2.169, 4.048, 0.0, 0.0, 0.0])
    np.testing.assert_array_equal(validate_joint_feedback(raw), raw)
    with pytest.raises(ValueError, match="exceeds configured limits"):
        validate_joint_target(raw)


@pytest.mark.parametrize('index', range(6))
@pytest.mark.parametrize('upper', [False, True])
def test_rejects_targets_outside_configured_range(index, upper):
    target = (PIPER_JOINT_LOWER_RAD + PIPER_JOINT_UPPER_RAD) / 2
    target[index] = (PIPER_JOINT_UPPER_RAD[index] + 1e-6 if upper
                     else PIPER_JOINT_LOWER_RAD[index] - 1e-6)
    with pytest.raises(ValueError, match="exceeds configured limits"):
        validate_joint_target(target)


@pytest.mark.parametrize('value', [np.nan, np.inf, -np.inf])
def test_still_rejects_nonfinite_targets(value):
    with pytest.raises(ValueError, match='six finite radians'):
        validate_joint_target(np.full(6, value))


def test_confirmed_calibration_normalizes_feedback_and_inverts_targets():
    calibration = PiperJointCalibration(
        signs=np.array([1, -1, 1, 1, 1, 1]),
        offsets_rad=np.array([0, 0, -2 * np.pi, 0, 0, 0]),
        source="test fixture",
    )
    raw = np.array([0.0, -2.0, 4.0, 0.0, 0.0, 0.0])
    canonical = calibration.normalize_feedback(raw)
    np.testing.assert_allclose(canonical, [0.0, 2.0, 4.0 - 2 * np.pi, 0.0, 0.0, 0.0])
    np.testing.assert_allclose(calibration.sdk_target(canonical), raw)


def test_target_send_requires_calibration_after_target_validation():
    from scripts.driver import PiperSdkArm

    arm = object.__new__(PiperSdkArm)
    arm.port = "can-test"
    with pytest.raises(RuntimeError, match="joint calibration is required"):
        arm.send_joints_rad(np.zeros(6))
