"""Deterministic pedagogical policy for selecting the next tutor action."""

from typing import Any

from .learning import topic_recommendations
from .models import SkillRating
from .rating import rating_to_level

TOPIC_SKILLS = {
    "articles": "grammar",
    "present_simple": "grammar",
    "present_continuous": "grammar",
    "past_simple": "grammar",
    "past_continuous": "grammar",
    "present_perfect": "grammar",
    "past_perfect": "grammar",
    "future_forms": "grammar",
    "modal_verbs": "grammar",
    "conditionals": "grammar",
    "reported_speech": "grammar",
    "passive_voice": "grammar",
    "relative_clauses": "grammar",
    "gerunds_infinitives": "grammar",
    "prepositions": "grammar",
    "word_order": "grammar",
    "subject_verb_agreement": "grammar",
    "countable_uncountable": "grammar",
    "comparatives_superlatives": "grammar",
    "phrasal_verbs": "vocab",
    "collocations": "vocab",
    "word_choice": "vocab",
    "false_friends": "vocab",
    "word_formation": "vocab",
    "spelling": "writing",
    "punctuation": "writing",
    "capitalization": "writing",
    "coherence": "writing",
    "register": "writing",
    "sentence_structure": "writing",
}


def select_learning_plan(db: Any, user_id: int) -> dict[str, str | None]:
    """Choose one explainable action for the next tutor response."""
    ratings = db.session.scalars(
        db.select(SkillRating).where(SkillRating.user_id == user_id)
    ).all()
    weakest = min(ratings, key=lambda row: row.rating) if ratings else None
    topics = topic_recommendations(db, user_id, limit=1)
    topic = topics[0] if topics else None

    if topic is None:
        action = "diagnostic_conversation"
        target_topic = None
    elif topic.uncertainty > 0.7:
        action = "targeted_diagnostic"
        target_topic = topic.topic
    elif topic.mastery < 0.45:
        action = "micro_exercise"
        target_topic = topic.topic
    else:
        action = "spaced_review"
        target_topic = topic.topic

    target_skill = TOPIC_SKILLS.get(target_topic) if target_topic else None
    if target_skill is None and weakest is not None:
        target_skill = weakest.skill
    level = (weakest.display_level or rating_to_level(weakest.rating)) if weakest is not None else "B1"
    return {
        "target_skill": target_skill,
        "target_topic": target_topic,
        "action": action,
        "difficulty": level,
    }
