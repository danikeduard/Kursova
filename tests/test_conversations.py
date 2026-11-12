from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import User


def register(client, email, level="B1"):
    return client.post(
        "/register",
        data={"email": email, "password": "password123", "level": level},
    )


def test_conversation_crud(client, app):
    assert register(client, "conversation@example.com").status_code == 302

    created = client.post("/api/conversations", json={})
    assert created.status_code == 201
    conversation_id = created.json["conversation"]["id"]

    updated = client.patch(
        f"/api/conversations/{conversation_id}",
        json={"title": "Practice English", "pinned": True},
    )
    assert updated.status_code == 200
    assert updated.json["conversation"]["title"] == "Practice English"
    assert updated.json["conversation"]["title_auto"] is False

    listed = client.get("/api/conversations")
    assert listed.status_code == 200
    assert listed.json["items"][0]["id"] == conversation_id

    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 204
    assert client.get(f"/api/conversations/{conversation_id}/messages").status_code == 404


def test_conversation_ownership_returns_not_found(client, app):
    assert register(client, "owner@example.com").status_code == 302
    created = client.post("/api/conversations", json={})
    conversation_id = created.json["conversation"]["id"]

    with app.app_context():
        other = User(
            email="other@example.com",
            password_hash=generate_password_hash("password123"),
            self_level="B1",
        )
        db.session.add(other)
        db.session.commit()
        other_id = other.id
    client.post("/logout")
    client.post("/login", data={"email": "other@example.com", "password": "password123"})

    assert client.get(f"/api/conversations/{conversation_id}/messages").status_code == 404
    assert client.patch(f"/api/conversations/{conversation_id}", json={"title": "Nope"}).status_code == 404
    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 404

    with app.app_context():
        db.session.delete(db.session.get(User, other_id))
        db.session.commit()


def test_conversation_can_be_duplicated_and_exported(client, app, monkeypatch):
    assert register(client, "export@example.com").status_code == 302
    conversation = client.post("/api/conversations", json={}).json["conversation"]
    monkeypatch.setattr("app.routes.Groq", lambda **kwargs: None)
    with app.app_context():
        from app.models import Message

        db.session.add_all(
            [
                Message(
                    user_id=1,
                    conversation_id=conversation["id"],
                    role="user",
                    content="Hello",
                ),
                Message(
                    user_id=1,
                    conversation_id=conversation["id"],
                    role="assistant",
                    content="Hi there",
                ),
            ]
        )
        db.session.commit()

    duplicate = client.post(f"/api/conversations/{conversation['id']}/duplicate")
    assert duplicate.status_code == 201
    duplicate_id = duplicate.json["conversation"]["id"]
    messages = client.get(f"/api/conversations/{duplicate_id}/messages")
    assert [item["content"] for item in messages.json["messages"]] == ["Hello", "Hi there"]

    exported = client.get(f"/api/conversations/{conversation['id']}/export?format=markdown")
    assert exported.status_code == 200
    assert "# New chat" in exported.text
    assert "Hi there" in exported.text

    with app.app_context():
        from app.models import Message

        cloned = db.session.scalars(
            db.select(Message).where(Message.conversation_id == duplicate_id)
        ).all()
        assert all(not item.is_valid_for_rating and item.msg_index is None for item in cloned)


