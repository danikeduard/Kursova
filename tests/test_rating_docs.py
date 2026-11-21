from pathlib import Path

from app.rating import P0, SkillState, effective_confidence, kalman_update, level_to_rating


def test_level_model_documentation_matches_rating_constants_and_example():
    source = Path(__file__).resolve().parents[1] / "docs" / "level_model.md"
    documentation = source.read_text(encoding="utf-8")
    centers = [f"{level}={int(level_to_rating(level))}" for level in ("A1", "A2", "B1", "B2", "C1", "C2")]
    state = SkillState(level_to_rating("C1"), P0)
    ratings = []
    for _ in range(7):
        state, _ = kalman_update(state, level_to_rating("A2"), effective_confidence(0.8, 14))
        ratings.append(str(round(state.r)))

    normalized_docs = " ".join(documentation.split())
    assert all(center in normalized_docs for center in centers)
    assert ", ".join(ratings) in normalized_docs
    assert "/ 2.5" not in normalized_docs
