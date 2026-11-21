"""Store the valid message number on each rating event."""

import sqlalchemy as sa
from alembic import op

revision = "0004_rating_event_message_index"
down_revision = "0003_telemetry_and_turns"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("app_rating_event", sa.Column("msg_index", sa.Integer(), nullable=True))
    op.create_index("ix_app_rating_event_msg_index", "app_rating_event", ["msg_index"])


def downgrade():
    op.drop_index("ix_app_rating_event_msg_index", table_name="app_rating_event")
    op.drop_column("app_rating_event", "msg_index")
