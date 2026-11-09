"""Physical Piper joint limits shared by control and kinematics."""

from __future__ import annotations

import numpy as np

PIPER_JOINT_LOWER_RAD = np.array([-2.618, 0.0, -2.967, -1.745, -1.22, -2.0944])
PIPER_JOINT_UPPER_RAD = np.array([2.618, 3.14, 0.0, 1.745, 1.22, 2.0944])

__all__ = ["PIPER_JOINT_LOWER_RAD", "PIPER_JOINT_UPPER_RAD"]
