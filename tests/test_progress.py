from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.extensions import db
from app.models import Conversation, ErrorLog, Message, RatingEvent, User


def _register(client, email="learner@example.com", level="B1"):
    client.post("/register", data={"email": email, "password": "password123", "level": level})


def _event(user_id, message_id, skill, before, after, ts, msg_index, skipped=False):
    return RatingEvent(
        user_id=user_id,
        message_id=message_id,
        skill=skill,
        rating_before=before,
        rating_after=after,
        observed_level="B1",
        confidence=0.2 if skipped else 0.9,
        weight=0.1 if skipped else 1.0,
        msg_index=msg_index,
        skipped=skipped,
        ts=ts,
    )


def test_progress_api_returns_isolated_ordered_after_ratings_and_range(client, app):
    _register(client)
    assert client.get("/progress").status_code == 200
    with app.app_context():
        user = db.session.scalar(db.select(User).filter_by(email="learner@example.com"))
        conversation = Conversation(user_id=user.id, title="Practice")
        db.session.add(conversation)
        db.session.flush()
        messages = [
            Message(user_id=user.id, conversation_id=conversation.id, role="user", content=f"Message {index}")
            for index in (1, 2, 3)
        ]
        db.session.add_all(messages)
        db.session.flush()
        now = datetime.now(UTC)
        db.session.add_all(
            [
                _event(user.id, messages[1].id, "grammar", 900, 1040, now, 2),
                _event(user.id, messages[0].id, "grammar", 800, 900, now - timedelta(days=40), 1),
                _event(user.id, messages[2].id, "grammar", 1040, 1010, now, 3, skipped=True),
                _event(user.id, messages[0].id, "vocab", 800, 850, now, 1),
            ]
        )
        db.session.commit()

    response = client.get("/api/progress?range=7d")

    assert response.status_code == 200
    data = response.get_json()
    grammar = data["skills"]["grammar"]["points"]
    assert [point["n"] for point in grammar] == [2, 3]
    assert [point["rating"] for point in grammar] == [1040, 1010]
    assert grammar[-1]["skipped"] is True
    assert data["skills"]["vocab"]["points"][0]["rating"] == 850
    assert data["skills"]["writing"]["points"] == []


def test_progress_api_does_not_expose_another_users_events(client, app):
    _register(client)
    with app.app_context():
        other = User(email="other@example.com", self_level="C1")
        other.set_password("password123")
        db.session.add(other)
        db.session.flush()
        message = Message(user_id=other.id, role="user", content="Private message")
        db.session.add(message)
        db.session.flush()
        db.session.add(_event(other.id, message.id, "grammar", 1400, 1500, datetime.now(UTC), 1))
        db.session.commit()

    data = client.get("/api/progress").get_json()

    assert data["skills"]["grammar"]["points"] == []


def test_deleting_conversation_preserves_rating_events(client, app):
    _register(client)
    conversation = client.post("/api/conversations", json={}).get_json()["conversation"]
    with app.app_context():
        user = db.session.scalar(db.select(User).filter_by(email="learner@example.com"))
        message = Message(
            user_id=user.id,
            conversation_id=conversation["id"],
            role="user",
            content="A valid English practice sentence.",
        )
        db.session.add(message)
        db.session.flush()
        db.session.add(_event(user.id, message.id, "writing", 800, 920, datetime.now(UTC), 1))
        db.session.add(
            ErrorLog(
                user_id=user.id,
                message_id=message.id,
                topic="grammar",
                error_type="grammar",
                original="I has a book.",
                corrected="I have a book.",
            )
        )
        db.session.commit()

    response = client.delete(f"/api/conversations/{conversation['id']}")

    assert response.status_code == 204
    with app.app_context():
        event = db.session.scalar(db.select(RatingEvent).filter_by(skill="writing"))
        assert event is not None
        assert event.message_id is None
        error = db.session.scalar(db.select(ErrorLog).filter_by(topic="grammar"))
        assert error is not None
        assert error.message_id is None


def test_three_chat_messages_keep_progress_after_conversation_delete(client, app, monkeypatch):
    class FakeGroq:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            if kwargs.get("response_format", {}).get("type") == "json_object":
                content = (
                    '{"is_english": true, "skills": {"grammar": {"level": "B1", "confidence": 0.9}, '
                    '"vocab": {"level": "B1", "confidence": 0.8}, "writing": {"level": "B1", "confidence": 0.7}}, '
                    '"errors": []}'
                )
            else:
                content = "Keep going and add another detail."
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    client.post("/register", data={"email": "three@example.com", "password": "password123", "level": "B1"})
    conversation = client.post("/api/conversations", json={}).get_json()["conversation"]
    monkeypatch.setattr("app.routes.Groq", FakeGroq)
    for content in (
        "I enjoy reading books every evening.",
        "Last weekend I visited a small museum.",
        "Next month I will practice speaking more often.",
    ):
        response = client.post("/api/chat", json={"content": content, "conversation_id": conversation["id"]})
        assert response.status_code == 200

    before = client.get("/api/progress").get_json()
    before_points = before["skills"]["grammar"]["points"]
    assert len(before_points) == 3

    assert client.delete(f"/api/conversations/{conversation['id']}").status_code == 204
    after = client.get("/api/progress").get_json()

    assert after["skills"]["grammar"]["points"] == before_points
    with app.app_context():
        events = db.session.scalars(db.select(RatingEvent)).all()
        assert len(events) == 9
        assert all(event.message_id is None and event.msg_index for event in events)
