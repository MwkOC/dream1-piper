from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_updated_at", "updated_at"),)

    task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Operation(Base):
    __tablename__ = "operations"

    operation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    task_snapshot: Mapped[str] = mapped_column(String(2000), default="")
    control_source: Mapped[str] = mapped_column(String(16))
    selected_arm: Mapped[str | None] = mapped_column(String(8), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(String(24), nullable=True)


class PolicyInvocation(Base):
    __tablename__ = "policy_invocations"

    invocation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    operation_id: Mapped[UUID] = mapped_column(ForeignKey("operations.operation_id"))
    checkpoint: Mapped[str] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str] = mapped_column(String(24))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ActionRecord(Base):
    __tablename__ = "actions"
    __table_args__ = (Index("ix_actions_operation_time", "operation_id", "created_at"),)

    action_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    operation_id: Mapped[UUID] = mapped_column(ForeignKey("operations.operation_id"))
    invocation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policy_invocations.invocation_id"), nullable=True
    )
    control_source: Mapped[str] = mapped_column(String(16))
    arm: Mapped[str | None] = mapped_column(String(8), nullable=True)
    sequence: Mapped[int | None] = mapped_column(nullable=True)
    result: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    proposed: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    applied: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    feedback: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class StageMetric(Base):
    __tablename__ = "stage_metrics"
    __table_args__ = (
        Index("ix_stage_metrics_operation_stage", "operation_id", "stage", "created_at"),
    )

    metric_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    operation_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    control_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    stage: Mapped[str] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class SystemEvent(Base):
    __tablename__ = "system_events"
    __table_args__ = (Index("ix_system_events_operation_time", "operation_id", "created_at"),)

    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    operation_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    control_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
