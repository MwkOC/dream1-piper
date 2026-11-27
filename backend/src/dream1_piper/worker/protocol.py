from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from .control import PolicyAction

VERSION = 1


@dataclass(frozen=True)
class Observation:
    observation_id: int
    station_monotonic_ns: int
    state: tuple[float, ...]
    images: dict[str, bytes]
    control_generation: int = 0


def observation_message(observation: Observation) -> dict[str, Any]:
    return {
        "type": "observation",
        "protocol_version": VERSION,
        "observation_id": observation.observation_id,
        "station_monotonic_ns": observation.station_monotonic_ns,
        "state": list(observation.state),
        "images": {
            name: base64.b64encode(value).decode("ascii")
            for name, value in observation.images.items()
        },
        "control_generation": observation.control_generation,
    }


def parse_observation(value: dict[str, Any]) -> Observation:
    if value.get("type") != "observation" or value.get("protocol_version") != VERSION:
        raise ValueError("unsupported station observation")
    return Observation(
        observation_id=int(value["observation_id"]),
        station_monotonic_ns=int(value["station_monotonic_ns"]),
        state=tuple(float(number) for number in value["state"]),
        images={name: base64.b64decode(image) for name, image in value["images"].items()},
        control_generation=int(value.get("control_generation", 0)),
    )


def action_message(action: PolicyAction) -> dict[str, Any]:
    return {
        "type": "action",
        "protocol_version": VERSION,
        "session_id": action.session_id,
        "sequence_id": action.sequence_id,
        "observation_id": action.observation_id,
        "station_monotonic_ns": action.station_monotonic_ns,
        "schema_version": action.schema_version,
        "values": list(action.values),
        "scheduled": action.scheduled,
        "control_generation": action.control_generation,
        "invocation_id": action.invocation_id,
        "tcp_targets": action.tcp_targets,
    }


def parse_action(value: dict[str, Any]) -> PolicyAction:
    if value.get("type") != "action" or value.get("protocol_version") != VERSION:
        raise ValueError("unsupported station action")
    return PolicyAction(
        session_id=str(value["session_id"]),
        sequence_id=int(value["sequence_id"]),
        observation_id=int(value["observation_id"]),
        station_monotonic_ns=int(value["station_monotonic_ns"]),
        schema_version=int(value["schema_version"]),
        values=tuple(float(number) for number in value["values"]),
        scheduled=bool(value.get("scheduled", False)),
        control_generation=int(value.get("control_generation", 0)),
        invocation_id=value.get("invocation_id"),
        tcp_targets=value.get("tcp_targets"),
    )
