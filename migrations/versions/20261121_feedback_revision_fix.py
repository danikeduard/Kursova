"""Add feedback revision and created_at columns when upgrading existing databases."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_feedback_revision_fix"
down_revision = "20261121_bug_reports"
branch_labels = None
depends_on = None

TABLE = "app_feedback"


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    with op.batch_alter_table(TABLE) as batch:
        if "revision" not in columns:
            batch.add_column(
                sa.Column(
                    "revision",
                    sa.Integer(),
                    nullable=False,
                    server_default=sa.text("1"),
                )
            )
        if "created_at" not in columns:
            batch.add_column(
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=True)
            )

    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if "created_at" in columns and "ts" in columns:
        op.execute(sa.text(
            f"UPDATE {TABLE} SET created_at = ts WHERE created_at IS NULL"
        ))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if "revision" in columns or "created_at" in columns:
        with op.batch_alter_table(TABLE) as batch:
            if "created_at" in columns:
                batch.drop_column("created_at")
            if "revision" in columns:
                batch.drop_column("revision")
