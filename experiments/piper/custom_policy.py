"""Dream EEF actions solved using the installation's two Piper chains."""
from threading import Lock

import numpy as np

from .kinematics import PiperKinematics


class PiperPolicy:
    def __init__(self, client, config):
        self.client = client
        self.kin = {
            side: PiperKinematics(config.urdf, config.frames[f"{side}_base"],
                                  config.frames[f"{side}_tcp"], side)
            for side in ("left", "right")
        }
        self._measured = {}
        self._lock = Lock()

    def __getattr__(self, name):
        return getattr(self.client, name)

    def set_observation(self, frames, observation, **kwargs):
        observation = dict(observation)
        measured = {}
        for side, kin in self.kin.items():
            q = np.asarray(observation[f"state.{side}_arm"], dtype=float)
            pose = kin.forward_matrix(q)
            measured[side] = q.copy()
            observation[f"state.{side}_eef_xyz"] = pose[:3, 3].tolist()
            observation[f"state.{side}_eef_rot6"] = pose[:3, :2].T.reshape(-1).tolist()
        with self._lock:
            self._measured = measured
        self.client.set_observation(frames, observation, **kwargs)

    def get_action(self, commanded=None):
        with self._lock:
            seeds = {side: q.copy() for side, q in self._measured.items()}
        # The custom solver owns joint continuity. Do not send Piper joint rows
        # to the upstream model's possibly different joint head/smoother.
        action = self.client.get_action()
        parts = action["per_key"]
        solved = dict(action)
        report = {}
        for side, kin in self.kin.items():
            key = "q_l_chunk" if side == "left" else "q_r_chunk"
            xyz = np.asarray(parts[f"action.{side}_eef_xyz"], dtype=float)
            rot = np.asarray(parts[f"action.{side}_eef_rot6"], dtype=float)
            grip = np.asarray(parts[f"action.{side}_grip"], dtype=float).reshape(-1)
            if xyz.ndim != 2 or xyz.shape[1:] != (3,) or len(xyz) == 0 or rot.shape != (len(xyz), 6) or grip.shape != (len(xyz),):
                raise ValueError(f"Invalid {side} EEF action shapes")
            if not all(np.isfinite(v).all() for v in (xyz, rot, grip)) or np.any((grip < 0) | (grip > 1)):
                raise ValueError(f"Invalid {side} EEF/gripper values")
            q = seeds[side] if commanded is None else np.asarray(commanded[key], dtype=float)[:6]
            rows, errors = [], []
            for point, orientation, opening in zip(xyz, rot, grip):
                q, pe, re = kin.solve(point, orientation, q)
                if np.any(q < kin.lower) or np.any(q > kin.upper):
                    raise ValueError(f"{side} IK exceeded joint limits")
                rows.append(np.r_[q, opening])
                errors.append((pe, re))
            solved[key] = np.asarray(rows)
            report[side] = {"max_position_error_m": max(e[0] for e in errors),
                            "max_rotation_error_rad": max(e[1] for e in errors)}
        if len(solved["q_l_chunk"]) != len(solved["q_r_chunk"]):
            raise ValueError("Unequal bimanual action horizons")
        solved["ik_report"] = report
        return solved
