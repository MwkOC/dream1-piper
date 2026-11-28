import asyncio
from collections import deque
from datetime import UTC, datetime
from itertools import islice
from uuid import UUID, uuid4


class MemoryStore:
    """Process-local collections shared by the memory repository and event writer."""

    def __init__(self, history_limit):
        self.history_limit = history_limit
        self.tasks = {}
        self.operations = deque(maxlen=history_limit)
        self.actions = deque(maxlen=history_limit)
        self.invocations = deque(maxlen=history_limit)
        self.metrics = deque(maxlen=history_limit)
        self.events = deque(maxlen=history_limit)
        self.evicted = 0

    def append(self, collection, item):
        if len(collection) == self.history_limit:
            self.evicted += 1
        collection.append(item)

    def clear(self):
        self.tasks.clear()
        for collection in self.history_collections():
            collection.clear()
        self.evicted = 0

    def history_collections(self):
        return (self.operations, self.actions, self.invocations, self.metrics, self.events)


class MemoryRepository:
    def __init__(self, store):
        self.store = store

    async def list_tasks(self):
        return sorted(self.store.tasks.values(), key=lambda row: row["updated_at"], reverse=True)

    async def get_task(self, task_id):
        return self.store.tasks.get(str(task_id))

    async def create_task(self, name, prompt):
        now = datetime.now(UTC)
        item = {
            "task_id": uuid4(),
            "name": name,
            "prompt": prompt,
            "created_at": now,
            "updated_at": now,
            "enabled": True,
        }
        self.store.tasks[str(item["task_id"])] = item
        return item

    async def update_task(self, task_id, name, prompt):
        item = await self.get_task(task_id)
        if item is None:
            return None
        item.update(name=name, prompt=prompt, updated_at=datetime.now(UTC))
        return item

    async def delete_task(self, task_id):
        return self.store.tasks.pop(str(task_id), None) is not None

    async def list_operations(self, limit, offset):
        rows = sorted(self.store.operations, key=lambda row: row["started_at"], reverse=True)
        return rows[offset : offset + limit]

    async def list_events(self, limit, offset):
        rows = list(islice(reversed(self.store.events), offset, offset + limit))
        return {
            "items": [
                {
                    "event_id": row["event_id"],
                    "type": row["event_type"],
                    "data": row["data"],
                    "received_at": row["created_at"],
                }
                for row in rows
            ],
            "total": len(rows),
            "limit": limit,
            "offset": offset,
        }

    async def operation_detail(self, operation_id):
        operation = next(
            (row for row in self.store.operations if str(row["operation_id"]) == str(operation_id)),
            None,
        )
        if operation is None:
            return None
        return self._operation_detail(operation)

    def _operation_detail(self, operation):
        result = dict(operation)
        for name in ("actions", "invocations", "metrics", "events"):
            collection = getattr(self.store, name)
            result[name] = [
                row
                for row in collection
                if str(row.get("operation_id")) == str(operation["operation_id"])
            ]
        return result

    async def purge_all(self):
        self.store.clear()


class MemoryEventWriter:
    def __init__(self, store, capacity):
        self.store = store
        self.queue = asyncio.Queue(capacity)
        self.queue_dropped = 0
        self.task = None

    @property
    def dropped(self):
        return self.queue_dropped + self.store.evicted

    @dropped.setter
    def dropped(self, value):
        self.queue_dropped = value
        if value == 0:
            self.store.evicted = 0

    def submit(self, event_type, data):
        try:
            self.queue.put_nowait((event_type, dict(data)))
        except asyncio.QueueFull:
            self.queue_dropped += 1

    async def start(self):
        self.task = asyncio.create_task(self._write_loop())

    async def close(self):
        if self.task is None:
            return
        try:
            await asyncio.wait_for(self.queue.join(), timeout=2.0)
        except TimeoutError:
            self.queue_dropped += self.queue.qsize()
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
                self._store_event(event_type, data)
            except Exception:
                self.queue_dropped += 1
            finally:
                self.queue.task_done()

    def _store_event(self, event_type, data):
        now = datetime.now(UTC)
        event = {
            "event_id": self._uuid(data.get("event_id")) or uuid4(),
            "operation_id": self._uuid(data.get("operation_id")),
            "control_source": data.get("control_source"),
            "event_type": event_type,
            "created_at": now,
            "duration_ms": data.get("duration_ms"),
            "data": data,
        }
        self.store.append(self.store.events, event)
        self._store_typed_event(event_type, data, now)

    def _store_typed_event(self, event_type, data, now):
        if event_type == "operation.started":
            self._store_operation(data, now)
        elif event_type == "operation.paused":
            self._finish_operation(data, now)
        elif event_type == "metric" and data.get("stage"):
            self._store_metric(data, now)
        elif event_type == "policy_invocation":
            self._store_invocation(data, now)
        elif event_type == "action":
            self._store_action(data, now)

    def _store_operation(self, data, now):
        operation_id = self._uuid(data.get("operation_id"))
        if operation_id is None:
            return
        operation = {
            "operation_id": operation_id,
            "task_id": self._uuid(data.get("task_id")),
            "task_snapshot": str(data.get("task", "")),
            "control_source": str(data.get("control_source", data.get("source", "dream"))),
            "selected_arm": data.get("selected_arm"),
            "started_at": now,
            "ended_at": None,
            "result": None,
        }
        self.store.append(self.store.operations, operation)

    def _finish_operation(self, data, now):
        operation_id = self._uuid(data.get("operation_id"))
        operation = self._find_operation(operation_id)
        if operation is not None:
            operation.update(ended_at=now, result="paused")

    def _store_metric(self, data, now):
        item = {
            "metric_id": uuid4(),
            "operation_id": self._uuid(data.get("operation_id")),
            "control_source": data.get("control_source"),
            "stage": str(data["stage"]),
            "created_at": now,
            "duration_ms": data.get("duration_ms"),
            "data": data,
        }
        self.store.append(self.store.metrics, item)

    def _store_invocation(self, data, now):
        operation_id = self._uuid(data.get("operation_id"))
        if operation_id is None:
            return
        item = {
            "invocation_id": self._uuid(data.get("invocation_id")) or uuid4(),
            "operation_id": operation_id,
            "checkpoint": str(data.get("checkpoint", "")),
            "started_at": now,
            "ended_at": now,
            "result": str(data.get("result", "unknown")),
            "data": data,
        }
        self.store.append(self.store.invocations, item)

    def _store_action(self, data, now):
        operation_id = self._uuid(data.get("operation_id"))
        if operation_id is None:
            return
        item = {
            "action_id": self._uuid(data.get("action_id")) or uuid4(),
            "operation_id": operation_id,
            "invocation_id": self._uuid(data.get("invocation_id")),
            "control_source": str(data.get("control_source", "dream")),
            "arm": data.get("arm"),
            "sequence": data.get("sequence"),
            "result": str(data.get("result", "accepted")),
            "created_at": now,
            "proposed": data.get("proposed", {}),
            "applied": data.get("applied", {}),
            "feedback": data.get("feedback", {}),
        }
        self.store.append(self.store.actions, item)

    def _find_operation(self, operation_id):
        return next(
            (row for row in self.store.operations if row["operation_id"] == operation_id),
            None,
        )

    @staticmethod
    def _uuid(value):
        try:
            return UUID(str(value)) if value else None
        except (TypeError, ValueError):
            return None
