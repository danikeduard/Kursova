from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import SkillRating, User
from werkzeug.security import check_password_hash


def test_server_configured_llm_migration_is_reversible():
    app = create_app(TestConfig)
    with app.app_context():
        upgrade()
        columns = {column["name"] for column in inspect(db.engine).get_columns("app_user_settings")}
        assert not {"model", "provider", "ui_language"} & columns

        downgrade(revision="20261112_llm_metric_details")
        restored = {
            column["name"]: column
            for column in inspect(db.engine).get_columns("app_user_settings")
        }
        assert all(restored[name]["nullable"] for name in ("model", "provider", "ui_language"))


def test_displayed_level_migration_is_reversible():
    app = create_app(TestConfig)
    with app.app_context():
        upgrade()
        rating_columns = {column["name"] for column in inspect(db.engine).get_columns("app_skill_rating")}
        event_columns = {column["name"] for column in inspect(db.engine).get_columns("app_rating_event")}
        turn_columns = {column["name"] for column in inspect(db.engine).get_columns("app_chat_turn")}
        assert "display_level" in rating_columns
        assert "display_level" in event_columns
        assert {"learning_action", "target_skill", "target_topic"} <= turn_columns

        downgrade(revision="20261112_server_configured_llm")
        rating_columns = {column["name"] for column in inspect(db.engine).get_columns("app_skill_rating")}
        event_columns = {column["name"] for column in inspect(db.engine).get_columns("app_rating_event")}
        turn_columns = {column["name"] for column in inspect(db.engine).get_columns("app_chat_turn")}
        assert "display_level" not in rating_columns
        assert "display_level" not in event_columns
        assert not {"learning_action", "target_skill", "target_topic"} & turn_columns


def test_seed_demo_users_migration_creates_accounts():
    app = create_app(TestConfig)
    with app.app_context():
        upgrade()

        admin = db.session.scalar(db.select(User).filter_by(email="admin"))
        standard_user = db.session.scalar(db.select(User).filter_by(email="user"))
        assert admin is not None
        assert admin.is_admin is True
        assert check_password_hash(admin.password_hash, "admin")
        assert standard_user is not None
        assert standard_user.is_admin is False
        assert check_password_hash(standard_user.password_hash, "user")

        for user in (admin, standard_user):
            ratings = db.session.scalars(
                db.select(SkillRating).filter_by(user_id=user.id)
            ).all()
            assert {rating.skill for rating in ratings} == {"grammar", "vocab", "writing"}
