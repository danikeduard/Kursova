"""Remove per-user language and LLM provider/model settings."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_server_configured_llm"
down_revision = "20261112_llm_metric_details"
branch_labels = None
depends_on = None


REMOVED_COLUMNS = ("provider", "model", "ui_language")


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "app_user_settings" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("app_user_settings")}
    columns = [name for name in REMOVED_COLUMNS if name in existing]
    if columns:
        with op.batch_alter_table("app_user_settings") as batch_op:
            for name in columns:
                batch_op.drop_column(name)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "app_user_settings" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("app_user_settings")}
    columns = [name for name in REMOVED_COLUMNS if name not in existing]
    if columns:
        with op.batch_alter_table("app_user_settings") as batch_op:
            for name in columns:
                column_type = sa.String(2) if name == "ui_language" else sa.String(120 if name == "model" else 30)
                batch_op.add_column(sa.Column(name, column_type, nullable=True))
