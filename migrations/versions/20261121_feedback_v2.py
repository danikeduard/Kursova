"""Add versioned five-question feedback and admin review metadata."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_feedback_v2"
down_revision = "20261112_expand_rating_scale"
branch_labels = None
depends_on = None

TABLE = "app_feedback"
UNIQUE_NAME = "uq_app_feedback_user_id"
STATUS_CHECK = "ck_app_feedback_admin_status"
NEW_COLUMNS = {
    "answers": sa.Column("answers", sa.JSON(), nullable=True),
    "schema_version": sa.Column("schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    "revision": sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
    "created_at": sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    "context": sa.Column("context", sa.JSON(), nullable=True),
    "consent_research": sa.Column(
        "consent_research", sa.Boolean(), nullable=False, server_default=sa.false()
    ),
    "admin_status": sa.Column("admin_status", sa.String(length=10), nullable=False, server_default="new"),
    "updated_at": sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
}


def _inspector():
    return sa.inspect(op.get_bind())


def _deduplicate_users() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(f"SELECT id, user_id FROM {TABLE} ORDER BY user_id, ts DESC, id DESC")
    ).all()
    seen_users = set()
    duplicate_ids = []
    for row in rows:
        if row.user_id in seen_users:
            duplicate_ids.append(row.id)
        else:
            seen_users.add(row.user_id)

    if duplicate_ids:
        feedback = sa.table(TABLE, sa.column("id", sa.Integer()))
        for offset in range(0, len(duplicate_ids), 500):
            bind.execute(
                sa.delete(feedback).where(feedback.c.id.in_(duplicate_ids[offset:offset + 500]))
            )


def _has_user_unique(inspector) -> bool:
    if any(
        set(constraint.get("column_names") or ()) == {"user_id"}
        for constraint in inspector.get_unique_constraints(TABLE)
    ):
        return True
    return any(
        index.get("unique") and set(index.get("column_names") or ()) == {"user_id"}
        for index in inspector.get_indexes(TABLE)
    )


def upgrade():
    inspector = _inspector()
    if TABLE not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns(TABLE)}
    missing = [column.copy() for name, column in NEW_COLUMNS.items() if name not in existing]
    if missing:
        with op.batch_alter_table(TABLE) as batch:
            for column in missing:
                batch.add_column(column)

    columns = {column["name"]: column for column in _inspector().get_columns(TABLE)}
    if "updated_at" in columns:
        if "ts" in columns:
            op.execute(sa.text(f"UPDATE {TABLE} SET updated_at = ts WHERE updated_at IS NULL"))
        else:
            op.execute(
                sa.text(f"UPDATE {TABLE} SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
            )
    if "created_at" in {column["name"] for column in _inspector().get_columns(TABLE)}:
        if "ts" in {column["name"] for column in _inspector().get_columns(TABLE)}:
            op.execute(sa.text(f"UPDATE {TABLE} SET created_at = ts WHERE created_at IS NULL"))

    _deduplicate_users()

    legacy_answers = columns.get("sus_answers")
    if legacy_answers and not legacy_answers.get("nullable", True):
        with op.batch_alter_table(TABLE) as batch:
            batch.alter_column(
                "sus_answers",
                existing_type=sa.JSON(),
                nullable=True,
            )

    updated_at = columns.get("updated_at")
    if updated_at and updated_at.get("nullable", True):
        with op.batch_alter_table(TABLE) as batch:
            batch.alter_column(
                "updated_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )

    inspector = _inspector()
    if not _has_user_unique(inspector):
        with op.batch_alter_table(TABLE) as batch:
            batch.create_unique_constraint(UNIQUE_NAME, ["user_id"])

    check_names = {
        constraint.get("name") for constraint in _inspector().get_check_constraints(TABLE)
    }
    if STATUS_CHECK not in check_names:
        with op.batch_alter_table(TABLE) as batch:
            batch.create_check_constraint(
                STATUS_CHECK,
                "admin_status IN ('new', 'read', 'archived')",
            )


def downgrade():
    inspector = _inspector()
    if TABLE not in inspector.get_table_names():
        return

    check_names = {
        constraint.get("name") for constraint in inspector.get_check_constraints(TABLE)
    }
    unique_names = {
        constraint.get("name") for constraint in inspector.get_unique_constraints(TABLE)
    }
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    drop_columns = [name for name in reversed(tuple(NEW_COLUMNS)) if name in columns]
    legacy_answers = next(
        (column for column in inspector.get_columns(TABLE) if column["name"] == "sus_answers"),
        None,
    )
    if legacy_answers and legacy_answers.get("nullable"):
        feedback = sa.table(TABLE, sa.column("sus_answers", sa.JSON()))
        op.get_bind().execute(
            sa.update(feedback)
            .where(feedback.c.sus_answers.is_(None))
            .values(sus_answers=[])
        )

    if STATUS_CHECK in check_names or UNIQUE_NAME in unique_names or drop_columns or (
        legacy_answers and legacy_answers.get("nullable")
    ):
        with op.batch_alter_table(TABLE) as batch:
            if STATUS_CHECK in check_names:
                batch.drop_constraint(STATUS_CHECK, type_="check")
            if UNIQUE_NAME in unique_names:
                batch.drop_constraint(UNIQUE_NAME, type_="unique")
            if legacy_answers and legacy_answers.get("nullable"):
                batch.alter_column(
                    "sus_answers",
                    existing_type=sa.JSON(),
                    nullable=False,
                )
            for name in drop_columns:
                batch.drop_column(name)
