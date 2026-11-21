from types import SimpleNamespace

from app.extensions import db
from app.models import ApiMetric, ChatTurn


class FakeGroq:
    def __init__(self, **kwargs):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        if kwargs.get("response_format", {}).get("type") == "json_object":
            content = '{"is_english": true, "skills": {"grammar": {"level": "B1", "confidence": 0.9}, "vocab": {"level": "B1", "confidence": 0.8}, "writing": {"level": "B1", "confidence": 0.7}}, "errors": []}'
        else:
            content = "Nice work! Can you tell me more? 🙂"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_chat_persists_message_and_returns_levels(client, app, monkeypatch):
    client.post("/register", data={"email": "chat@example.com", "password": "password123", "level": "A2"})
    monkeypatch.setattr("app.routes.Groq", FakeGroq)
    response = client.post("/api/chat", json={"content": "I like reading books every evening."})
    assert response.status_code == 200
    assert response.json["reply"].startswith("Nice work")
    assert response.json["levels"]["grammar"] == "A2"


def test_levels_endpoint_returns_persisted_skill_levels(client):
    client.post("/register", data={"email": "levels@example.com", "password": "password123", "level": "C1"})
    response = client.get("/api/levels")
    assert response.status_code == 200
    assert response.json["levels"] == {"grammar": "C1", "vocab": "C1", "writing": "C1"}


def test_sidebar_logo_links_back_to_chat(client):
    client.post("/register", data={"email": "logo@example.com", "password": "password123", "level": "B1"})

    chat_page = client.get("/chat")
    progress_page = client.get("/progress")

    assert b'href="/chat" aria-label="LinguaPath chat"' in chat_page.data
    assert b'href="/chat" aria-label="LinguaPath chat"' in progress_page.data


def test_chat_messages_are_stored_in_selected_conversation(client, app, monkeypatch):
    client.post("/register", data={"email": "multi@example.com", "password": "password123", "level": "B1"})
    conversation = client.post("/api/conversations", json={}).json["conversation"]
    monkeypatch.setattr("app.routes.Groq", FakeGroq)

    response = client.post(
        "/api/chat",
        json={"content": "I enjoy reading books every evening.", "conversation_id": conversation["id"]},
    )

    assert response.status_code == 200
    history = client.get(f"/api/conversations/{conversation['id']}/messages")
    assert [message["role"] for message in history.json["messages"]] == ["user", "assistant"]


def test_demo_mode_works_without_provider_key(client, app):
    client.post("/register", data={"email": "demo@example.com", "password": "password123", "level": "B1"})
    app.config["DEMO_MODE"] = True

    response = client.post("/api/chat", json={"content": "I enjoy learning English every day."})

    assert response.status_code == 200
    with app.app_context():
        turn = db.session.scalar(db.select(ChatTurn))
        metric = db.session.scalar(db.select(ApiMetric).where(ApiMetric.kind == "tutor"))
        assert turn.status == "completed"
        assert metric.tokens_in == 80
        assert metric.tokens_out == 40


def test_demo_mode_assesses_models_using_strict_json_schema(client, app):
    client.post("/register", data={"email": "demo-schema@example.com", "password": "password123", "level": "A2"})
    app.config["DEMO_MODE"] = True
    app.config["LLM_MODEL_EVALUATOR"] = "openai/gpt-oss-120b"

    response = client.post("/api/chat", json={"content": "I enjoy learning English every day."})

    assert response.status_code == 200
    assert response.json["assessment_status"] == "success"
    assert client.get("/api/progress").json["user"]["assessed_messages"] == 1


def test_tutor_failure_marks_turn_failed(client, app, monkeypatch):
    client.post("/register", data={"email": "failure@example.com", "password": "password123", "level": "B1"})

    class BrokenGroq:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr("app.routes.Groq", BrokenGroq)

    response = client.post("/api/chat", json={"content": "I enjoy learning English every day."})

    assert response.status_code == 503
    with app.app_context():
        turn = db.session.scalar(db.select(ChatTurn))
        assert turn.status == "failed"
        assert turn.tutor_status == "failed"


def test_failed_turn_does_not_consume_daily_message_limit(client, app, monkeypatch):
    client.post("/register", data={"email": "retry@example.com", "password": "password123", "level": "B1"})
    app.config["DAILY_MESSAGE_CAP"] = 1

    class BrokenGroq:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr("app.routes.Groq", BrokenGroq)
    failed = client.post("/api/chat", json={"content": "I enjoy learning English every day."})
    assert failed.status_code == 503

    monkeypatch.setattr("app.routes.Groq", FakeGroq)
    succeeded = client.post("/api/chat", json={"content": "I enjoy learning English every day."})
    assert succeeded.status_code == 200


def test_evaluator_metric_is_saved_when_tutor_fails(client, app, monkeypatch):
    client.post("/register", data={"email": "metrics@example.com", "password": "password123", "level": "B1"})

    class TutorFailsAfterEvaluation(FakeGroq):
        def create(self, **kwargs):
            if kwargs.get("response_format", {}).get("type") == "json_object":
                return super().create(**kwargs)
            raise RuntimeError("tutor unavailable")

    monkeypatch.setattr("app.routes.Groq", TutorFailsAfterEvaluation)
    response = client.post("/api/chat", json={"content": "I enjoy learning English every day."})

    assert response.status_code == 503
    with app.app_context():
        metrics = db.session.scalars(db.select(ApiMetric)).all()
        assert any(metric.kind == "evaluator" and metric.status == "success" for metric in metrics)


def test_client_creation_failure_marks_turn_failed(client, app, monkeypatch):
    client.post("/register", data={"email": "client-failure@example.com", "password": "password123", "level": "B1"})

    def fail_client_creation(*args, **kwargs):
        raise RuntimeError("provider configuration missing")

    monkeypatch.setattr("app.routes.create_client", fail_client_creation)

    response = client.post("/api/chat", json={"content": "I enjoy learning English every day."})

    assert response.status_code == 503
    with app.app_context():
        turn = db.session.scalar(db.select(ChatTurn))
        assert turn.status == "failed"
        assert turn.tutor_status == "failed"
