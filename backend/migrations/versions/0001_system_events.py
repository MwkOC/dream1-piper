"""Create event persistence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_system_events"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "operations",
        sa.Column("operation_id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("task_snapshot", sa.String(2000), nullable=False, server_default=""),
        sa.Column("control_source", sa.String(16), nullable=False),
        sa.Column("selected_arm", sa.String(8), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.String(24), nullable=True),
    )
    op.create_table(
        "policy_invocations",
        sa.Column("invocation_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "operation_id", sa.Uuid(), sa.ForeignKey("operations.operation_id"), nullable=False
        ),
        sa.Column("checkpoint", sa.String(200), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.String(24), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "actions",
        sa.Column("action_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "operation_id", sa.Uuid(), sa.ForeignKey("operations.operation_id"), nullable=False
        ),
        sa.Column(
            "invocation_id",
            sa.Uuid(),
            sa.ForeignKey("policy_invocations.invocation_id"),
            nullable=True,
        ),
        sa.Column("control_source", sa.String(16), nullable=False),
        sa.Column("arm", sa.String(8), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=True),
        sa.Column("result", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proposed", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("applied", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("feedback", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_actions_operation_time", "actions", ["operation_id", "created_at"])
    op.create_table(
        "stage_metrics",
        sa.Column("metric_id", sa.Uuid(), primary_key=True),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("control_source", sa.String(16), nullable=True),
        sa.Column("stage", sa.String(48), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_stage_metrics_operation_stage", "stage_metrics", ["operation_id", "stage", "created_at"]
    )
    op.create_table(
        "system_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("control_source", sa.String(16), nullable=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_system_events_operation_time", "system_events", ["operation_id", "created_at"]
    )


def downgrade():
    op.drop_index("ix_system_events_operation_time", table_name="system_events")
    op.drop_table("system_events")
    op.drop_index("ix_stage_metrics_operation_stage", table_name="stage_metrics")
    op.drop_table("stage_metrics")
    op.drop_index("ix_actions_operation_time", table_name="actions")
    op.drop_table("actions")
    op.drop_table("policy_invocations")
    op.drop_table("operations")
