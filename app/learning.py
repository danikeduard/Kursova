"""Deterministic updates for topic-level learner evidence."""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from .models import TopicMastery

ERROR_IMPACT = 0.12
STRENGTH_IMPACT = 0.06
UNCERTAINTY_DECAY = 0.92


def _topic_row(db: Any, user_id: int, topic: str) -> TopicMastery:
    row = db.session.get(TopicMastery, (user_id, topic))
    if row is None:
        row = TopicMastery(
            user_id=user_id,
            topic=topic,
            mastery=0.5,
            uncertainty=1.0,
            attempts=0,
            errors=0,
        )
        db.session.add(row)
    return row


def update_topic_mastery(
    db: Any,
    user_id: int,
    errors: Iterable[Any],
    strengths: Iterable[Any],
) -> list[TopicMastery]:
    """Apply one validated observation and return the touched topic rows."""
    touched: dict[str, TopicMastery] = {}
    for observation in errors:
        topic = observation.topic
        row = touched.setdefault(topic, _topic_row(db, user_id, topic))
        confidence = getattr(observation, "severity", 0.6)
        row.mastery = max(0.0, row.mastery - ERROR_IMPACT * confidence)
        row.errors += 1
        row.attempts += 1
        row.uncertainty = max(0.05, row.uncertainty * UNCERTAINTY_DECAY)
        row.last_seen_at = datetime.now(UTC)
    for observation in strengths:
        topic = observation.topic
        row = touched.setdefault(topic, _topic_row(db, user_id, topic))
        row.mastery = min(1.0, row.mastery + STRENGTH_IMPACT)
        row.attempts += 1
        row.uncertainty = max(0.05, row.uncertainty * UNCERTAINTY_DECAY)
        row.last_seen_at = datetime.now(UTC)
    return list(touched.values())


def topic_recommendations(db: Any, user_id: int, limit: int = 5) -> list[TopicMastery]:
    """Return topics with the weakest observed mastery first."""
    return db.session.scalars(
        db.select(TopicMastery)
        .where(TopicMastery.user_id == user_id, TopicMastery.attempts > 0)
        .order_by(TopicMastery.mastery.asc(), TopicMastery.uncertainty.desc())
        .limit(limit)
    ).all()