def test_conversation_cursor_matches_pinned_updated_id_order(client, app):
    assert register(client, "paging@example.com").status_code == 302
    first = client.post("/api/conversations", json={}).json["conversation"]
    second = client.post("/api/conversations", json={}).json["conversation"]
    third = client.post("/api/conversations", json={}).json["conversation"]

    with app.app_context():
        from datetime import UTC, datetime, timedelta

        from app.models import Conversation

        now = datetime.now(UTC)
        for conversation_id, pinned, offset in (
            (first["id"], True, 0),
            (second["id"], False, 0),
            (third["id"], False, 1),
        ):
            db.session.execute(
                db.update(Conversation).where(Conversation.id == conversation_id).values(
                    pinned=pinned,
                    updated_at=now - timedelta(minutes=offset),
                )
            )
        db.session.commit()

    page_one = client.get("/api/conversations?limit=1")
    page_two = client.get(f"/api/conversations?limit=1&cursor={page_one.json['next_cursor']}")
    page_three = client.get(f"/api/conversations?limit=1&cursor={page_two.json['next_cursor']}")
    assert [page_one.json["items"][0]["id"], page_two.json["items"][0]["id"],
            page_three.json["items"][0]["id"]] == [first["id"], second["id"], third["id"]]


def test_conversation_search_treats_wildcards_literally(client, app):
    assert register(client, "search-wildcards@example.com").status_code == 302
    target = client.post("/api/conversations", json={}).json["conversation"]
    other = client.post("/api/conversations", json={}).json["conversation"]
    client.patch(f"/api/conversations/{target['id']}", json={"title": "100%_ready"})
    client.patch(f"/api/conversations/{other['id']}", json={"title": "100Xaready"})

    response = client.get("/api/conversations", query_string={"q": "%_"})

    assert response.status_code == 200
    assert [item["id"] for item in response.json["items"]] == [target["id"]]


def test_assistant_message_feedback_is_owned_and_updatable(client, app):
    assert register(client, "feedback@example.com").status_code == 302
    conversation = client.post("/api/conversations", json={}).json["conversation"]
    with app.app_context():
        from app.models import Message

        message = Message(
            user_id=1,
            conversation_id=conversation["id"],
            role="assistant",
            content="Try using the past tense.",
        )
        db.session.add(message)
        db.session.commit()
        message_id = message.id

    response = client.post(f"/api/messages/{message_id}/feedback", json={"rating": "up"})
    assert response.status_code == 200
    assert response.json["rating"] == "up"
    response = client.post(
        f"/api/messages/{message_id}/feedback",
        json={"rating": "down", "comment": "Too brief"},
    )
    assert response.status_code == 200
    assert client.get(f"/api/conversations/{conversation['id']}/messages").json["messages"][0]["feedback"] == "down"


def test_settings_and_conversation_organization_are_persisted(client):
    assert register(client, "settings@example.com").status_code == 302
    settings = client.get("/api/settings")
    assert settings.status_code == 200
    assert "provider" not in settings.json
    assert "model" not in settings.json

    rejected = client.patch(
        "/api/settings",
        json={"provider": "openai", "model": "gpt-4o-mini"},
    )
    assert rejected.status_code == 400

    updated = client.patch(
        "/api/settings",
        json={"reply_length": "concise", "use_emojis": False, "theme": "light"},
    )
    assert updated.status_code == 200
    assert "provider" not in updated.json
    assert "model" not in updated.json
    conversation = client.post("/api/conversations", json={}).json["conversation"]
    organized = client.patch(
        f"/api/conversations/{conversation['id']}",
        json={"folder": "Grammar", "tags": ["grammar", "grammar", "exam"]},
    )
    assert organized.status_code == 200
    assert organized.json["conversation"]["folder"] == "Grammar"
    assert organized.json["conversation"]["tags"] == ["grammar", "exam"]


def test_level_change_is_readable_only_by_owner(client, app):
    assert register(client, "level-change@example.com").status_code == 302
    with app.app_context():
        from app.models import LevelChange

        change = LevelChange(
            user_id=1,
            skill="grammar",
            label="B2",
            rating_before=1190,
            rating_after=1210,
            evidence={"events": [], "errors": [], "strengths": []},
        )
        db.session.add(change)
        db.session.commit()
        change_id = change.id

    response = client.get(f"/api/level-changes/{change_id}")
    assert response.status_code == 200
    assert response.json["id"] == change_id

    client.post("/logout")
    assert client.get(f"/api/level-changes/{change_id}").status_code == 302
