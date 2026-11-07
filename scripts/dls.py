"""Robot-independent incremental damped-least-squares IK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from scipy.spatial.transform import Rotation


class RobotKinematics(Protocol):
    def forward_matrix(self, joints: np.ndarray) -> np.ndarray: ...
    def jacobian(self, joints: np.ndarray) -> np.ndarray: ...

DEFAULT_DLS_RATE_HZ = 20.0
DEFAULT_JOINT_SPEED_CAP_RAD_S = 1.0


@dataclass(frozen=True)
class DlsConfig:
    lambda_position: float = 0.05
    lambda_singularity: float = 0.15
    singular_value_threshold: float = 0.05
    rest_gain: float = 0.02
    orientation_weight: float = 0.1
    rotation_error_hold_rad: float = 2.2

    def validate(self) -> None:
        values = np.asarray(list(vars(self).values()), dtype=np.float64)
        if not np.isfinite(values).all():
            raise ValueError("DLS parameters must be finite")
        if self.lambda_position <= 0 or self.lambda_singularity < 0:
            raise ValueError("DLS damping values are invalid")
        if self.singular_value_threshold <= 0 or self.rest_gain < 0:
            raise ValueError("DLS threshold/rest gain values are invalid")
        if self.orientation_weight < 0 or self.rotation_error_hold_rad < 0:
            raise ValueError("DLS orientation values are invalid")


class IncrementalDlsSolver:
    """One warm-started weighted-DLS step for a serial robot arm."""

    def __init__(
        self,
        kinematics: RobotKinematics,
        *,
        rest_q: np.ndarray,
        joint_lower_rad: np.ndarray,
        joint_upper_rad: np.ndarray,
        nominal_rate_hz: float = DEFAULT_DLS_RATE_HZ,
        speed_limits_rad_s: np.ndarray | None = None,
        config: DlsConfig | None = None,
    ) -> None:
        if nominal_rate_hz <= 0:
            raise ValueError("nominal_rate_hz must be positive")
        self.kinematics = kinematics
        self.rest_q = np.asarray(rest_q, dtype=np.float64).reshape(-1).copy()
        self.joint_count = self.rest_q.size
        if self.joint_count == 0 or not np.isfinite(self.rest_q).all():
            raise ValueError("rest_q must contain finite joint values")

        self.joint_lower_rad = np.asarray(joint_lower_rad, dtype=np.float64).reshape(
            self.joint_count
        )
        self.joint_upper_rad = np.asarray(joint_upper_rad, dtype=np.float64).reshape(
            self.joint_count
        )
        if (
            not np.isfinite(self.joint_lower_rad).all()
            or not np.isfinite(self.joint_upper_rad).all()
            or np.any(self.joint_lower_rad >= self.joint_upper_rad)
        ):
            raise ValueError("DLS joint limits must be finite and ordered")

        self.nominal_dt_s = 1.0 / float(nominal_rate_hz)
        self._step_dt_s = self.nominal_dt_s
        raw_speed_limits = np.asarray(
            (
                speed_limits_rad_s
                if speed_limits_rad_s is not None
                else np.full(
                    self.joint_count,
                    DEFAULT_JOINT_SPEED_CAP_RAD_S,
                    dtype=np.float64,
                )
            ),
            dtype=np.float64,
        ).reshape(self.joint_count)
        self.speed_limits_rad_s = np.minimum(raw_speed_limits, DEFAULT_JOINT_SPEED_CAP_RAD_S)
        if not np.isfinite(self.speed_limits_rad_s).all() or np.any(self.speed_limits_rad_s <= 0):
            raise ValueError("DLS speed limits must be finite and positive")
        self.config = config or DlsConfig()
        self.config.validate()

    def set_timestep(self, dt_s: float) -> None:
        if not np.isfinite(dt_s) or dt_s <= 0:
            dt_s = self.nominal_dt_s
        self._step_dt_s = min(float(dt_s), 2.0 * self.nominal_dt_s)

    def ik(self, q_current: np.ndarray, target_pose7: np.ndarray) -> np.ndarray:
        q = np.asarray(q_current, dtype=np.float64).reshape(self.joint_count)
        target = np.asarray(target_pose7, dtype=np.float64).reshape(7)
        current = self.kinematics.forward_matrix(q)
        position_error = target[:3] - current[:3, 3]
        rotation_error = Rotation.from_matrix(
            Rotation.from_quat(target[3:7]).as_matrix() @ current[:3, :3].T
        ).as_rotvec()
        task_error = np.concatenate((position_error, rotation_error))

        include_rotation = np.linalg.norm(rotation_error) <= self.config.rotation_error_hold_rad
        orientation_weight = self.config.orientation_weight if include_rotation else 0.0
        weights = np.concatenate((np.ones(3), np.full(3, orientation_weight)))
        jacobian = np.asarray(self.kinematics.jacobian(q), dtype=np.float64).reshape(
            6, self.joint_count
        )
        weighted_jacobian = jacobian * weights[:, None]
        weighted_error = task_error * weights

        singular_values = np.linalg.svd(weighted_jacobian, compute_uv=False)
        sigma_min = float(np.min(singular_values))
        ramp = max(0.0, 1.0 - sigma_min / self.config.singular_value_threshold)
        lambda_squared = (
            self.config.lambda_position**2 + self.config.lambda_singularity**2 * ramp**2
        )
        mu_squared = self.config.rest_gain**2
        normal = weighted_jacobian.T @ weighted_jacobian
        normal += (lambda_squared + mu_squared) * np.eye(self.joint_count)
        rhs = weighted_jacobian.T @ weighted_error
        rhs += mu_squared * (self.rest_q - q)
        delta = np.linalg.solve(normal, rhs)

        candidate = np.clip(q + delta, self.joint_lower_rad, self.joint_upper_rad)
        max_delta = self.speed_limits_rad_s * self._step_dt_s
        bounded = np.clip(candidate - q, -max_delta, max_delta)
        return np.clip(q + bounded, self.joint_lower_rad, self.joint_upper_rad)


__all__ = [
    "DEFAULT_DLS_RATE_HZ",
    "DEFAULT_JOINT_SPEED_CAP_RAD_S",
    "DlsConfig",
    "IncrementalDlsSolver",
]
