"""Index event creation time for paginated station activity."""

from alembic import op

revision = "0003_events_created_at_index"
down_revision = "0002_tasks_library"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_system_events_created_at", "system_events", ["created_at"])


def downgrade():
    op.drop_index("ix_system_events_created_at", table_name="system_events")
