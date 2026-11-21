"""Keep rating events after their conversation is deleted."""

import sqlalchemy as sa
from alembic import op

revision = "0005_preserve_rating_events_on_chat_delete"
down_revision = "0004_rating_event_message_index"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("app_rating_event_message_id_fkey", "app_rating_event", type_="foreignkey")
    op.alter_column("app_rating_event", "message_id", existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key(
        "app_rating_event_message_id_fkey",
        "app_rating_event",
        "app_message",
        ["message_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("app_rating_event_message_id_fkey", "app_rating_event", type_="foreignkey")
    op.alter_column("app_rating_event", "message_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(
        "app_rating_event_message_id_fkey",
        "app_rating_event",
        "app_message",
        ["message_id"],
        ["id"],
    )
