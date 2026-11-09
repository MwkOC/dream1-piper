"""URDF forward and inverse kinematics for the Piper Dream EEF actions."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from .constants import PIPER_JOINT_LOWER_RAD, PIPER_JOINT_UPPER_RAD


class PiperKinematics:
    """Solve a six-joint Piper chain described in a URDF."""

    def __init__(self, urdf: Path, base: str, tcp_link: str, side: str):
        root = ET.parse(urdf).getroot()
        by_child = {joint.find("child").get("link"): joint for joint in root.findall("joint")}
        chain = []
        link = tcp_link
        while link != base:
            if link not in by_child:
                raise ValueError(f"No URDF chain from {base} to {tcp_link}")
            joint = by_child[link]
            chain.append(joint)
            link = joint.find("parent").get("link")
            if len(chain) > 100:
                raise ValueError("URDF chain contains a cycle")
        self.chain = list(reversed(chain))
        moving = [joint for joint in self.chain if joint.get("type") != "fixed"]
        expected = [f"{side}_joint{index}" for index in range(1, 7)]
        names = [joint.get("name") for joint in moving]
        if names != expected or any(joint.get("type") != "revolute" for joint in moving):
            raise ValueError(f"{side} URDF chain must contain revolute joints {expected}; got {names}")
        self.lower = PIPER_JOINT_LOWER_RAD.copy()
        self.upper = PIPER_JOINT_UPPER_RAD.copy()
        for joint, lower, upper in zip(moving, self.lower, self.upper):
            limit = joint.find("limit")
            if limit is None or float(limit.get("lower")) > lower or float(limit.get("upper")) < upper:
                raise ValueError(f"URDF limits for {joint.get('name')} do not include Piper limits")

    @staticmethod
    def _origin(joint: ET.Element) -> np.ndarray:
        origin = joint.find("origin")
        xyz = np.fromstring(origin.get("xyz", "0 0 0"), sep=" ") if origin is not None else np.zeros(3)
        rpy = np.fromstring(origin.get("rpy", "0 0 0"), sep=" ") if origin is not None else np.zeros(3)
        transform = np.eye(4)
        transform[:3, :3] = Rotation.from_euler("xyz", rpy).as_matrix()
        transform[:3, 3] = xyz
        return transform

    def forward_matrix(self, joints: np.ndarray) -> np.ndarray:
        values = np.asarray(joints, dtype=np.float64).reshape(6)
        if not np.isfinite(values).all():
            raise ValueError("Joint state must be finite")
        transform = np.eye(4)
        index = 0
        for joint in self.chain:
            transform = transform @ self._origin(joint)
            if joint.get("type") == "fixed":
                continue
            axis_node = joint.find("axis")
            axis = np.fromstring(axis_node.get("xyz", "1 0 0"), sep=" ") if axis_node is not None else np.array([1., 0., 0.])
            norm = np.linalg.norm(axis)
            if norm < 1e-12:
                raise ValueError(f"Invalid zero axis in URDF joint {joint.get('name')}")
            transform[:3, :3] = transform[:3, :3] @ Rotation.from_rotvec(axis / norm * values[index]).as_matrix()
            index += 1
        return transform

    @staticmethod
    def rot6_to_matrix(rot6: np.ndarray) -> np.ndarray:
        """Decode Dream's 6D rotation representation as two matrix columns."""
        value = np.asarray(rot6, dtype=np.float64).reshape(6)
        first, second = value[:3].copy(), value[3:].copy()
        first_norm = np.linalg.norm(first)
        if first_norm < 1e-8:
            raise ValueError("Dream EEF rotation has a degenerate first axis")
        first /= first_norm
        second -= first * np.dot(first, second)
        second_norm = np.linalg.norm(second)
        if second_norm < 1e-8:
            raise ValueError("Dream EEF rotation has degenerate axes")
        second /= second_norm
        return np.column_stack((first, second, np.cross(first, second)))

    def solve(self, position: np.ndarray, rot6: np.ndarray, seed: np.ndarray) -> tuple[np.ndarray, float, float]:
        """Find a bounded joint target and reject unreachable EEF poses."""
        target_position = np.asarray(position, dtype=np.float64).reshape(3)
        target_rotation = self.rot6_to_matrix(rot6)
        initial = np.clip(np.asarray(seed, dtype=np.float64).reshape(6), self.lower, self.upper)
        if not np.isfinite(target_position).all() or not np.isfinite(initial).all():
            raise ValueError("Dream EEF target and IK seed must be finite")

        def residual(joints: np.ndarray) -> np.ndarray:
            current = self.forward_matrix(joints)
            translation = current[:3, 3] - target_position
            rotation = Rotation.from_matrix(target_rotation @ current[:3, :3].T).as_rotvec()
            return np.concatenate((translation, 0.12 * rotation))

        result = least_squares(
            residual, initial, bounds=(self.lower, self.upper), max_nfev=60,
            ftol=1e-5, xtol=1e-5, gtol=1e-5,
        )
        transform = self.forward_matrix(result.x)
        position_error = float(np.linalg.norm(transform[:3, 3] - target_position))
        rotation_error = float(np.linalg.norm(
            Rotation.from_matrix(target_rotation @ transform[:3, :3].T).as_rotvec()
        ))
        if position_error > 0.02 or rotation_error > np.deg2rad(10.0):
            raise ValueError(
                "Piper IK could not reach Dream target within tolerance "
                f"(position {position_error:.3f} m, orientation {np.rad2deg(rotation_error):.1f} deg)"
            )
        return result.x, position_error, rotation_error


__all__ = ["PiperKinematics"]
