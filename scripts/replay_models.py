"""Replay logged rating observations without inventing missing observations."""

import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.extensions import db
from app.models import RatingEvent, User
from app.rating import (
    P0,
    SkillState,
    blend_observation,
    effective_confidence,
    kalman_update,
    level_to_rating,
    rating_to_level,
    update_rating,
)


def replay(events, model):
    states = {}
    changes = defaultdict(int)
    histories = defaultdict(list)
    for event in events:
        key = (event.user_id, event.skill)
        if key not in states:
            states[key] = SkillState(event.rating_before, P0, 0)
        state = states[key]
        previous = rating_to_level(state.r)
        if model == "baseline":
            value, _ = update_rating(state.r, event.observed_level, event.c_llm or event.confidence, 1)
            state = SkillState(value, state.p, state.last_outlier_sign)
        else:
            confidence = event.c_eff or effective_confidence(event.c_llm or event.confidence, event.word_count or 0)
            observation = level_to_rating(event.observed_level)
            if model != "kalman-no-density":
                observation, _ = blend_observation(observation, event.error_count or 0, event.word_count or 0)
            if model == "kalman-no-outlier":
                state = SkillState(state.r, state.p, 0)
            state, _ = kalman_update(state, observation, confidence)
        states[key] = state
        current = rating_to_level(state.r)
        changes[key] += current != previous
        histories[key].append(state.r)
    return histories, changes, states


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", help="Override DATABASE_URL")
    args = parser.parse_args()
    app = create_app()
    if args.database:
        app.config["SQLALCHEMY_DATABASE_URI"] = args.database
    with app.app_context():
        events = db.session.scalars(db.select(RatingEvent).order_by(RatingEvent.user_id, RatingEvent.ts, RatingEvent.id)).all()
        if not events:
            print("No logged rating observations; nothing to replay.")
            return
        print("WARNING: replay is non-causal; tutor behavior depended on the live model.")
        print("WARNING: small samples are not conclusive.")
        users = {user.id: user for user in db.session.scalars(db.select(User)).all()}
        for model in ("baseline", "kalman", "kalman-no-density", "kalman-no-outlier"):
            histories, flips, _ = replay(events, model)
            changes = [
                abs(history[index] - history[index - 1])
                for history in histories.values()
                for index in range(1, len(history))
            ]
            convergence = []
            for history in histories.values():
                final = history[-1]
                convergence.append(next(
                    (index + 1 for index, value in enumerate(history) if abs(value - final) <= 100),
                    "n/a",
                ))
            print(
                f"{model}: mean_abs_change={statistics.mean(changes) if changes else 0:.2f}, "
                f"label_flips={sum(flips.values())}, "
                f"messages_to_within_100={statistics.mean(v for v in convergence if v != 'n/a') if any(v != 'n/a' for v in convergence) else 'n/a'}"
            )
            for user_id, user in users.items():
                user_histories = [history for (uid, _), history in histories.items() if uid == user_id]
                if not user_histories:
                    continue
                final = statistics.mean(history[-1] for history in user_histories)
                if rating_to_level(final) == user.self_level:
                    continue
                values = [user_histories[0][index - 1] if len(user_histories[0]) >= index else "n/a" for index in (3, 5, 10)]
                print(f"  wrong-self user={user_id}: after_3_5_10={values}")


if __name__ == "__main__":
    main()
