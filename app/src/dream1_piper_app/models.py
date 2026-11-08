"""Small, transport-neutral observation contracts.

These models validate data at the application boundary. They intentionally do
not encode Dream Labs' internal action loop or ROS message types.
"""

from __future__ import annotations

import math
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


FiniteFloat = Annotated[float, Field(strict=True)]


class ObservationEnvelope(BaseModel):
    """An already captured observation, suitable for validation or replay."""

    model_config = ConfigDict(extra="forbid")

    episode_id: str = Field(min_length=1, max_length=128)
    timestamp_ns: int = Field(gt=0)
    task: str = Field(min_length=1, max_length=200)
    frames: dict[str, str] = Field(min_length=1)
    state: dict[str, list[FiniteFloat]] = Field(min_length=1)

    @field_validator("frames")
    @classmethod
    def validate_frames(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not key or not frame for key, frame in value.items()):
            raise ValueError("frames must contain non-empty keys and encoded frames")
        return value

    @field_validator("state")
    @classmethod
    def validate_state(cls, value: dict[str, list[FiniteFloat]]) -> dict[str, list[FiniteFloat]]:
        if any(not key or not values for key, values in value.items()):
            raise ValueError("state must contain non-empty named vectors")
        if any(not math.isfinite(number) for values in value.values() for number in values):
            raise ValueError("state values must be finite")
        return value


class ValidationResponse(BaseModel):
    valid: bool = True
    episode_id: str
    frame_keys: list[str]
    state_keys: list[str]

