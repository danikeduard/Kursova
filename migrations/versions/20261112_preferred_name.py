"""Add the user's preferred form of address."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_preferred_name"
down_revision = "20261112_persist_displayed_levels"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "app_user_settings" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("app_user_settings")}
    if "preferred_name" not in existing:
        with op.batch_alter_table("app_user_settings") as batch_op:
            batch_op.add_column(sa.Column("preferred_name", sa.String(40), nullable=False, server_default=""))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "app_user_settings" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("app_user_settings")}
    if "preferred_name" in existing:
        with op.batch_alter_table("app_user_settings") as batch_op:
            batch_op.drop_column("preferred_name")
