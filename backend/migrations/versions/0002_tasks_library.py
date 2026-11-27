"""Add the reusable task library."""

import sqlalchemy as sa
from alembic import op

revision = "0002_tasks_library"
down_revision = "0001_system_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("prompt", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_tasks_updated_at", "tasks", ["updated_at"])


def downgrade():
    op.drop_index("ix_tasks_updated_at", table_name="tasks")
    op.drop_table("tasks")
