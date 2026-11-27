"""Concurrent observation, inference and action-pacing lifecycle."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import replace
from typing import Any
from uuid import uuid4

from .control import PolicyAction, RobotSchema
from .metrics import RuntimeMetrics
from .protocol import action_message, parse_observation
from .settings import env_value
from .worker_helpers import retryable, validate_action


class WorkerRuntime:
    def __init__(self, websocket: Any, policy: Any, schema: RobotSchema, *, observe: bool):
        self.websocket, self.policy, self.schema, self.observe = websocket, policy, schema, observe
        window_size = int(env_value("RSTACK_DREAM_METRICS_WINDOW", 200))
        self.metrics = RuntimeMetrics(window_size=window_size)
        self.queue: deque[tuple[float, ...]] = deque()
        self.epoch: tuple[str, int, str] | None = None
        self.latest: Any | None = None
        self.source: tuple[int, int, int] | None = None
        self.sequence = self.executed = self.chunk_executed = 0
        self.last_emitted: tuple[float, ...] | None = None
        self.first_chunk = False
        self.started_at: float | None = None
        self.inference: asyncio.Task[Any] | None = None
        self.stopped = asyncio.Event()
        self.lock = asyncio.Lock()
        self.send_lock = asyncio.Lock()
        self.fatal: Exception | None = None
        self._window_started = time.perf_counter()
        self._previous_observations = self._previous_actions = 0
        self.current_invocation_id: str | None = None

    async def run(self) -> None:
        receiver = asyncio.create_task(self._receive(), name="dream-worker-receive")
        emitter = asyncio.create_task(self._emit(), name="dream-worker-emit")
        try:
            done, _ = await asyncio.wait({receiver, emitter}, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            await self._shutdown(receiver, emitter)

    async def _shutdown(self, receiver: asyncio.Task[Any], emitter: asyncio.Task[Any]) -> None:
        self.stopped.set()
        for task in (receiver, emitter, self.inference):
            if task is not None:
                task.cancel()
        tasks = [receiver, emitter] + ([self.inference] if self.inference is not None else [])
        await asyncio.gather(*tasks, return_exceptions=True)
        self.queue.clear()

    async def _send(self, message: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.websocket.send(json.dumps(message))

    async def _receive(self) -> None:
        while not self.stopped.is_set():
            tick = time.perf_counter()
            if self.observe:
                await self._send({"type": "observation_request"})
            message = json.loads(await self.websocket.recv())
            if await self._handle_control_message(message):
                continue
            await self._handle_observation(message)
            if self.observe:
                await asyncio.sleep(
                    max(0.0, 1 / self.schema.control_hz - (time.perf_counter() - tick))
                )

    async def _handle_control_message(self, message: dict[str, Any]) -> bool:
        kind = message.get("type")
        if kind == "error":
            raise RuntimeError(str(message.get("reason", "station observation failed")))
        if kind == "control_state":
            await self._handle_station_state(str(message.get("state", "unknown")))
            return True
        if kind == "rejected":
            reason = str(message.get("reason", "unspecified reason"))
            self.metrics.rejected(reason)
            self.queue.clear()
            self.fatal = RuntimeError(f"station rejected action: {reason}")
            return True
        return kind != "observation"

    async def _handle_station_state(self, state: str) -> None:
        if state == "running":
            return
        async with self.lock:
            self.queue.clear()
            self.epoch = self.latest = self.source = self.last_emitted = None
            self.started_at = None
            self.chunk_executed = self.executed = 0
            self.first_chunk = False
            self.metrics.queue_depth(0)

    async def _handle_observation(self, message: dict[str, Any]) -> None:
        observation = parse_observation(message)
        self.metrics.count("observations")
        task = str(message.get("task") or self.policy.config.task)
        candidate = (
            str(message.get("session_id") or "dry-run"),
            observation.control_generation,
            task,
        )
        async with self.lock:
            await self._reset_epoch(candidate, task)
            self.latest = observation
            self.policy.set_observation(observation)
            if self._should_refill():
                self.inference = asyncio.create_task(
                    self._produce(observation, self.executed), name="dream-inference"
                )

    async def _reset_epoch(self, candidate: tuple[str, int, str], task: str) -> None:
        if self.epoch == candidate:
            return
        self.epoch, self.started_at = candidate, time.perf_counter()
        self.queue.clear()
        self.source = self.last_emitted = None
        self.chunk_executed = self.executed = 0
        self.first_chunk = False
        await asyncio.to_thread(self.policy.reset_episode)
        self.policy.config = replace(self.policy.config, task=task)

    def _should_refill(self) -> bool:
        return (self.inference is None or self.inference.done()) and (
            not self.queue or self.policy.refill_due(self.chunk_executed, len(self.queue))
        )

    async def _produce(self, observation: Any, executed_at_request: int) -> None:
        token, began = self.epoch, time.perf_counter()
        invocation_id = str(uuid4())
        try:
            chunk = await asyncio.to_thread(self.policy.get_chunk, self.last_emitted)
            elapsed = time.perf_counter() - began
            if elapsed > self.policy.config.action_timeout_s:
                limit = self.policy.config.action_timeout_s
                raise TimeoutError(f"Dream chunk took {elapsed:.2f}s; limit is {limit:.2f}s")
            rows = [validate_action(self.schema, row) for row in chunk]
            await self._install_chunk(
                token, observation, rows, elapsed, executed_at_request, invocation_id
            )
            await self._send(
                {
                    "type": "invocation",
                    "invocation_id": invocation_id,
                    "checkpoint": self.policy.config.checkpoint,
                    "duration_ms": elapsed * 1000,
                    "result": "accepted",
                    "timing": self.policy.timing,
                }
            )
        except Exception as exc:
            await self._send(
                {
                    "type": "invocation",
                    "invocation_id": invocation_id,
                    "checkpoint": self.policy.config.checkpoint,
                    "duration_ms": (time.perf_counter() - began) * 1000,
                    "result": "rejected",
                    "error": str(exc),
                }
            )
            await self._handle_inference_error(exc, token)

    async def _install_chunk(
        self,
        token: Any,
        observation: Any,
        rows: list[tuple[float, ...]],
        elapsed: float,
        executed_at_request: int,
        invocation_id: str,
    ) -> None:
        async with self.lock:
            if self.epoch != token:
                return
            executed_during_request = max(0, self.executed - executed_at_request)
            skipped = min(executed_during_request, max(0, round(elapsed * self.schema.control_hz)))
            if skipped >= len(rows):
                raise TimeoutError("Dream chunk landed after its complete action horizon")
            self.queue.clear()
            self.queue.extend(rows[skipped:])
            self.current_invocation_id = invocation_id
            self.chunk_executed = 0
            self.source = (
                observation.observation_id,
                observation.station_monotonic_ns,
                observation.control_generation,
            )
            self.first_chunk = True
            self.metrics.inference(elapsed, self.policy.timing)
            await self._send(
                {
                    "type": "metric",
                    "stage": "dream_inference",
                    "duration_ms": elapsed * 1000,
                    "timing": self.policy.timing,
                }
            )
            self.metrics.queue_depth(len(self.queue))
            print(f"Dream chunk ready: rows={len(rows) - skipped} latency={elapsed:.2f}s")

    async def _handle_inference_error(self, exc: Exception, token: Any) -> None:
        if self.epoch != token:
            return
        self.metrics.error(str(exc))
        print(f"Dream inference failed ({type(exc).__name__}): {exc}")
        if not retryable(exc):
            self.queue.clear()
            self.fatal = exc
            return
        await asyncio.sleep(1.0)

    async def _emit(self) -> None:
        deadline = time.perf_counter()
        while not self.stopped.is_set():
            if self.fatal is not None:
                raise self.fatal
            deadline += 1 / self.schema.control_hz
            await self._emit_one()
            await self._send_metrics_if_due()
            await asyncio.sleep(max(0.0, deadline - time.perf_counter()))
            deadline = max(deadline, time.perf_counter())

    async def _emit_one(self) -> None:
        async with self.lock:
            if self.queue and self.epoch is not None and self.source is not None:
                values = self.queue.popleft()
                self.chunk_executed += 1
                self.executed += 1
                self.last_emitted = values
                self.metrics.count("actions_emitted")
                if not self.observe:
                    await self._send_action(values)
            elif self.latest is not None:
                self.metrics.count("underruns")
                self._check_first_chunk_deadline()

    async def _send_action(self, values: tuple[float, ...]) -> None:
        self.sequence += 1
        observation_id, timestamp, generation = self.source or (0, 0, 0)
        action = PolicyAction(
            self.epoch[0],
            self.sequence,
            observation_id,
            timestamp,
            self.schema.version,
            values,
            scheduled=True,
            control_generation=generation,
            invocation_id=self.current_invocation_id,
        )
        await self._send(action_message(action))

    def _check_first_chunk_deadline(self) -> None:
        if not self.first_chunk and self.started_at is not None:
            limit = self.policy.config.first_chunk_timeout_s
            if time.perf_counter() - self.started_at > limit:
                raise TimeoutError(f"Dream produced no first chunk within {limit:.0f}s")

    async def _send_metrics_if_due(self) -> None:
        now = time.perf_counter()
        if now - self._window_started < 1.0:
            return
        elapsed = now - self._window_started
        snapshot = self.metrics.snapshot()
        counts = snapshot["counts"]
        snapshot["observation_hz"] = (
            counts.get("observations", 0) - self._previous_observations
        ) / elapsed
        snapshot["action_hz"] = (
            counts.get("actions_emitted", 0) - self._previous_actions
        ) / elapsed
        snapshot.update(
            {
                "enabled": True,
                "dry_run": self.observe,
                "pacing_mode": self.policy.pacing_mode,
                "queue_depth": len(self.queue),
                "task": self.policy.config.task,
            }
        )
        await self._send({"type": "rtc_status", **snapshot})
        self._previous_observations = counts.get("observations", 0)
        self._previous_actions = counts.get("actions_emitted", 0)
        self._window_started = now
