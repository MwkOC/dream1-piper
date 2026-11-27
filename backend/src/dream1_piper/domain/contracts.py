from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RunState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    READY = "READY"
    ARMED = "ARMED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    FAULT = "FAULT"


class ControlSource(StrEnum):
    DREAM = "dream"
    TELEOP = "teleop"
    HOME = "home"


class OperationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class ArmCommand(OperationCommand):
    control_source: Literal["dream", "teleop"]
    selected_arm: Literal["left", "right"] | None = None


class TaskCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str = Field(min_length=1, max_length=2000)
    task_id: UUID | None = None


class TaskRecordCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=2000)

    @field_validator("name", "prompt")
    @classmethod
    def trim_task_fields(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("field cannot be blank")
        return value


class PurgeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: str = Field(min_length=1, max_length=32)


class LoginCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operator_token: str = Field(min_length=1)


class TeleopLimits(BaseModel):
    jog_speed_m_s: float
    linear_limit_m_s: float
    angular_limit_rad_s: float


class StatusResponse(BaseModel):
    state: RunState
    session_id: str | None
    operation_id: str | None
    control_generation: int
    control_source: ControlSource | None
    selected_arm: Literal["left", "right"] | None
    task: str
    hardware_validated: bool
    worker_connected: bool
    arms: dict[str, dict[str, object]]
    cameras: dict[str, dict[str, object]]
    last_fault: str | None
    teleop_limits: TeleopLimits
