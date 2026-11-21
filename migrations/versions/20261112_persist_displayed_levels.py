"""Persist stable displayed CEFR labels for skill ratings and rating history."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_persist_displayed_levels"
down_revision = "20261112_server_configured_llm"
branch_labels = None
depends_on = None


def _backfill_level(column: str, table: str, rating_column: str) -> None:
    op.execute(
        sa.text(
            f"UPDATE {table} SET {column} = CASE "
            f"WHEN {rating_column} < 700 THEN 'A1' WHEN {rating_column} < 900 THEN 'A2' "
            f"WHEN {rating_column} < 1100 THEN 'B1' WHEN {rating_column} < 1300 THEN 'B2' "
            f"WHEN {rating_column} < 1500 THEN 'C1' ELSE 'C2' END"
        )
    )


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "app_chat_turn" in tables:
        columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("app_chat_turn")}
        with op.batch_alter_table("app_chat_turn") as batch:
            for name, length in (("learning_action", 40), ("target_skill", 20), ("target_topic", 80)):
                if name not in columns:
                    batch.add_column(sa.Column(name, sa.String(length), nullable=True))
    for table, rating_column in (("app_skill_rating", "rating"), ("app_rating_event", "rating_after")):
        if table not in tables:
            continue
        columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
        if "display_level" not in columns:
            op.add_column(table, sa.Column("display_level", sa.String(2), nullable=True))
        _backfill_level("display_level", table, rating_column)


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "app_chat_turn" in tables:
        columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("app_chat_turn")}
        with op.batch_alter_table("app_chat_turn") as batch:
            for name in ("target_topic", "target_skill", "learning_action"):
                if name in columns:
                    batch.drop_column(name)
    for table in ("app_rating_event", "app_skill_rating"):
        if table in tables:
            columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
            if "display_level" in columns:
                with op.batch_alter_table(table) as batch:
                    batch.drop_column("display_level")
