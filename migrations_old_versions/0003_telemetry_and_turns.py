"""Add provider telemetry, topic mastery, and chat turn audit."""

import sqlalchemy as sa
from alembic import op

revision = "0003_telemetry_and_turns"
down_revision = "0002_adaptive_rating"
branch_labels = None
depends_on = None


def upgrade():
    for name, column in (
        ("provider", sa.Column("provider", sa.String(30))),
        ("model", sa.Column("model", sa.String(120))),
        ("status", sa.Column("status", sa.String(20), nullable=False, server_default="success")),
        ("retry_count", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0")),
    ):
        op.add_column("app_api_metric", column)
    op.create_table(
        "app_topic_mastery",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("topic", sa.String(80), primary_key=True),
        sa.Column("mastery", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("uncertainty", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "app_chat_turn",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("app_conversation.id", ondelete="CASCADE")),
        sa.Column("user_message_id", sa.Integer(), sa.ForeignKey("app_message.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assistant_message_id", sa.Integer(), sa.ForeignKey("app_message.id", ondelete="SET NULL")),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("evaluation_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("tutor_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.String(500)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_app_chat_turn_user_id", "app_chat_turn", ["user_id"])


def downgrade():
    op.drop_index("ix_app_chat_turn_user_id", table_name="app_chat_turn")
    op.drop_table("app_chat_turn")
    op.drop_table("app_topic_mastery")
    for name in ("retry_count", "status", "model", "provider"):
        op.drop_column("app_api_metric", name)
