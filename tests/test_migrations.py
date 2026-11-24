from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect

from app import create_app
from app.config import TestConfig
from app.extensions import db


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
