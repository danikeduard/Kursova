"""Seed the documented demo accounts for new and upgraded databases."""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from werkzeug.security import generate_password_hash

revision = "20261121_seed_demo_users"
down_revision = "20261121_feedback_revision_fix"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "app_user" not in tables or "app_skill_rating" not in tables:
        return

    user_table = sa.table(
        "app_user",
        sa.column("id", sa.Integer()),
        sa.column("email", sa.String()),
        sa.column("password_hash", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("self_level", sa.String()),
        sa.column("daily_cap_override", sa.Integer()),
        sa.column("is_admin", sa.Boolean()),
    )

    now = datetime.now(UTC)
    for login, password, is_admin in (
        ("admin", "admin", True),
        ("user", "user", False),
    ):
        existing = bind.execute(
            sa.select(user_table.c.id).where(user_table.c.email == login)
        ).first()
        if existing is None:
            bind.execute(
                user_table.insert().values(
                    email=login,
                    password_hash=generate_password_hash(password),
                    created_at=now,
                    self_level="B1",
                    daily_cap_override=None,
                    is_admin=is_admin,
                )
            )
            created = bind.execute(
                sa.select(user_table.c.id).where(user_table.c.email == login)
            ).first()
            if created is None:
                continue
            user_id = created.id
        else:
            user_id = existing.id
            if is_admin:
                bind.execute(
                    user_table.update()
                    .where(user_table.c.id == user_id)
                    .values(is_admin=True)
                )

        rating_columns = {
            column["name"]
            for column in sa.inspect(bind).get_columns("app_skill_rating")
        }
        rating_values = {
            "user_id": user_id,
            "rating": 2500.0,
            "variance": 390625.0,
            "last_outlier_sign": 0,
        }
        if "n_updates" in rating_columns:
            rating_values["n_updates"] = 0
        if "updated_at" in rating_columns:
            rating_values["updated_at"] = now
        if "display_level" in rating_columns:
            rating_values["display_level"] = "B1"

        rating_table = sa.table(
            "app_skill_rating",
            *[sa.column(name) for name in rating_values],
            sa.column("skill", sa.String()),
        )
        for skill in ("grammar", "vocab", "writing"):
            existing_rating = bind.execute(
                sa.select(rating_table.c.skill).where(
                    sa.and_(
                        rating_table.c.user_id == user_id,
                        rating_table.c.skill == skill,
                    )
                )
            ).first()
            if existing_rating is None:
                bind.execute(
                    rating_table.insert().values(skill=skill, **rating_values)
                )


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "app_user" not in tables:
        return

    user_table = sa.table(
        "app_user",
        sa.column("id", sa.Integer()),
        sa.column("email", sa.String()),
    )
    user_ids = bind.execute(
        sa.select(user_table.c.id).where(user_table.c.email.in_(("admin", "user")))
    ).scalars()
    for user_id in list(user_ids):
        bind.execute(
            sa.text("DELETE FROM app_skill_rating WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
    bind.execute(
        user_table.delete().where(user_table.c.email.in_(("admin", "user")))
    )
