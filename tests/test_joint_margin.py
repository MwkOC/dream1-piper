import numpy as np
import pytest

from scripts.constants import (
    PIPER_JOINT_LOWER_RAD, PIPER_JOINT_UPPER_RAD, validate_joint_target,
)


def test_reported_startup_posture_fits_configured_margin():
    measured = np.deg2rad([0, -2.169, 4.048, 0, 0, 0])
    np.testing.assert_array_equal(validate_joint_target(measured), measured)


@pytest.mark.parametrize('index', range(6))
@pytest.mark.parametrize('upper', [False, True])
def test_temporarily_accepts_targets_outside_configured_range(index, upper):
    target = (PIPER_JOINT_LOWER_RAD + PIPER_JOINT_UPPER_RAD) / 2
    target[index] = (PIPER_JOINT_UPPER_RAD[index] + 1e-6 if upper
                     else PIPER_JOINT_LOWER_RAD[index] - 1e-6)
    np.testing.assert_array_equal(validate_joint_target(target), target)


@pytest.mark.parametrize('value', [np.nan, np.inf, -np.inf])
def test_still_rejects_nonfinite_targets(value):
    with pytest.raises(ValueError, match='six finite radians'):
        validate_joint_target(np.full(6, value))
