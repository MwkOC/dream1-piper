"""Dream-1 adapter copied from the working Piper deployment profile."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

from .config import DreamConfig
from .control import ContractError, RobotSchema
from .kinematics import DampedLeastSquares, DlsSettings, UrdfArm
from .protocol import Observation


def _quaternion_xyzw(rotation: np.ndarray) -> list[float]:
    matrix = np.asarray(rotation, dtype=float)
    trace = float(np.trace(matrix))
    if trace > 0:
        scale = 2.0 * np.sqrt(trace + 1.0)
        values = [
            (matrix[2, 1] - matrix[1, 2]) / scale,
            (matrix[0, 2] - matrix[2, 0]) / scale,
            (matrix[1, 0] - matrix[0, 1]) / scale,
            scale / 4.0,
        ]
    else:
        axis = int(np.argmax(np.diag(matrix)))
        next_axis, last_axis = (axis + 1) % 3, (axis + 2) % 3
        scale = 2.0 * np.sqrt(
            1.0 + matrix[axis, axis] - matrix[next_axis, next_axis] - matrix[last_axis, last_axis]
        )
        xyz = [0.0, 0.0, 0.0]
        xyz[axis] = scale / 4.0
        xyz[next_axis] = (matrix[next_axis, axis] + matrix[axis, next_axis]) / scale
        xyz[last_axis] = (matrix[last_axis, axis] + matrix[axis, last_axis]) / scale
        values = [*xyz, (matrix[last_axis, next_axis] - matrix[next_axis, last_axis]) / scale]
    return (np.asarray(values) / np.linalg.norm(values)).tolist()


def _dotenv() -> None:
    from dotenv import load_dotenv

    load_dotenv(Path.cwd() / ".env", override=False)


def validate_arm_file(path: Path, *, require_confirmation: bool) -> dict[str, Any]:
    try:
        arm = json.loads(path.read_text(encoding="utf-8"))
        urdf = path.parent / str(arm["urdf"])
        contents = urdf.read_bytes()
        root = ET.fromstring(contents)
    except (OSError, KeyError, json.JSONDecodeError, ET.ParseError) as exc:
        raise ContractError(f"cannot read Dream Piper assets: {exc}") from exc
    meshes = set()
    for mesh in root.findall(".//mesh"):
        filename = str(mesh.get("filename", ""))
        candidate = (urdf.parent / filename).resolve()
        if (
            not filename
            or Path(filename).is_absolute()
            or not candidate.is_relative_to(urdf.parent.resolve())
            or not candidate.is_file()
        ):
            raise ContractError(f"missing or unsafe Piper mesh: {filename}")
        meshes.add(filename)
    for key in ("base", "flange", "tcp", "approach", "jaw", "rest"):
        if key not in arm:
            raise ContractError(f"Dream arm file is missing {key}")
    digest = hashlib.sha256(
        contents
        + b"\0"
        + json.dumps(
            {key: arm[key] for key in ("base", "flange", "tcp", "approach", "jaw")}, sort_keys=True
        ).encode()
    ).hexdigest()[:16]
    confirmation = arm.get("tcp_calibration")
    confirmed = (
        isinstance(confirmation, dict)
        and confirmation.get("status") == "calibrated"
        and confirmation.get("digest") == digest
    )
    if require_confirmation and not confirmed:
        raise ContractError("Piper TCP is not confirmed for this URDF")
    return {
        "arm_file": str(path),
        "urdf": str(urdf),
        "tcp_confirmed": confirmed,
        "mesh_count": len(meshes),
    }


def validate_dream_schema(schema: RobotSchema, config: DreamConfig) -> None:
    canonical = tuple(
        [
            *(f"left_joint_{number}" for number in range(1, 7)),
            "left_gripper",
            *(f"right_joint_{number}" for number in range(1, 7)),
            "right_gripper",
        ]
    )
    if (
        schema.robot_type != "piper"
        or schema.action_space != "radians"
        or tuple(schema.action_names) != canonical
    ):
        raise ContractError("Dream-1 requires the canonical left-first 14D Piper schema")
    if not np.isclose(schema.control_hz, config.action_hz):
        raise ContractError("station control_hz differs from Dream action_hz")


class DreamDls:
    """The incremental source DLS: it bounds each 20 Hz step, not final pose error."""

    def __init__(self, config: DreamConfig):
        self.config = config
        self.arm = UrdfArm(config.arm_file)
        self.solver = DampedLeastSquares(
            self.arm, rate_hz=config.action_hz, settings=DlsSettings(**config.dls)
        )

    def observation(self, state: np.ndarray, payload: dict[str, Any]) -> dict[str, Any]:
        for side, start in (("left", 0), ("right", 7)):
            pose = self.arm.forward(state[start : start + 6])
            payload[f"state.{side}_eef_xyz"] = pose[:3, 3]
            payload[f"state.{side}_eef_rot6"] = np.r_[pose[:3, 0], pose[:3, 1]]
            payload[f"state.{side}_arm"] = np.zeros(6)
            payload[f"state.{side}_gripper"] = state[start + 6 : start + 7]
        return payload

    def tcp_targets(self, values: tuple[float, ...]) -> dict[str, dict[str, Any]]:
        targets = {}
        for side, start in (("left", 0), ("right", 7)):
            pose = self.arm.forward(np.asarray(values[start : start + 6], dtype=float))
            targets[side] = {
                "frame_id": f"{side}_base_link",
                "position": pose[:3, 3].tolist(),
                "orientation": _quaternion_xyzw(pose[:3, :3]),
            }
        return targets

    @staticmethod
    def _target(position: np.ndarray, rot6: np.ndarray) -> np.ndarray:
        x = np.asarray(rot6[:3], dtype=float)
        x /= np.linalg.norm(x)
        y = np.asarray(rot6[3:], dtype=float)
        y -= np.dot(x, y) * x
        if np.linalg.norm(y) < 1e-8:
            raise ContractError("degenerate Dream rot6 orientation")
        y /= np.linalg.norm(y)
        pose = np.eye(4)
        pose[:3, :3] = np.column_stack((x, y, np.cross(x, y)))
        pose[:3, 3] = position
        return pose

    def solve(self, reply: Any, state: np.ndarray) -> np.ndarray:
        parts = reply.get("per_key") if isinstance(reply, dict) else None
        if not isinstance(parts, dict):
            raise ContractError("DLS requires named EEF Dream actions")
        chunks: list[np.ndarray] = []
        count: int | None = None
        for side, start in (("left", 0), ("right", 7)):
            try:
                xyz = np.asarray(parts[f"action.{side}_eef_xyz"], dtype=float)
                rot = np.asarray(parts[f"action.{side}_eef_rot6"], dtype=float)
                grip = np.asarray(parts[f"action.{side}_grip"], dtype=float)
            except (KeyError, TypeError, ValueError) as exc:
                raise ContractError("DLS reply lacks named EEF actions") from exc
            if grip.ndim == 1:
                grip = grip[:, None]
            if (
                xyz.ndim != 2
                or xyz.shape[1] != 3
                or rot.shape != (len(xyz), 6)
                or grip.shape != (len(xyz), 1)
                or not len(xyz)
                or not all(np.isfinite(item).all() for item in (xyz, rot, grip))
            ):
                raise ContractError("invalid EEF Dream action chunk")
            if count not in (None, len(xyz)):
                raise ContractError("Dream EEF chunks have inconsistent lengths")
            count = len(xyz)
            q = np.asarray(state[start : start + 6], dtype=float).copy()
            rows = []
            for position, orientation, opening in zip(xyz, rot, grip, strict=True):
                q = self.solver.step(
                    q, self._target(position, orientation), dt_s=1 / self.config.action_hz
                )
                rows.append(np.r_[q, np.clip(opening[0], 0.0, 1.0)])
            chunks.append(np.asarray(rows))
        return np.concatenate(chunks, axis=1)


class DreamPiperPolicy:
    def __init__(self, config: DreamConfig, *, client: Any | None = None):
        validate_arm_file(config.arm_file, require_confirmation=config.require_tcp_confirmation)
        if client is None:
            _dotenv()
            import dream

            client = dream.DreamClient()
        self.config, self.client = config, client
        self._local_ik = DreamDls(config) if config.solver == "dls" else None
        self._measured_state: np.ndarray | None = None
        self._lock = threading.Lock()
        self._open_policy()

    def _open_policy(self) -> None:
        video = {
            role: f"observation.images.{local}" for local, role in self.config.camera_roles.items()
        }
        embodiment = {
            "state": {
                "right_arm": [0, 6],
                "right_gripper": [6, 7],
                "left_arm": [7, 13],
                "left_gripper": [13, 14],
                "right_eef_xyz": [14, 17],
                "right_eef_rot6": [17, 23],
                "right_grip": [23, 24],
                "left_eef_xyz": [24, 27],
                "left_eef_rot6": [27, 33],
                "left_grip": [33, 34],
            },
            "action": {
                "right_arm": [0, 6],
                "left_arm": [6, 12],
                "right_eef_xyz": [12, 15],
                "right_eef_rot6": [15, 21],
                "right_grip": [21, 22],
                "left_eef_xyz": [22, 25],
                "left_eef_rot6": [25, 31],
                "left_grip": [31, 32],
            },
            "video": video,
        }
        policy: dict[str, Any] = {
            "checkpoint": self.config.checkpoint,
            "timeout_ms": self.config.timeout_ms,
            "strict": True,
            "robot": "other_embodiment",
            "embodiment": embodiment,
            "obs_window": self.config.obs_window,
            "obs_fps": self.config.obs_fps,
            "action_hz": self.config.action_hz,
            "execution_horizon": self.config.execution_horizon,
            "sync_above_ms": self.config.sync_above_ms,
        }
        if self._local_ik is None:
            policy["ik"] = {
                "arm": str(self.config.arm_file),
                "head": "eef",
                "solve": self.config.solver,
            }
        self.client.policy(policy)

    def set_observation(self, observation: Observation) -> None:
        state = np.asarray(observation.state, dtype=np.float32)
        if state.shape != (14,):
            raise ContractError("Dream-1 needs a 14D Piper observation")
        frames = {
            f"video.{role}": base64.b64encode(observation.images[local]).decode("ascii")
            for local, role in self.config.camera_roles.items()
        }
        payload: dict[str, Any] = {
            "state.right_arm": state[7:13],
            "state.right_grip": state[13:14],
            "state.left_arm": state[:6],
            "state.left_grip": state[6:7],
            "prompt": self.config.task,
        }
        if getattr(self, "_local_ik", None) is not None:
            self._measured_state = state.copy()
            payload = self._local_ik.observation(state, payload)
        self.client.set_observation(
            frames, payload, timestamp=observation.station_monotonic_ns / 1e9
        )

    def get_chunk(self, commanded: tuple[float, ...] | None = None) -> np.ndarray:
        with self._lock:
            measured = None if self._measured_state is None else self._measured_state.copy()
            seam = (
                None
                if commanded is None
                else {
                    "q_l_chunk": np.asarray(commanded[:6]),
                    "q_r_chunk": np.asarray(commanded[7:13]),
                }
            )
            reply = self.client.get_action(commanded=seam if self._local_ik is None else None)
            if self._local_ik is not None:
                if measured is None:
                    raise ContractError("DLS needs an observation before inference")
                return self._local_ik.solve(reply, measured)
        raise ContractError("non-DLS Piper operation is not enabled in this experiment")

    def refill_due(self, executed: int, remaining: int) -> bool:
        return bool(self.client.refill_due(executed, remaining))

    def tcp_targets(self, values: tuple[float, ...]) -> dict[str, dict[str, Any]]:
        if self._local_ik is None:
            return {}
        return self._local_ik.tcp_targets(values)

    def reset_episode(self) -> None:
        with self._lock:
            self.client.reset_episode()

    @property
    def timing(self) -> dict[str, Any]:
        return dict(self.client.last_timing or {})

    @property
    def pacing_mode(self) -> str:
        return str(getattr(self.client, "mode", "unknown"))

    def close(self) -> None:
        with self._lock:
            self.client.close()
