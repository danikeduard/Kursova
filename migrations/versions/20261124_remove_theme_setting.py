"""Remove the retired user theme preference."""

import sqlalchemy as sa
from alembic import op

revision = "20261124_remove_theme_setting"
down_revision = "20261121_feedback_revision_fix"
branch_labels = None
depends_on = None


TABLE = "app_user_settings"


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if "theme" in columns:
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_column("theme")


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if "theme" not in columns:
        with op.batch_alter_table(TABLE) as batch:
            batch.add_column(
                sa.Column("theme", sa.String(length=10), nullable=False, server_default="dark")
            )
        with op.batch_alter_table(TABLE) as batch:
            batch.alter_column("theme", server_default=None)
