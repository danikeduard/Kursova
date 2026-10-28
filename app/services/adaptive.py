"""Compatibility exports for the adaptive CEFR math.

The stateful learner pipeline uses the same pure functions as the Open WebUI
filter. Keeping this module as a re-export preserves older integrations.
"""

from .levels import (
    LEVELS, clamp, cyrillic_ratio, decay_weights, error_weight,
    extract_json_object, hysteresis_level, kalman_update, level_from_mu,
    ngram_overlap, obs_fluency, obs_grammar, obs_vocab, reliability,
    sanitize_analyzer_json,
)
