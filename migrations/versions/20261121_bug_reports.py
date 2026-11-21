"""Create bug reports and feedback revision metadata."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_bug_reports"
down_revision = "20261121_feedback_v2"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "app_bug_report" not in inspector.get_table_names():
        op.create_table(
            "app_bug_report",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("category", sa.String(length=40), nullable=False),
            sa.Column("title", sa.String(length=120), nullable=True),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("context", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
            sa.Column("admin_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )
        with op.batch_alter_table("app_bug_report") as batch:
            batch.create_index("ix_app_bug_report_user_id", ["user_id"], unique=False)
            batch.create_index("ix_app_bug_report_status_created", ["status", "created_at"], unique=False)
        with op.batch_alter_table("app_bug_report") as batch:
            batch.create_check_constraint(
                "ck_app_bug_report_status",
                "status IN ('new', 'in_progress', 'resolved', 'wont_fix')",
            )
            batch.create_check_constraint(
                "ck_app_bug_report_category",
                "category IN ('Something is broken', 'Wrong level or rating', 'Confusing or hard to use', 'Idea or suggestion', 'Other')",
            )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "app_bug_report" in inspector.get_table_names():
        op.drop_table("app_bug_report")
