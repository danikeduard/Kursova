from app.extensions import db
from app.models import SkillRating, TopicMastery, User
from app.pedagogy import select_learning_plan


def test_policy_starts_with_diagnostic_conversation(app):
    with app.app_context():
        user = User(email="policy@example.com", password_hash="hash", self_level="B1")
        db.session.add(user)
        db.session.flush()
        db.session.add_all(
            [
                    SkillRating(user_id=user.id, skill="grammar", rating=2500),
                    SkillRating(user_id=user.id, skill="vocab", rating=2400),
                    SkillRating(user_id=user.id, skill="writing", rating=2600),
            ]
        )
        db.session.commit()

        plan = select_learning_plan(db, user.id)

    assert plan == {
        "target_skill": "vocab",
        "target_topic": None,
        "action": "diagnostic_conversation",
        "difficulty": "B1",
    }


def test_policy_selects_micro_exercise_for_weak_topic(app):
    with app.app_context():
        user = User(email="exercise@example.com", password_hash="hash", self_level="B1")
        db.session.add(user)
        db.session.flush()
        db.session.add_all(
            [
                SkillRating(user_id=user.id, skill="grammar", rating=1000),
                SkillRating(user_id=user.id, skill="vocab", rating=1100),
                SkillRating(user_id=user.id, skill="writing", rating=1200),
                TopicMastery(
                    user_id=user.id,
                    topic="articles",
                    mastery=0.3,
                    uncertainty=0.4,
                    attempts=3,
                    errors=2,
                ),
            ]
        )
        db.session.commit()

        plan = select_learning_plan(db, user.id)

    assert plan["target_skill"] == "grammar"
    assert plan["target_topic"] == "articles"
    assert plan["action"] == "micro_exercise"
