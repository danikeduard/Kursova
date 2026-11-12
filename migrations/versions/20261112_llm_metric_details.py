"""Add fallback and reasoning telemetry to API metrics."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_llm_metric_details"
down_revision = "d8a9a1a06a3b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("app_api_metric") as batch_op:
        batch_op.add_column(sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("reasoning_tokens", sa.Integer(), nullable=True))
    with op.batch_alter_table("app_api_metric") as batch_op:
        batch_op.alter_column("fallback_used", server_default=None)


def downgrade():
    with op.batch_alter_table("app_api_metric") as batch_op:
        batch_op.drop_column("reasoning_tokens")
        batch_op.drop_column("fallback_used")
