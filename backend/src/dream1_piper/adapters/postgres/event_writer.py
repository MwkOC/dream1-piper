import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from dream1_piper.adapters.postgres.models import (
    ActionRecord,
    Operation,
    PolicyInvocation,
    StageMetric,
    SystemEvent,
)


class EventWriter:
    def __init__(self, database, capacity):
        self.database = database
        self.queue = asyncio.Queue(capacity)
        self.dropped = 0
        self.task = None

    def submit(self, event_type, data):
        try:
            self.queue.put_nowait((event_type, data))
        except asyncio.QueueFull:
            self.dropped += 1

    async def start(self):
        self.task = asyncio.create_task(self._write_loop())

    async def close(self):
        if self.task is None:
            return
        try:
            await asyncio.wait_for(self.queue.join(), timeout=2.0)
        except TimeoutError:
            self.dropped += self.queue.qsize()
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass

    async def flush(self):
        if self.task is not None:
            await asyncio.wait_for(self.queue.join(), timeout=3.0)

    async def _write_loop(self):
        while True:
            event_type, data = await self.queue.get()
            try:
                await self._store(event_type, data)
            finally:
                self.queue.task_done()

    async def _store(self, event_type, data):
        item = SystemEvent(
            event_id=uuid4(),
            operation_id=self._uuid(data.get("operation_id")),
            control_source=data.get("control_source"),
            event_type=event_type,
            created_at=datetime.now(UTC),
            data=data,
        )
        try:
            async with self.database.sessions() as session:
                session.add(item)
                await self._write_typed_event(session, event_type, data)
                await session.commit()
        except Exception:
            self.dropped += 1

    async def _write_typed_event(self, session, event_type, data):
        if event_type == "operation.started":
            await self._write_operation_started(session, data)
        elif event_type == "operation.paused":
            await self._write_operation_paused(session, data)
        elif event_type == "metric":
            self._write_metric(session, data)
        elif event_type == "policy_invocation":
            self._write_invocation(session, data)
        elif event_type == "action":
            self._write_action(session, data)

    async def _write_operation_started(self, session, data):
        operation_id = self._uuid(data.get("operation_id"))
        if operation_id:
            session.add(
                Operation(
                    operation_id=operation_id,
                    task_id=self._uuid(data.get("task_id")),
                    task_snapshot=str(data.get("task", "")),
                    control_source=str(data.get("control_source", data.get("source", "dream"))),
                    selected_arm=data.get("selected_arm"),
                    started_at=datetime.now(UTC),
                )
            )

    async def _write_operation_paused(self, session, data):
        operation_id = self._uuid(data.get("operation_id"))
        if operation_id:
            operation = await session.get(Operation, operation_id)
            if operation:
                operation.ended_at = datetime.now(UTC)
                operation.result = "paused"

    def _write_metric(self, session, data):
        if not data.get("stage"):
            return
        session.add(
            StageMetric(
                metric_id=uuid4(),
                operation_id=self._uuid(data.get("operation_id")),
                control_source=data.get("control_source"),
                stage=str(data["stage"]),
                created_at=datetime.now(UTC),
                duration_ms=data.get("duration_ms"),
                data=data,
            )
        )

    def _write_invocation(self, session, data):
        operation_id = self._uuid(data.get("operation_id"))
        if not operation_id:
            return
        now = datetime.now(UTC)
        session.add(
            PolicyInvocation(
                invocation_id=self._uuid(data.get("invocation_id")) or uuid4(),
                operation_id=operation_id,
                checkpoint=str(data.get("checkpoint", "")),
                started_at=now,
                ended_at=now,
                result=str(data.get("result", "unknown")),
                data=data,
            )
        )

    def _write_action(self, session, data):
        operation_id = self._uuid(data.get("operation_id"))
        if not operation_id:
            return
        session.add(
            ActionRecord(
                action_id=self._uuid(data.get("action_id")) or uuid4(),
                operation_id=operation_id,
                invocation_id=self._uuid(data.get("invocation_id")),
                control_source=str(data.get("control_source", "dream")),
                arm=data.get("arm"),
                sequence=data.get("sequence"),
                result=str(data.get("result", "accepted")),
                created_at=datetime.now(UTC),
                proposed=data.get("proposed", {}),
                applied=data.get("applied", {}),
                feedback=data.get("feedback", {}),
            )
        )

    @staticmethod
    def _uuid(value):
        try:
            return UUID(str(value)) if value else None
        except ValueError:
            return None
