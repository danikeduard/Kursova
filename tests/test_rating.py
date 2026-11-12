import pytest

from app.rating import (
    displayed_level,
    is_valid_message,
    level_to_rating,
    overall_rating,
    rating_to_level,
    update_rating,
)


def test_initialization_and_mapping_boundaries():
    assert level_to_rating("a2") == 2000
    assert rating_to_level(1749.99) == "A1"
    assert rating_to_level(1750) == "A2"
    assert rating_to_level(2249.99) == "A2"
    assert rating_to_level(2250) == "B1"
    assert rating_to_level(3750) == "C2"


def test_weight_is_two_for_first_five_and_one_after():
    first, first_weight = update_rating(2500, "A2", 1, 1)
    sixth, sixth_weight = update_rating(2500, "A2", 1, 6)
    assert first_weight == 2
    assert sixth_weight == 1
    assert 2500 - first == 2 * (2500 - sixth)


def test_delta_is_clamped():
    updated, _ = update_rating(4000, "A1", 1, 1)
    assert updated == 3920


def test_low_confidence_skips_update():
    assert update_rating(2500, "C2", 0.29, 1)[0] == 2500


def test_invalid_messages_do_not_qualify_for_rating():
    assert not is_valid_message("/analysis please explain this")
    assert not is_valid_message("Too short")
    assert is_valid_message("I enjoy reading books every evening.")


def test_hysteresis_prevents_flapping():
    assert displayed_level(2262, "A2") == "A2"
    assert displayed_level(2312.5, "A2") == "B1"
    assert displayed_level(2200, "B1") == "B1"
    assert displayed_level(2187.5, "B1") == "A2"


def test_overall_weighted_rating():
    assert overall_rating({"grammar": 2500, "vocab": 3000, "writing": 3500}) == pytest.approx(2950)


def test_convergence_is_faster_during_early_window():
    early = 3500.0
    late = 3500.0
    for index in range(1, 6):
        early, _ = update_rating(early, "A2", 1, index)
    for index in range(6, 11):
        late, _ = update_rating(late, "A2", 1, index)
    assert abs(3500 - early) > abs(3500 - late)
    assert early < 3500 and late < 3500
