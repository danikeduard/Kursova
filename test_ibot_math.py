from ibot_filter import (
    CONFIG, cyrillic_ratio, decay_weights, error_weight, hysteresis_level,
    extract_json_object, kalman_update, ngram_overlap, obs_fluency, reliability,
    sanitize_analyzer_json,
)


def test_kalman_regression_and_hysteresis():
    mu, variance = 2.0, 1.5
    for words, observation in ((10, 2.0), (21, 3.2), (35, 3.8)):
        mu, variance = kalman_update(mu, variance, observation, words)
    assert abs(mu - 3.11) < 0.03
    assert abs(variance - 0.21) < 0.03
    shown, _ = hysteresis_level(mu, variance, "A2", 3)
    assert shown == "A2"


def test_decay_and_error_weighting():
    assert decay_weights({"article": 2, "tense": 1}) == {"article": 1.8, "tense": 0.9}
    assert error_weight("high", 2, 2.0, "tense") > error_weight("high", 6, 2.0, "tense")
    assert error_weight("low", 2, 2.0, "spelling", True) == 0


def test_text_features_and_safe_json():
    assert cyrillic_ratio("Привіт world") > 0.5
    assert ngram_overlap("I like to read books", "I like to read books today") == 1
    assert sanitize_analyzer_json("{not json}") is None
    assert sanitize_analyzer_json({"errors": [], "structures_correct": [], "words": [],
                                   "task_difficulty": 1, "overall_estimate": 2})["overall_estimate"] == 2
    assert extract_json_object("Here is the result:\n```json\n{\"overall_estimate\": 3}\n```") == {
        "overall_estimate": 3
    }


def test_short_message_reliability():
    assert reliability(2) == 2 / 30
