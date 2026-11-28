import asyncio
import math
import time
from typing import Literal
from uuid import uuid4

from fastapi import WebSocket
from pydantic import BaseModel, ValidationError, field_validator


class TwistInput(BaseModel):
    type: Literal["jog", "heartbeat"]
    sequence: int
    control_generation: int
    arm: str
    deadman: bool
    linear: list[float]
    angular: list[float]

    @field_validator("linear", "angular")
    @classmethod
    def validate_vector(cls, value):
        if len(value) != 3 or not all(math.isfinite(item) for item in value):
            raise ValueError("twist vectors must contain three finite numbers")
        return value


class TeleopService:
    def __init__(self, station, gateway, settings, metrics, events, event_writer=None):
        self.station = station
        self.gateway = gateway
        self.settings = settings
        self.metrics = metrics
        self.events = events
        self.event_writer = event_writer
        self.active_socket = None
        self.last_sequence = -1
        self.last_message_at = 0.0
        self.deadman_active = False

    async def handle(self, socket: WebSocket):
        if self.active_socket is not None:
            await socket.close(code=4409)
            return
        self.active_socket = socket
        self.last_sequence = -1
        self.last_message_at = 0.0
        self.deadman_active = False
        watchdog = asyncio.create_task(self._watchdog())
        try:
            await self._receive_loop(socket)
        finally:
            watchdog.cancel()
            await asyncio.gather(watchdog, return_exceptions=True)
            await self.release("teleop session ended")

    async def _receive_loop(self, socket):
        while True:
            raw = await socket.receive_json()
            await self._handle_message(socket, raw)

    async def _handle_message(self, socket, raw):
        try:
            message = TwistInput.model_validate(raw)
            if not message.deadman:
                await self._deadman_release(socket, message.sequence)
                return
            self._validate_state(message)
            if self.station.state.value == "RUNNING":
                await self._send_twist(message)
            else:
                await socket.send_json(
                    {
                        "type": "ack",
                        "accepted": True,
                        "sequence": message.sequence,
                        "status": "armed",
                    }
                )
        except (ValidationError, ValueError, RuntimeError) as exc:
            await socket.send_json({"type": "ack", "accepted": False, "reason": str(exc)})

    async def _deadman_release(self, socket, sequence):
        if (
            self.station.state.value not in {"ARMED", "RUNNING"}
            or self.station.control_source.value != "teleop"
        ):
            raise RuntimeError("manual teleop is not the active control source")
        if sequence <= self.last_sequence:
            raise ValueError("teleop sequence is stale")
        self.deadman_active = False
        self.last_sequence = sequence
        self.last_message_at = time.monotonic()
        generation = self.station.control_generation + int(self.station.state.value == "RUNNING")
        await self.gateway.command(
            "stop", {"reason": "teleop deadman released", "generation": generation}
        )
        if self.station.state.value == "RUNNING":
            self.station.pause(uuid4(), "teleop deadman released")
        await socket.send_json(
            {"type": "ack", "accepted": True, "sequence": sequence, "status": "paused"}
        )

    async def _watchdog(self):
        while self.active_socket is not None:
            age_ms = (time.monotonic() - self.last_message_at) * 1000 if self.last_message_at else 0
            if self.last_message_at and age_ms > self.settings.teleop_deadman_timeout_ms:
                await self.release("teleop heartbeat expired")
                if self.station.state.value == "RUNNING":
                    self.station.pause(uuid4(), "teleop heartbeat expired")
                return
            await asyncio.sleep(self.settings.teleop_deadman_timeout_ms / 3000)

    def _validate_state(self, message):
        now = time.monotonic()
        if (
            self.station.state.value not in {"ARMED", "RUNNING"}
            or self.station.control_source.value != "teleop"
        ):
            raise RuntimeError("manual teleop is not the active control source")
        if message.control_generation != self.station.control_generation:
            raise ValueError("stale control generation")
        if message.arm != self.station.selected_arm or message.arm not in {"left", "right"}:
            raise ValueError("arm does not match the active selection")
        if message.sequence <= self.last_sequence:
            raise ValueError("teleop sequence is stale")
        if now - self.last_message_at < 1.0 / self.settings.teleop_max_hz:
            raise ValueError("teleop frequency limit exceeded")
        if not message.deadman:
            raise RuntimeError("deadman released")
        self.last_sequence = message.sequence
        self.last_message_at = now
        self.deadman_active = True

    async def _send_twist(self, message):
        began = time.monotonic()
        linear = [
            self._clamp(value, self.settings.teleop_linear_limit_m_s) for value in message.linear
        ]
        angular = [
            self._clamp(value, self.settings.teleop_angular_limit_rad_s)
            for value in message.angular
        ]
        await self.gateway.command(
            "teleop", {"arm": message.arm, "linear": linear, "angular": angular}
        )
        duration_ms = (time.monotonic() - began) * 1000
        metric = {
            "control_source": "teleop",
            "stage": "input_to_ros",
            "duration_ms": duration_ms,
            "sequence": message.sequence,
            "operation_id": self.station.operation_id,
        }
        self.metrics.record(metric)
        action = {
            **metric,
            "arm": message.arm,
            "sequence": message.sequence,
            "result": "accepted",
            "proposed": {"linear": message.linear, "angular": message.angular},
            "applied": {"linear": linear, "angular": angular},
        }
        self.events.publish("action", action)
        if self.event_writer:
            self.event_writer.submit("metric", metric)
            self.event_writer.submit("action", action)
        if self.active_socket is not None:
            await self.active_socket.send_json(
                {"type": "ack", "sequence": message.sequence, "accepted": True}
            )

    async def release(self, reason):
        if self.active_socket is None:
            return
        try:
            generation = self.station.control_generation + int(
                self.station.state.value == "RUNNING" and self.station.control_source.value == "teleop"
            )
            await self.gateway.command("stop", {"reason": reason, "generation": generation})
        except Exception:
            pass
        self.active_socket = None
        self.deadman_active = False
        if self.station.state.value == "RUNNING" and self.station.control_source.value == "teleop":
            self.station.pause(uuid4(), reason)

    @staticmethod
    def _clamp(value, limit):
        return max(-limit, min(limit, value))
