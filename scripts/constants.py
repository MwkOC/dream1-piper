"""Configured Piper joint limits shared by control and kinematics."""

from __future__ import annotations

import numpy as np
import logging

LOG = logging.getLogger(__name__)
_limit_warning_reported = False

PIPER_NOMINAL_LOWER_RAD = np.array([-2.618, 0.0, -2.967, -1.745, -1.22, -2.0944])
PIPER_NOMINAL_UPPER_RAD = np.array([2.618, 3.14, 0.0, 1.745, 1.22, 2.0944])
# Each endpoint gains 3% of the nominal joint travel (including zero endpoints).
# Keep assets/piper/piper.urdf in sync when changing this configured margin.
PIPER_JOINT_MARGIN_FRACTION = 0.03
_JOINT_MARGIN_RAD = (PIPER_NOMINAL_UPPER_RAD - PIPER_NOMINAL_LOWER_RAD) * PIPER_JOINT_MARGIN_FRACTION
PIPER_JOINT_LOWER_RAD = np.round(PIPER_NOMINAL_LOWER_RAD - _JOINT_MARGIN_RAD, 10)
PIPER_JOINT_UPPER_RAD = np.round(PIPER_NOMINAL_UPPER_RAD + _JOINT_MARGIN_RAD, 10)

def validate_joint_target(joints: np.ndarray) -> np.ndarray:
    """Return finite J1..J6 radians; temporarily only warn about range excess."""
    global _limit_warning_reported
    values = np.asarray(joints, dtype=np.float64)
    if values.shape != (6,) or not np.isfinite(values).all():
        raise ValueError("Piper joint target must contain six finite radians")
    outside = (values < PIPER_JOINT_LOWER_RAD) | (values > PIPER_JOINT_UPPER_RAD)
    if np.any(outside) and not _limit_warning_reported:
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
        LOG.warning("Límites articulares ignorados temporalmente: %s. "
                    "Se omiten advertencias posteriores de rango en este proceso.",
                    "; ".join(details))
        _limit_warning_reported = True
    return values.copy()


__all__ = ["PIPER_JOINT_LOWER_RAD", "PIPER_JOINT_UPPER_RAD", "validate_joint_target"]
