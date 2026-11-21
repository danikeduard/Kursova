"""Bug report model kept separate from the feedback model."""

from datetime import UTC, datetime
from sqlalchemy import CheckConstraint

from .extensions import db


def utcnow() -> datetime:
    return datetime.now(UTC)


class BugReport(db.Model):
    __tablename__ = "app_bug_report"
    __table_args__ = (
        db.Index("ix_app_bug_report_status_created", "status", "created_at"),
        CheckConstraint("status IN ('new', 'in_progress', 'resolved', 'wont_fix')", name="ck_app_bug_report_status"),
        CheckConstraint("category IN ('Something is broken', 'Wrong level or rating', 'Confusing or hard to use', 'Idea or suggestion', 'Other')", name="ck_app_bug_report_category"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)
    category = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(120), nullable=True)
    description = db.Column(db.Text, nullable=False)
    context = db.Column(db.JSON, nullable=False, default=dict)
    status = db.Column(db.String(20), nullable=False, default="new")
    admin_note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
