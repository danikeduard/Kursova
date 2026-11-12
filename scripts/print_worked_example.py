"""Print the documented adaptive-rating worked example from the model code."""

from app.rating import P0, SkillState, effective_confidence, kalman_update, level_to_rating


def main() -> None:
    """Print successive ratings for repeated A2 observations from a C1 state."""
    state = SkillState(level_to_rating("C1"), P0)
    ratings = []
    for _ in range(7):
        state, _ = kalman_update(state, level_to_rating("A2"), effective_confidence(0.8, 14))
        ratings.append(round(state.r))
    print(", ".join(map(str, ratings)))


if __name__ == "__main__":
    main()
