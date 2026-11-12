"""End-to-end test for learner text changing the persisted CEFR rating."""

from types import SimpleNamespace

from app.extensions import db
from app.models import ChatTurn, LevelChange, RatingEvent, SkillRating


class TextDrivenAssessmentGroq:
    """Deterministic provider stand-in: advanced text yields B2 skill evidence."""

    def __init__(self, **kwargs):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        messages = kwargs["messages"]
        learner_text = " ".join(item["content"] for item in messages if item["role"] == "user")
        if kwargs.get("response_format", {}).get("type") == "json_object":
            level = "B2" if "although" in learner_text.casefold() else "A2"
            payload = (
                '{"is_english": true, "skills": {'
                f'"grammar": {{"level": "{level}", "confidence": 0.95}}, '
                f'"vocab": {{"level": "{level}", "confidence": 0.95}}, '
                f'"writing": {{"level": "{level}", "confidence": 0.95}}'
                '}, "errors": [], "strengths": []}'
            )
            content = payload
        else:
            content = "Thanks for sharing. Keep going!"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10),
        )


def test_text_messages_adapt_persisted_english_level(client, app, monkeypatch):
    client.post("/register", data={"email": "adapt@example.com", "password": "password123", "level": "A2"})
    monkeypatch.setattr("app.routes.Groq", TextDrivenAssessmentGroq)
    app.config["RATING_MODE"] = "kalman"

    messages = [
        "Although the first attempt was difficult, I revised my argument after comparing several examples.",
        "Although I had misunderstood the assignment, I eventually revised my argument after studying the evidence.",
        "Although the evidence was incomplete, I compared alternative explanations before revising my conclusion.",
    ]
    responses = [client.post("/api/chat", json={"content": content}) for content in messages]

    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json["levels"]["grammar"] == "A2"
    assert responses[2].json["levels"]["grammar"] == "B1"
    assert responses[2].json["level_changed"]
    with app.app_context():
        turns = db.session.scalars(db.select(ChatTurn).order_by(ChatTurn.id)).all()
        assert [turn.learning_action for turn in turns] == ["diagnostic_conversation"] * 3
        assert all(turn.status == "completed" and turn.evaluation_status == "success" for turn in turns)
        ratings = db.session.scalars(
            db.select(SkillRating).where(SkillRating.user_id == 1).order_by(SkillRating.skill)
        ).all()
        assert {row.display_level for row in ratings} == {"B1"}
        assert all(row.rating > 2000 for row in ratings)
        level_change = db.session.scalar(db.select(LevelChange).where(LevelChange.skill == "grammar"))
        assert level_change.evidence["display_level_before"] == "A2"


def test_evaluator_failure_is_reported_and_does_not_count_as_assessed(client, app, monkeypatch):
    class BrokenEvaluatorGroq(TextDrivenAssessmentGroq):
        def create(self, **kwargs):
            if kwargs.get("response_format", {}).get("type") == "json_object":
                content = "not valid JSON"
            else:
                content = "I replied, but could not assess your English."
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10),
            )

    client.post("/register", data={"email": "failed-eval@example.com", "password": "password123", "level": "A2"})
    monkeypatch.setattr("app.routes.Groq", BrokenEvaluatorGroq)
    response = client.post(
        "/api/chat",
        json={"content": "I went to the library yesterday and borrowed a book about history."},
    )

    assert response.status_code == 200
    assert response.json["assessment_status"] == "failed"
    progress = client.get("/api/progress").json["user"]
    assert progress["valid_messages"] == 1
    assert progress["assessed_messages"] == 0
    assert progress["assessment_failures"] == 1
    with app.app_context():
        rating_events = db.session.scalar(db.select(db.func.count(RatingEvent.id)))
        assert rating_events == 0
