"""Small validation and retry helpers used by worker runtime."""

from __future__ import annotations

from typing import Any

import numpy as np

from .control import ContractError, RobotSchema


def retryable(exc: Exception) -> bool:
    try:
        from dream.errors import DreamAuthError, DreamConfigError, DreamError, DreamObservationError, DreamServerError
    except ImportError:
        return isinstance(exc, (ContractError, TimeoutError))
    if isinstance(exc, (DreamAuthError, DreamConfigError, DreamObservationError)):
        return False
    return exc.retryable if isinstance(exc, DreamServerError) else isinstance(exc, (DreamError, ContractError, TimeoutError))


def validate_action(schema: RobotSchema, row: Any) -> tuple[float, ...]:
    values = np.asarray(row, dtype=np.float64).reshape(-1).copy()
    for index, limit in enumerate(schema.joint_limits):
        if index % 7 != 6 and limit.minimum - 1e-5 <= values[index] <= limit.maximum + 1e-5:
            values[index] = np.clip(values[index], limit.minimum, limit.maximum)
    return tuple(float(value) for value in schema.validate_action(values))
