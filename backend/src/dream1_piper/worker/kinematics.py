"""Source-profile Piper URDF and incremental DLS kinematics.

This is intentionally local to the experiment.  It keeps the physical Piper
adapter independent of the application's legacy SciPy global IK solver.
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np


def _origin(xyz: tuple[float, ...], rpy: tuple[float, ...]) -> np.ndarray:
    roll, pitch, yaw = rpy
    cr, sr, cp, sp, cy, sy = (
        np.cos(roll),
        np.sin(roll),
        np.cos(pitch),
        np.sin(pitch),
        np.cos(yaw),
        np.sin(yaw),
    )
    result = np.eye(4)
    result[:3, :3] = (
        (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
        (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
        (-sp, cp * sr, cp * cr),
    )
    result[:3, 3] = xyz
    return result


def _rotation_vector(rotation: np.ndarray) -> np.ndarray:
    matrix = np.asarray(rotation, dtype=np.float64).reshape(3, 3)
    cosine = float(np.clip((np.trace(matrix) - 1.0) / 2.0, -1.0, 1.0))
    angle = math.acos(cosine)
    if angle < 1e-10:
        return np.zeros(3)
    axis = np.array(
        (matrix[2, 1] - matrix[1, 2], matrix[0, 2] - matrix[2, 0], matrix[1, 0] - matrix[0, 1])
    )
    norm = np.linalg.norm(axis)
    return np.zeros(3) if norm < 1e-10 else axis * (angle / norm)


@dataclass(frozen=True)
class DlsSettings:
    base_damping: float = 0.05
    singularity_damping: float = 0.15
    singular_value_threshold: float = 0.05
    rest_gain: float = 0.02
    orientation_weight: float = 0.1
    orientation_hold_rad: float = 2.2
    max_step_multiplier: float = 2.0

    def __post_init__(self) -> None:
        if any(
            not math.isfinite(float(value)) or float(value) < 0 for value in vars(self).values()
        ):
            raise ValueError("DLS settings must be finite and non-negative")
        if (
            self.base_damping <= 0
            or self.singular_value_threshold <= 0
            or self.max_step_multiplier < 1
        ):
            raise ValueError("invalid DLS damping or step multiplier")


class UrdfArm:
    def __init__(self, arm_file: Path):
        spec = json.loads(arm_file.read_text(encoding="utf-8"))
        root = ET.parse(arm_file.parent / str(spec["urdf"])).getroot()
        self.chain, limits = _arm_chain(root, str(spec["base"]), str(spec["flange"]))
        self.lower, self.upper, self.speed = map(np.asarray, limits)
        self.rest = np.asarray(spec["rest"], dtype=float)
        self.tool = _tool_transform(spec)

    def _evaluate(
        self, joints: np.ndarray
    ) -> tuple[np.ndarray, list[np.ndarray], list[np.ndarray], np.ndarray]:
        q = np.asarray(joints, dtype=float).reshape(len(self.lower))
        transform = np.eye(4)
        origins: list[np.ndarray] = []
        axes: list[np.ndarray] = []
        points = [np.zeros(3)]
        index = 0
        for origin, axis, kind in self.chain:
            transform = transform @ origin
            points.append(transform[:3, 3].copy())
            if kind == "fixed":
                continue
            origins.append(transform[:3, 3].copy())
            axes.append(transform[:3, :3] @ axis)
            x, y, z = axis
            skew = np.array(((0, -z, y), (z, 0, -x), (-y, x, 0)))
            rotation = np.eye(4)
            rotation[:3, :3] += np.sin(q[index]) * skew + (1 - np.cos(q[index])) * skew @ skew
            transform = transform @ rotation
            index += 1
        transform = transform @ self.tool
        points.append(transform[:3, 3].copy())
        return transform, origins, axes, np.asarray(points)

    def forward(self, joints: np.ndarray) -> np.ndarray:
        return self._evaluate(joints)[0]

    def link_positions(self, joints: np.ndarray) -> np.ndarray:
        return self._evaluate(joints)[3]

    def jacobian(self, joints: np.ndarray) -> np.ndarray:
        pose, origins, axes, _ = self._evaluate(joints)
        return np.vstack(
            (
                np.array(
                    [
                        np.cross(axis, pose[:3, 3] - origin)
                        for axis, origin in zip(axes, origins, strict=True)
                    ]
                ).T,
                np.array(axes).T,
            )
        )


def _arm_chain(root, base, flange):
    by_child = {joint.find("child").get("link"): joint for joint in root.findall("joint")}
    joints, link = [], flange
    while link != base:
        joint = by_child[link]
        if joint in joints:
            raise ValueError("URDF chain contains a cycle")
        joints.append(joint)
        link = joint.find("parent").get("link")
    chain, lower, upper, speed = [], [], [], []
    for joint in reversed(joints):
        kind = str(joint.get("type"))
        if kind not in {"fixed", "revolute"}:
            raise ValueError("only fixed and bounded revolute joints are supported")
        chain.append((_joint_origin(joint), _joint_axis(joint), kind))
        if kind == "revolute":
            limit = joint.find("limit")
            lower.append(float(limit.get("lower")))
            upper.append(float(limit.get("upper")))
            speed.append(float(limit.get("velocity")))
    return chain, (lower, upper, speed)


def _joint_origin(joint):
    node = joint.find("origin")
    xyz = tuple(map(float, node.get("xyz", "0 0 0").split())) if node is not None else (0, 0, 0)
    rpy = tuple(map(float, node.get("rpy", "0 0 0").split())) if node is not None else (0, 0, 0)
    return _origin(xyz, rpy)


def _joint_axis(joint):
    node = joint.find("axis")
    axis = (
        np.array(list(map(float, node.get("xyz").split())))
        if node is not None
        else np.array([1.0, 0.0, 0.0])
    )
    return axis / np.linalg.norm(axis)


def _tool_transform(spec):
    transform = np.eye(4)
    transform[:3, 3] = spec["tcp"]
    z = np.asarray(spec["approach"], dtype=float)
    z /= np.linalg.norm(z)
    x = np.asarray(spec["jaw"], dtype=float)
    x -= np.dot(x, z) * z
    x /= np.linalg.norm(x)
    transform[:3, :3] = np.column_stack((x, np.cross(z, x), z))
    return transform


class DampedLeastSquares:
    def __init__(self, arm: UrdfArm, *, rate_hz: float, settings: DlsSettings):
        self.arm, self.settings = arm, settings
        self.rest = arm.rest
        self.lower = arm.lower
        self.upper = arm.upper
        self.speed = np.minimum(arm.speed, 0.5)
        self.nominal_dt = 1.0 / rate_hz

    def step(self, current: np.ndarray, target: np.ndarray, *, dt_s: float) -> np.ndarray:
        q = np.asarray(current, dtype=np.float64).reshape(6)
        current_pose = self.arm.forward(q)
        error = np.r_[
            target[:3, 3] - current_pose[:3, 3],
            _rotation_vector(target[:3, :3] @ current_pose[:3, :3].T),
        ]
        weights = np.ones(6)
        weights[3:] = (
            0.0
            if np.linalg.norm(error[3:]) > self.settings.orientation_hold_rad
            else self.settings.orientation_weight
        )
        jacobian = self.arm.jacobian(q) * weights[:, None]
        smallest = float(np.min(np.linalg.svd(jacobian, compute_uv=False)))
        ramp = max(0.0, 1.0 - smallest / self.settings.singular_value_threshold)
        damping_sq = self.settings.base_damping**2 + (self.settings.singularity_damping * ramp) ** 2
        rest_sq = self.settings.rest_gain**2
        candidate = np.clip(
            q
            + np.linalg.solve(
                jacobian.T @ jacobian + (damping_sq + rest_sq) * np.eye(6),
                jacobian.T @ (error * weights) + rest_sq * (self.rest - q),
            ),
            self.lower,
            self.upper,
        )
        dt = (
            min(dt_s, self.nominal_dt * self.settings.max_step_multiplier)
            if math.isfinite(dt_s) and dt_s > 0
            else self.nominal_dt
        )
        return np.clip(
            q + np.clip(candidate - q, -self.speed * dt, self.speed * dt), self.lower, self.upper
        )
