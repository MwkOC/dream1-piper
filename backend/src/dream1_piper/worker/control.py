"""Station-local schema and motion authority for the Piper experiment."""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass

import numpy as np


class ContractError(ValueError):
    """A wire message or motion target violates the configured robot contract."""


@dataclass(frozen=True)
class JointLimit:
    minimum: float
    maximum: float
    max_speed: float
    max_acceleration: float

    def validate(self, value: float) -> bool:
        return bool(np.isfinite(value) and self.minimum <= value <= self.maximum)


@dataclass(frozen=True)
class RobotSchema:
    name: str
    version: int
    control_hz: float
    action_names: tuple[str, ...]
    state_names: tuple[str, ...]
    action_space: str
    robot_type: str
    joint_limits: tuple[JointLimit, ...]

    def __post_init__(self) -> None:
        if self.control_hz <= 0 or len(self.action_names) != 14:
            raise ContractError("Piper schema requires a positive rate and fourteen action names")
        if self.state_names != self.action_names or len(self.joint_limits) != 14:
            raise ContractError("Piper state names and joint limits must match the 14D action")
        if self.action_space != "radians" or self.robot_type != "piper":
            raise ContractError("Piper station requires radians and robot_type=piper")

    def validate_action(self, values: tuple[float, ...] | list[float] | np.ndarray) -> np.ndarray:
        array = np.asarray(values, dtype=np.float64).reshape(-1)
        if array.size != 14:
            raise ContractError(f"expected 14 action values, got {array.size}")
        for name, limit, value in zip(self.action_names, self.joint_limits, array, strict=True):
            if not limit.validate(float(value)):
                raise ContractError(f"{name}={value} is outside [{limit.minimum}, {limit.maximum}]")
        return array

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "control_hz": self.control_hz,
            "action_names": list(self.action_names),
            "state_names": list(self.state_names),
            "action_space": self.action_space,
            "robot_type": self.robot_type,
            "joint_limits": [limit.__dict__ for limit in self.joint_limits],
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> RobotSchema:
        return cls(
            name=str(value["name"]),
            version=int(value["version"]),
            control_hz=float(value["control_hz"]),
            action_names=tuple(str(item) for item in value["action_names"]),
            state_names=tuple(str(item) for item in value["state_names"]),
            action_space=str(value["action_space"]),
            robot_type=str(value["robot_type"]),
            joint_limits=tuple(JointLimit(**limit) for limit in value["joint_limits"]),
        )


class RunState(str, enum.Enum):
    DISCONNECTED = "disconnected"
    READY = "ready"
    ARMED = "armed"
    RUNNING = "running"
    PAUSED = "paused"
    FAULT = "fault"


@dataclass(frozen=True)
class PolicyAction:
    session_id: str
    sequence_id: int
    observation_id: int
    station_monotonic_ns: int
    schema_version: int
    values: tuple[float, ...]
    scheduled: bool = False
    control_generation: int = 0
    invocation_id: str | None = None


class MotionSupervisor:
    """Owns the explicit arm/start lifecycle and validates remote targets."""

    def __init__(
        self, schema: RobotSchema, *, action_age_ms: float, scheduled_action_age_ms: float
    ):
        self.schema = schema
        self.action_age_ns = int(action_age_ms * 1_000_000)
        self.scheduled_action_age_ns = int(scheduled_action_age_ms * 1_000_000)
        if min(self.action_age_ns, self.scheduled_action_age_ns) <= 0:
            raise ValueError("action age limits must be positive")
        self.state = RunState.DISCONNECTED
        self.session_id: str | None = None
        self.last_sequence_id = -1
        self.last_action_at_ns: int | None = None
        self.run_started_at_ns: int | None = None
        self.last_fault: str | None = None
        # A policy chunk belongs to one explicit control epoch.  Starting again
        # after a pause must never make a queued old chunk valid.
        self.control_generation = 0

    def connected(self) -> None:
        self.state, self.last_fault = RunState.READY, None

    def arm(self) -> str:
        if self.state not in {RunState.READY, RunState.PAUSED}:
            raise RuntimeError(f"cannot arm while {self.state.value}")
        self.session_id = uuid.uuid4().hex
        self.last_sequence_id = -1
        self.last_action_at_ns = None
        self.run_started_at_ns = None
        self.control_generation += 1
        self.state = RunState.ARMED
        return self.session_id

    def start(self) -> None:
        if self.state != RunState.ARMED:
            raise RuntimeError("station must be armed before execution")
        self.state = RunState.RUNNING
        self.run_started_at_ns = time.monotonic_ns()

    def pause(self, reason: str) -> None:
        if self.state == RunState.FAULT:
            return
        if self.state != RunState.DISCONNECTED:
            self.state = RunState.PAUSED
        self.last_fault = reason

    def fault(self, reason: str) -> None:
        self.state, self.last_fault, self.session_id = RunState.FAULT, reason, None
        self.control_generation += 1

    def reset_fault(self) -> None:
        if self.state != RunState.FAULT:
            raise RuntimeError("no fault to reset")
        self.state = RunState.READY
        self.last_fault = None
        self.last_sequence_id = -1
        self.control_generation += 1

    def validate(self, action: PolicyAction, *, now_ns: int | None = None) -> str | None:
        now = time.monotonic_ns() if now_ns is None else now_ns
        if self.state != RunState.RUNNING:
            return f"station is {self.state.value}"
        if action.session_id != self.session_id:
            return "session does not match current armed session"
        if action.schema_version != self.schema.version:
            return "schema version does not match station"
        if action.control_generation != self.control_generation:
            return "action belongs to an inactive control generation"
        if action.sequence_id <= self.last_sequence_id:
            return "action sequence is stale or duplicated"
        age_limit = self.scheduled_action_age_ns if action.scheduled else self.action_age_ns
        if now - action.station_monotonic_ns > age_limit:
            return "action was computed from an expired observation"
        try:
            self.schema.validate_action(action.values)
        except ContractError as exc:
            return str(exc)
        self.last_sequence_id, self.last_action_at_ns = action.sequence_id, now
        return None

    def watchdog_expired(self, timeout_ms: float, first_action_timeout_ms: float) -> bool:
        if self.state != RunState.RUNNING:
            return False
        now = time.monotonic_ns()
        if self.last_action_at_ns is None:
            return self.run_started_at_ns is not None and now - self.run_started_at_ns > int(
                first_action_timeout_ms * 1_000_000
            )
        return now - self.last_action_at_ns > int(timeout_ms * 1_000_000)
