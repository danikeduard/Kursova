"""Database models for users, tutoring interactions, and research data."""

from datetime import UTC, datetime

from flask_login import UserMixin
from werkzeug.security import generate_password_hash

from .extensions import db


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(UserMixin, db.Model):
    __tablename__ = "app_user"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(320), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    self_level = db.Column(db.String(2), nullable=False)
    daily_cap_override = db.Column(db.Integer, nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    @property
    def daily_cap(self) -> int:
        from flask import current_app

        return self.daily_cap_override or current_app.config["DAILY_MESSAGE_CAP"]


class Conversation(db.Model):
    __tablename__ = "app_conversation"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False, default="New chat")
    title_auto = db.Column(db.Boolean, nullable=False, default=True)
    pinned = db.Column(db.Boolean, nullable=False, default=False)
    archived = db.Column(db.Boolean, nullable=False, default=False)
    folder = db.Column(db.String(80), nullable=True)
    tags = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class UserSettings(db.Model):
    __tablename__ = "app_user_settings"

    user_id = db.Column(db.Integer, db.ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    reply_length = db.Column(db.String(20), nullable=False, default="balanced")
    use_emojis = db.Column(db.Boolean, nullable=False, default=True)
    theme = db.Column(db.String(10), nullable=False, default="dark")
    preferred_name = db.Column(db.String(40), nullable=False, default="")
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class SkillRating(db.Model):
    __tablename__ = "app_skill_rating"

    user_id = db.Column(db.Integer, db.ForeignKey("app_user.id"), primary_key=True)
    skill = db.Column(db.String(20), primary_key=True)
    rating = db.Column(db.Float, nullable=False)
    display_level = db.Column(db.String(2), nullable=True)
    variance = db.Column(db.Float, nullable=False, default=390625.0)
    last_outlier_sign = db.Column(db.SmallInteger, nullable=False, default=0)
    n_updates = db.Column(db.Integer, default=0, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class TopicMastery(db.Model):
    __tablename__ = "app_topic_mastery"

    user_id = db.Column(db.Integer, db.ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    topic = db.Column(db.String(80), primary_key=True)
    mastery = db.Column(db.Float, nullable=False, default=0.5)
    uncertainty = db.Column(db.Float, nullable=False, default=1.0)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    errors = db.Column(db.Integer, nullable=False, default=0)
    last_seen_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class Message(db.Model):
    __tablename__ = "app_message"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("app_user.id"), nullable=False, index=True)
    conversation_id = db.Column(
        db.Integer, db.ForeignKey("app_conversation.id", ondelete="CASCADE"), nullable=True, index=True
    )
    role = db.Column(db.String(10), nullable=False)
    content = db.Column(db.Text, nullable=False)
    ts = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    is_valid_for_rating = db.Column(db.Boolean, default=False, nullable=False)
    msg_index = db.Column(db.Integer, nullable=True)


class MessageFeedback(db.Model):
    __tablename__ = "app_message_feedback"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = db.Column(db.Integer, db.ForeignKey("app_message.id", ondelete="CASCADE"), nullable=False, unique=True)
    rating = db.Column(db.String(10), nullable=False)
    comment = db.Column(db.String(1000), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class ChatTurn(db.Model):
    __tablename__ = "app_chat_turn"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("app_conversation.id", ondelete="CASCADE"), nullable=True)
    user_message_id = db.Column(db.Integer, db.ForeignKey("app_message.id", ondelete="CASCADE"), nullable=False)
    assistant_message_id = db.Column(db.Integer, db.ForeignKey("app_message.id", ondelete="SET NULL"), nullable=True)
    provider = db.Column(db.String(30), nullable=False)
    model = db.Column(db.String(120), nullable=False)
    learning_action = db.Column(db.String(40), nullable=True)
    target_skill = db.Column(db.String(20), nullable=True)
    target_topic = db.Column(db.String(80), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="running")
    evaluation_status = db.Column(db.String(20), nullable=False, default="pending")
    tutor_status = db.Column(db.String(20), nullable=False, default="pending")
    error = db.Column(db.String(500), nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)


class RatingEvent(db.Model):
    __tablename__ = "app_rating_event"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("app_user.id"), nullable=False, index=True)
    message_id = db.Column(
        db.Integer,
        db.ForeignKey("app_message.id", ondelete="SET NULL"),
        nullable=True,
    )
    msg_index = db.Column(db.Integer, nullable=False, index=True)
    skill = db.Column(db.String(20), nullable=False)
    rating_before = db.Column(db.Float, nullable=False)
    rating_after = db.Column(db.Float, nullable=False)
    observed_level = db.Column(db.String(2), nullable=False)
    display_level = db.Column(db.String(2), nullable=True)
    confidence = db.Column(db.Float, nullable=False)
    weight = db.Column(db.Float, nullable=False)
    mode = db.Column(db.String(20), nullable=False, default="baseline")
    word_count = db.Column(db.Integer, nullable=True)
    error_count = db.Column(db.Integer, nullable=True)
    r_llm = db.Column(db.Float, nullable=True)
    c_llm = db.Column(db.Float, nullable=True)
    c_eff = db.Column(db.Float, nullable=True)
    r_density = db.Column(db.Float, nullable=True)
    r_obs = db.Column(db.Float, nullable=True)
    gain = db.Column(db.Float, nullable=True)
    outlier_flag = db.Column(db.SmallInteger, nullable=False, default=0)
    skipped = db.Column(db.Boolean, nullable=False, default=False)
    ts = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class LevelChange(db.Model):
    __tablename__ = "app_level_change"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)
    skill = db.Column(db.String(20), nullable=False)
    label = db.Column(db.String(2), nullable=False)
    rating_before = db.Column(db.Float, nullable=False)
    rating_after = db.Column(db.Float, nullable=False)
    evidence = db.Column(db.JSON, nullable=False)
    explanation = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class ErrorLog(db.Model):
    __tablename__ = "app_error_log"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("app_user.id"), nullable=False, index=True)
    message_id = db.Column(
        db.Integer,
        db.ForeignKey("app_message.id", ondelete="SET NULL"),
        nullable=True,
    )
    topic = db.Column(db.String(80), nullable=False)
    error_type = db.Column(db.String(30), nullable=False)
    original = db.Column(db.Text, nullable=False)
    corrected = db.Column(db.Text, nullable=False)
    ts = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class ApiMetric(db.Model):
    __tablename__ = "app_api_metric"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("app_user.id"), nullable=True)
    kind = db.Column(db.String(20), nullable=False)
    latency_ms = db.Column(db.Float, nullable=False)
    tokens_in = db.Column(db.Integer, nullable=True)
    tokens_out = db.Column(db.Integer, nullable=True)
    est_cost_usd = db.Column(db.Float, nullable=True)
    provider = db.Column(db.String(30), nullable=True)
    model = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="success")
    retry_count = db.Column(db.Integer, nullable=False, default=0)
    fallback_used = db.Column(db.Boolean, nullable=False, default=False)
    reasoning_tokens = db.Column(db.Integer, nullable=True)
    ts = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class Feedback(db.Model):
    __tablename__ = "app_feedback"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("app_user.id"), nullable=False, index=True)
    sus_answers = db.Column(db.JSON, nullable=False)
    free_text = db.Column(db.Text, nullable=True)
    ts = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
