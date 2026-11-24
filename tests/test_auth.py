from app.extensions import db
from app.models import (
    Conversation,
    Feedback,
    Message,
    MessageFeedback,
    SkillRating,
    User,
    UserSettings,
)


def test_register_initializes_account_and_ratings(client, app):
    response = client.post("/register", data={"email": "learner@example.com", "password": "password123", "level": "B1"})
    assert response.status_code == 302
    with app.app_context():
        user = db.session.scalar(db.select(User).filter_by(email="learner@example.com"))
        assert user is not None
        ratings = db.session.scalars(db.select(SkillRating).filter_by(user_id=user.id)).all()
        assert {rating.skill for rating in ratings} == {"grammar", "vocab", "writing"}
        assert {rating.rating for rating in ratings} == {2500.0}


def test_login_rejects_bad_credentials(client):
    client.post("/register", data={"email": "learner@example.com", "password": "password123", "level": "A1"})
    response = client.post("/login", data={"email": "learner@example.com", "password": "wrongpass"})
    assert response.status_code == 200
    assert b"Invalid email or password" in response.data


def test_account_deletion_removes_all_user_owned_records(client, app):
    client.post("/register", data={"email": "delete@example.com", "password": "password123", "level": "B1"})
    conversation = client.post("/api/conversations", json={}).json["conversation"]
    with app.app_context():
        user = db.session.scalar(db.select(User).filter_by(email="delete@example.com"))
        settings = UserSettings(user_id=user.id)
        user_message = Message(
            user_id=user.id,
            conversation_id=conversation["id"],
            role="user",
            content="I enjoy reading books.",
        )
        db.session.add_all([settings, user_message])
        db.session.flush()
        db.session.add(
            MessageFeedback(
                user_id=user.id,
                message_id=user_message.id,
                rating="up",
            )
        )
        db.session.add(Feedback(user_id=user.id, sus_answers=["3"] * 10))
        db.session.commit()

    response = client.post("/account/delete")

    assert response.status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(User).filter_by(email="delete@example.com")) is None
        assert db.session.scalar(db.select(Conversation).where(Conversation.id == conversation["id"])) is None
        assert db.session.scalar(db.select(UserSettings).where(UserSettings.user_id == 1)) is None


def test_public_pages_load_the_stylesheet(client):
    page = client.get("/")
    assert page.status_code == 200
    assert b"Build confidence, one conversation at a time." in page.data
    assert b"Choose your starting level" in page.data
    assert b'href="/static/style.css"' in page.data
    stylesheet = client.get("/static/style.css")
    assert stylesheet.status_code == 200
    assert b".site-header" in stylesheet.data
    assert b".hero" in stylesheet.data


def test_registration_does_not_grant_admin_and_cli_can_promote(client, app):
    app.config["ADMIN_EMAILS"] = {"admin@example.com"}
    client.post("/register", data={"email": "admin@example.com", "password": "password123", "level": "B1"})
    with app.app_context():
        user = db.session.scalar(db.select(User).filter_by(email="admin@example.com"))
        assert user.is_admin is False

    result = app.test_cli_runner().invoke(args=["make-admin"], input="admin@example.com\n")

    assert result.exit_code == 0
    with app.app_context():
        user = db.session.scalar(db.select(User).filter_by(email="admin@example.com"))
        assert user.is_admin is True


def test_public_response_includes_security_headers(client):
    response = client.get("/")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
