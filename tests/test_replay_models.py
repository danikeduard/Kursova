from types import SimpleNamespace

from scripts.replay_models import replay


def event(user_id, skill, observed_level, confidence=0.8, word_count=20, error_count=0):
    return SimpleNamespace(
        user_id=user_id,
        skill=skill,
        observed_level=observed_level,
        confidence=confidence,
        c_llm=confidence,
        c_eff=None,
        word_count=word_count,
        error_count=error_count,
        rating_before=1000,
    )


def test_replay_is_deterministic_and_models_are_comparable():
    events = [
        event(1, "grammar", "B2"),
        event(1, "grammar", "B2"),
        event(1, "grammar", "A2", confidence=0.4, error_count=8),
    ]

    first = replay(events, "kalman")
    second = replay(events, "kalman")

    assert first[0] == second[0]
    assert first[1] == second[1]
    assert first[0][(1, "grammar")][-1] != replay(events, "baseline")[0][(1, "grammar")][-1]


def test_replay_variants_isolate_density_and_outlier_signals():
    events = [
        event(1, "writing", "C2", confidence=0.4, word_count=40, error_count=0),
        event(1, "writing", "C2", confidence=0.4, word_count=40, error_count=0),
    ]

    _, _, with_guard = replay(events, "kalman")
    _, _, without_guard = replay(events, "kalman-no-outlier")

    assert with_guard[(1, "writing")].p != without_guard[(1, "writing")].p
