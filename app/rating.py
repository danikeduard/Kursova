"""Pure adaptive CEFR rating functions.

Ratings use a 2.5x expanded scale (0-5000) with CEFR centres spaced by 500.
"""

from dataclasses import dataclass

from .message_validation import assessability, assessment_word_count

LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
SCALE_FACTOR = 2.5
CENTERS = {"A1": 1500.0, "A2": 2000.0, "B1": 2500.0, "B2": 3000.0, "C1": 3500.0, "C2": 4000.0}
ALPHA = 0.12 / SCALE_FACTOR
MAX_STEP = 80.0
SKILL_WEIGHTS = {"grammar": 0.4, "vocab": 0.3, "writing": 0.3}
P0 = (250 * SCALE_FACTOR) ** 2
SIGMA2 = (250 * SCALE_FACTOR) ** 2
Q = 900 * SCALE_FACTOR**2
KALMAN_MAX_STEP = 120
LEN_FULL_WORDS = 12
MIN_CONFIDENCE = 0.3
MIN_EVIDENCE_WORDS = 12
MIN_EVIDENCE_CONFIDENCE = 0.55
PROMOTION_MAX_ERROR_RATE = 0.05
DOWNGRADE_MIN_ERRORS = 2
DOWNGRADE_MIN_ERROR_RATE = 0.1
LONG_SAMPLE_WORDS = 40
LONG_SAMPLE_CONFIDENCE = 0.75
OUTLIER_GAP = 1000
OUTLIER_CONF = 0.6
OUTLIER_FACTOR = 0.5
DENS_MIN_WORDS = 8
DENS_LAMBDA = 0.3
DENS_TABLE = [(15, 1500), (10, 2000), (6, 2500), (3, 3000), (1.5, 3500), (0, 4000)]


@dataclass(frozen=True)
class SkillState:
    r: float
    p: float
    last_outlier_sign: int = 0


def level_to_rating(level: str) -> float:
    """Return the centre rating for a CEFR level."""
    normalized = level.upper()
    if normalized not in CENTERS:
        raise ValueError(f"Unknown CEFR level: {level}")
    return CENTERS[normalized]


def rating_to_level(rating: float) -> str:
    """Return the label for a rating using the specified boundaries."""
    if rating < 1750:
        return "A1"
    if rating < 2250:
        return "A2"
    if rating < 2750:
        return "B1"
    if rating < 3250:
        return "B2"
    if rating < 3750:
        return "C1"
    return "C2"


def initial_states(level: str) -> dict[str, SkillState]:
    center = level_to_rating(level)
    return {skill: SkillState(center, P0, 0) for skill in SKILL_WEIGHTS}


def effective_confidence(c_llm: float, words: int) -> float:
    return c_llm * min(1.0, words / LEN_FULL_WORDS)


def has_level_evidence(
    current_level: str, observed_level: str, confidence: float, words: int, skill_errors: int
) -> bool:
    """Require a substantial, skill-relevant sample before changing a CEFR band."""
    if words < MIN_EVIDENCE_WORDS or confidence < MIN_EVIDENCE_CONFIDENCE:
        return False

    current_index = LEVELS.index(current_level.upper())
    observed_index = LEVELS.index(observed_level.upper())
    if current_index == observed_index:
        return False

    error_rate = skill_errors / words
    if observed_index > current_index:
        # A few slips are acceptable in a longer sample, but a level-up needs
        # broadly controlled use of the skill being rated.
        return error_rate <= PROMOTION_MAX_ERROR_RATE

    # A short, simple, error-free sentence does not prove that a learner's
    # established level has fallen. Require repeated errors or a long sample.
    repeated_errors = (
        skill_errors >= DOWNGRADE_MIN_ERRORS
        and error_rate >= DOWNGRADE_MIN_ERROR_RATE
    )
    long_sample = words >= LONG_SAMPLE_WORDS and confidence >= LONG_SAMPLE_CONFIDENCE
    return repeated_errors or long_sample


def density_rating(errors: int, words: int) -> float:
    density = 100.0 * errors / words
    for lower_bound, rating in DENS_TABLE:
        if density >= lower_bound:
            return rating
    return DENS_TABLE[-1][1]


def blend_observation(r_llm: float, errors: int, words: int) -> tuple[float, float | None]:
    if words < DENS_MIN_WORDS:
        return r_llm, None
    density = density_rating(errors, words)
    return r_llm - DENS_LAMBDA * max(0.0, r_llm - density), density


def kalman_update(state: SkillState, r_obs: float, c_eff: float) -> tuple[SkillState, dict]:
    if c_eff < MIN_CONFIDENCE:
        return state, {"skipped": True}
    gap = r_obs - state.r
    sign = (gap > 0) - (gap < 0)
    suspicious = abs(gap) >= OUTLIER_GAP and c_eff < OUTLIER_CONF
    confirmed = suspicious and state.last_outlier_sign == sign
    factor = OUTLIER_FACTOR if suspicious and not confirmed else 1.0
    measurement_variance = SIGMA2 / c_eff**2
    gain = factor * state.p / (state.p + measurement_variance)
    delta = max(-KALMAN_MAX_STEP, min(KALMAN_MAX_STEP, gain * gap))
    new_p = min(P0, (1 - gain) * state.p + Q)
    new_sign = sign if suspicious else 0
    outlier_flag = 0 if not suspicious else (2 if confirmed else 1)
    return SkillState(state.r + delta, new_p, new_sign), {
        "skipped": False,
        "gain": gain,
        "delta": delta,
        "outlier_flag": outlier_flag,
    }


def word_count(content: str) -> int:
    """Count words that can provide learner evidence for an assessment."""
    return assessment_word_count(content)


def error_count_for_skill(errors: list, skill: str) -> int:
    grammar_types = {"grammar", "word_order", "preposition", "article"}
    if skill == "grammar":
        return sum(error.type in grammar_types for error in errors)
    if skill == "vocab":
        return sum(error.type == "vocab" for error in errors)
    # Writing is assessed for organization and cohesion, not language accuracy.
    # The evaluator currently emits no structural writing-error category.
    return 0


def is_valid_message(content: str) -> bool:
    """Compatibility wrapper for the shared assessment-eligibility policy."""
    return assessability(content).eligible


def update_rating(rating: float, observed_level: str, confidence: float, valid_index: int) -> tuple[float, float]:
    """Apply one observation and return (new rating, applied weight)."""
    weight = 2.0 if valid_index <= 5 else 1.0
    if confidence < 0.3:
        return rating, weight
    confidence = max(0.0, min(1.0, confidence))
    delta = ALPHA * weight * confidence * (level_to_rating(observed_level) - rating)
    delta = max(-MAX_STEP, min(MAX_STEP, delta))
    return rating + delta, weight


def displayed_level(rating: float, previous_level: str | None) -> str:
    """Apply 25-point hysteresis when changing a displayed label."""
    candidate = rating_to_level(rating)
    if previous_level is None or candidate == previous_level:
        return candidate
    if LEVELS.index(candidate) > LEVELS.index(previous_level):
        boundary = level_to_rating(candidate) - 250
        return candidate if rating >= boundary + 62.5 else previous_level
    boundary = level_to_rating(previous_level) - 250
    return candidate if rating <= boundary - 62.5 else previous_level


def overall_rating(ratings: dict[str, float]) -> float:
    """Return the weighted overall rating."""
    return sum(ratings[skill] * weight for skill, weight in SKILL_WEIGHTS.items())
