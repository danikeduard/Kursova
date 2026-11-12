"""Persistence boundary for baseline and adaptive rating updates."""

from .models import RatingEvent, SkillRating
from .rating import (
    blend_observation,
    effective_confidence,
    error_count_for_skill,
    initial_states,
    kalman_update,
    level_to_rating,
    rating_to_level,
    update_rating,
    word_count,
)


def ensure_rating_state(row: SkillRating, level: str) -> None:
    if row.variance is None:
        row.variance = initial_states(level)[row.skill].p
    if row.last_outlier_sign is None:
        row.last_outlier_sign = 0
    if not row.display_level:
        row.display_level = rating_to_level(row.rating)


def update_skill(
    row: SkillRating,
    observed_level: str,
    confidence: float,
    valid_index: int,
    content: str,
    errors: list,
    mode: str,
) -> dict:
    words = word_count(content)
    error_count = error_count_for_skill(errors, row.skill)
    r_llm = level_to_rating(observed_level)
    if mode == "baseline":
        before = row.rating
        after, weight = update_rating(before, observed_level, confidence, valid_index)
        row.rating = after
        row.n_updates += confidence >= 0.3
        return {
            "mode": mode, "word_count": words, "error_count": error_count,
            "r_llm": r_llm, "c_llm": confidence, "c_eff": confidence,
            "r_density": None, "r_obs": r_llm, "gain": None, "outlier_flag": 0,
            "skipped": confidence < 0.3, "weight": weight, "before": before, "after": after,
        }

    ensure_rating_state(row, observed_level)
    c_eff = effective_confidence(confidence, words)
    r_obs, density = blend_observation(r_llm, error_count, words)
    from .rating import SkillState

    state, info = kalman_update(SkillState(row.rating, row.variance, row.last_outlier_sign), r_obs, c_eff)
    before = row.rating
    row.rating, row.variance, row.last_outlier_sign = state.r, state.p, state.last_outlier_sign
    row.n_updates += not info["skipped"]
    return {
        "mode": mode, "word_count": words, "error_count": error_count,
        "r_llm": r_llm, "c_llm": confidence, "c_eff": c_eff,
        "r_density": density, "r_obs": r_obs, "gain": info.get("gain"),
        "outlier_flag": info.get("outlier_flag", 0), "skipped": info["skipped"],
        "weight": 1.0, "before": before, "after": row.rating,
    }


def event_from_update(
    user_id: int, message_id: int, skill: str, observed_level: str, update: dict, msg_index: int | None = None
) -> RatingEvent:
    return RatingEvent(
        user_id=user_id, message_id=message_id, msg_index=msg_index, skill=skill,
        rating_before=update["before"], rating_after=update["after"],
        observed_level=observed_level, display_level=update["display_level"], confidence=update["c_llm"],
        weight=update["weight"], mode=update["mode"],
        word_count=update["word_count"], error_count=update["error_count"],
        r_llm=update["r_llm"], c_llm=update["c_llm"], c_eff=update["c_eff"],
        r_density=update["r_density"], r_obs=update["r_obs"], gain=update["gain"],
        outlier_flag=update["outlier_flag"], skipped=update["skipped"],
    )
