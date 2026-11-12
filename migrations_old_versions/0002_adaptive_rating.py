"""Add adaptive rating state, replay fields, and level changes."""

import sqlalchemy as sa
from alembic import op

revision = "0002_adaptive_rating"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("app_skill_rating", sa.Column("variance", sa.Float(), nullable=False, server_default="62500"))
    op.add_column("app_skill_rating", sa.Column("last_outlier_sign", sa.SmallInteger(), nullable=False, server_default="0"))
    for name, column in (
        ("mode", sa.Column("mode", sa.String(20), nullable=False, server_default="baseline")),
        ("word_count", sa.Column("word_count", sa.Integer())),
        ("error_count", sa.Column("error_count", sa.Integer())),
        ("r_llm", sa.Column("r_llm", sa.Float())),
        ("c_llm", sa.Column("c_llm", sa.Float())),
        ("c_eff", sa.Column("c_eff", sa.Float())),
        ("r_density", sa.Column("r_density", sa.Float())),
        ("r_obs", sa.Column("r_obs", sa.Float())),
        ("gain", sa.Column("gain", sa.Float())),
        ("outlier_flag", sa.Column("outlier_flag", sa.SmallInteger(), nullable=False, server_default="0")),
        ("skipped", sa.Column("skipped", sa.Boolean(), nullable=False, server_default=sa.false())),
    ):
        op.add_column("app_rating_event", column)
    op.add_column("app_user_settings", sa.Column("ui_language", sa.String(2), nullable=False, server_default="uk"))
    op.create_table(
        "app_level_change",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill", sa.String(20), nullable=False),
        sa.Column("label", sa.String(2), nullable=False),
        sa.Column("rating_before", sa.Float(), nullable=False),
        sa.Column("rating_after", sa.Float(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_app_level_change_user_id", "app_level_change", ["user_id"])


def downgrade():
    op.drop_index("ix_app_level_change_user_id", table_name="app_level_change")
    op.drop_table("app_level_change")
    op.drop_column("app_user_settings", "ui_language")
    for name in ("skipped", "outlier_flag", "gain", "r_obs", "r_density", "c_eff", "c_llm", "r_llm", "error_count", "word_count", "mode"):
        op.drop_column("app_rating_event", name)
    op.drop_column("app_skill_rating", "last_outlier_sign")
    op.drop_column("app_skill_rating", "variance")
