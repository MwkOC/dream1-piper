from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, func, select

from dream1_piper.adapters.postgres.models import (
    ActionRecord,
    Operation,
    PolicyInvocation,
    StageMetric,
    SystemEvent,
    Task,
)


class StationRepository:
    """Persistence queries for the operator API."""

    def __init__(self, database):
        self.database = database

    async def list_tasks(self):
        async with self.database.sessions() as session:
            rows = await session.scalars(select(Task).order_by(Task.updated_at.desc()))
            return [self._task(row) for row in rows]

    async def get_task(self, task_id):
        async with self.database.sessions() as session:
            item = await session.get(Task, task_id)
            return self._task(item) if item else None

    async def create_task(self, name, prompt):
        now = datetime.now(UTC)
        item = Task(task_id=uuid4(), name=name, prompt=prompt, created_at=now, updated_at=now)
        async with self.database.sessions() as session:
            session.add(item)
            await session.commit()
            return self._task(item)

    async def update_task(self, task_id, name, prompt):
        async with self.database.sessions() as session:
            item = await session.get(Task, task_id)
            if item is None:
                return None
            item.name, item.prompt, item.updated_at = name, prompt, datetime.now(UTC)
            await session.commit()
            return self._task(item)

    async def delete_task(self, task_id):
        async with self.database.sessions() as session:
            item = await session.get(Task, task_id)
            if item is None:
                return False
            await session.delete(item)
            await session.commit()
            return True

    async def list_operations(self, limit, offset):
        async with self.database.sessions() as session:
            query = (
                select(Operation).order_by(Operation.started_at.desc()).limit(limit).offset(offset)
            )
            rows = await session.scalars(query)
            return [self._operation(row) for row in rows]

    async def list_events(self, limit, offset):
        async with self.database.sessions() as session:
            total = await session.scalar(select(func.count()).select_from(SystemEvent))
            query = (
                select(SystemEvent)
                .order_by(SystemEvent.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            rows = await session.scalars(query)
            return {
                "items": [self._event(row) for row in rows],
                "total": int(total or 0),
                "limit": limit,
                "offset": offset,
            }

    async def operation_detail(self, operation_id):
        async with self.database.sessions() as session:
            operation = await session.get(Operation, operation_id)
            if operation is None:
                return None
            result = self._operation(operation)
            result["actions"] = await self._rows(session, ActionRecord, operation_id)
            result["invocations"] = await self._rows(session, PolicyInvocation, operation_id)
            result["metrics"] = await self._rows(session, StageMetric, operation_id)
            result["events"] = await self._rows(session, SystemEvent, operation_id)
            return result

    async def purge_all(self):
        tables = (ActionRecord, PolicyInvocation, StageMetric, SystemEvent, Operation, Task)
        async with self.database.sessions() as session:
            for model in tables:
                await session.execute(delete(model))
            await session.commit()

    @staticmethod
    async def _rows(session, model, operation_id):
        order_column = getattr(model, "created_at", getattr(model, "started_at", None))
        query = select(model).where(model.operation_id == operation_id)
        if order_column is not None:
            query = query.order_by(order_column)
        rows = await session.scalars(query)
        return [StationRepository._json_row(row) for row in rows]

    @staticmethod
    def _task(item):
        return {
            "task_id": item.task_id,
            "name": item.name,
            "prompt": item.prompt,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "enabled": item.enabled,
        }

    @staticmethod
    def _operation(item):
        return {
            "operation_id": item.operation_id,
            "task_id": item.task_id,
            "task_snapshot": item.task_snapshot,
            "control_source": item.control_source,
            "selected_arm": item.selected_arm,
            "started_at": item.started_at,
            "ended_at": item.ended_at,
            "result": item.result,
        }

    @staticmethod
    def _event(item):
        return {
            "event_id": item.event_id,
            "type": item.event_type,
            "data": item.data,
            "received_at": item.created_at,
        }

    @staticmethod
    def _json_row(item):
        return {column.name: getattr(item, column.name) for column in item.__table__.columns}
