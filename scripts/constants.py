"""Configured Piper joint limits shared by control and kinematics."""

from __future__ import annotations

import numpy as np
PIPER_NOMINAL_LOWER_RAD = np.array([-2.618, 0.0, -2.967, -1.745, -1.22, -2.0944])
PIPER_NOMINAL_UPPER_RAD = np.array([2.618, 3.14, 0.0, 1.745, 1.22, 2.0944])
# Each endpoint gains 3% of the nominal joint travel (including zero endpoints).
# Keep assets/piper/piper.urdf in sync when changing this configured margin.
PIPER_JOINT_MARGIN_FRACTION = 0.03
_JOINT_MARGIN_RAD = (PIPER_NOMINAL_UPPER_RAD - PIPER_NOMINAL_LOWER_RAD) * PIPER_JOINT_MARGIN_FRACTION
PIPER_JOINT_LOWER_RAD = np.round(PIPER_NOMINAL_LOWER_RAD - _JOINT_MARGIN_RAD, 10)
PIPER_JOINT_UPPER_RAD = np.round(PIPER_NOMINAL_UPPER_RAD + _JOINT_MARGIN_RAD, 10)

def validate_joint_target(joints: np.ndarray) -> np.ndarray:
    """Return a finite, in-range canonical J1..J6 target in radians.

    These limits protect commands headed to the controller.  SDK feedback must
    be normalized with an explicitly confirmed joint calibration before it is
    passed here; raw encoder values are not command coordinates.
    """
    values = np.asarray(joints, dtype=np.float64)
    if values.shape != (6,) or not np.isfinite(values).all():
        raise ValueError("Piper joint target must contain six finite radians")
    outside = (values < PIPER_JOINT_LOWER_RAD) | (values > PIPER_JOINT_UPPER_RAD)
    if np.any(outside):
        details = []
        for index in np.flatnonzero(outside):
            value = values[index]
            lower, upper = PIPER_JOINT_LOWER_RAD[index], PIPER_JOINT_UPPER_RAD[index]
            excess = max(lower - value, value - upper)
            details.append(
                f"J{index + 1}: leído={np.rad2deg(value):.6f}° "
                f"({value:.9f} rad), rango=[{np.rad2deg(lower):.6f}°, "
                f"{np.rad2deg(upper):.6f}°], exceso={np.rad2deg(excess):.6f}°"
            )
        raise ValueError("Piper joint target exceeds configured limits: " + "; ".join(details))
    return values.copy()


def validate_joint_feedback(joints: np.ndarray) -> np.ndarray:
    """Return raw SDK feedback after structural validation only.

    This is intentionally separate from :func:`validate_joint_target`: a raw
    encoder vector is useful for diagnosis but cannot authorize movement.
    """
    values = np.asarray(joints, dtype=np.float64)
    if values.shape != (6,) or not np.isfinite(values).all():
        raise ValueError("Piper joint feedback must contain six finite radians")
    return values.copy()


__all__ = [
    "PIPER_JOINT_LOWER_RAD",
    "PIPER_JOINT_UPPER_RAD",
    "validate_joint_feedback",
    "validate_joint_target",
]
