"""LinguaPath Flask application factory."""

import logging
import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from flask import Flask
from flask.cli import with_appcontext
from groq import APIError
from werkzeug.middleware.proxy_fix import ProxyFix

from .extensions import csrf, db, limiter, login_manager, migrate
from .i18n import install_i18n


def create_app(config_class=None) -> Flask:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not getattr(config_class, "TESTING", False):
        dotenv = dotenv_values(env_path)
        for name in ("LLM_MODEL", "LLM_MODEL_EVALUATOR", "LLM_MODEL_TITLE", "LLM_MODEL_EXPLAIN"):
            if name in os.environ and dotenv.get(name) and os.environ[name] != dotenv[name]:
                logging.getLogger(__name__).warning("OS environment %s differs from %s", name, env_path.resolve())
        load_dotenv(env_path, override=False)
    from .config import Config

    config_class = config_class or Config
    app = Flask(__name__)
    app.config.from_object(config_class)
    if not getattr(config_class, "TESTING", False):
        app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
        app.config["GROQ_API_KEY"] = os.environ.get("GROQ_API_KEY")
        app.config["LLM_PROVIDER"] = os.environ.get("LLM_PROVIDER", app.config["LLM_PROVIDER"])
    model = (app.config.get("LLM_MODEL") if getattr(config_class, "TESTING", False)
             else os.environ.get("LLM_MODEL", "")).strip()
    if not model:
        raise RuntimeError("LLM_MODEL must be configured with a non-empty model name.")
    app.config["LLM_MODEL"] = model
    for role in ("EVALUATOR", "TITLE", "EXPLAIN"):
        app.config[f"LLM_MODEL_{role}"] = os.environ.get(f"LLM_MODEL_{role}", model).strip() or model
    app.config["ENV_FILE_PATH"] = str(env_path.resolve())
    logging.getLogger(__name__).info("dotenv file=%s", env_path.resolve())
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be configured")
    trusted_proxy_count = app.config.get("TRUSTED_PROXY_COUNT", 0)
    if trusted_proxy_count < 0:
        raise RuntimeError("TRUSTED_PROXY_COUNT cannot be negative")
    if app.config.get("APP_ENV") == "production" and app.config.get("RATELIMIT_STORAGE_URI", "memory://") == "memory://":
        raise RuntimeError("Production deployments must configure shared RATELIMIT_STORAGE_URI storage")
    if trusted_proxy_count:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=trusted_proxy_count, x_proto=trusted_proxy_count)
    if app.config.get("APP_ENV") == "production" and not getattr(config_class, "TESTING", False):
        secret = app.config["SECRET_KEY"]
        if len(secret) < 32 or secret == "replace-with-a-long-random-secret":
            raise RuntimeError("Production SECRET_KEY must contain at least 32 non-placeholder characters")

    db.init_app(app)
    install_i18n(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    from config.llm import get_model, log_effective_models
    with app.app_context():
        log_effective_models()
    if not app.config.get("TESTING") and not app.config.get("DEMO_MODE") and app.config.get("GROQ_API_KEY"):
        try:
            from groq import Groq
            available = {item.id for item in Groq(api_key=app.config["GROQ_API_KEY"]).models.list().data}
            for role in ("tutor", "evaluator", "title", "explain"):
                with app.app_context():
                    configured = get_model(role)
                if configured not in available:
                    logging.getLogger(__name__).warning("configured LLM model is unavailable role=%s model=%s", role, configured)
        except (APIError, OSError, RuntimeError, ValueError) as error:
            logging.getLogger(__name__).warning("could not check Groq model availability: %s", type(error).__name__)

    from .auth import auth_bp
    from .routes import main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    @app.cli.command("make-admin")
    @with_appcontext
    def make_admin_command():
        """Promote one existing user by email from a trusted CLI session."""
        import click

        email = click.prompt("Account email").strip().lower()
        user = db.session.scalar(db.select(models.User).filter_by(email=email))
        if user is None:
            raise click.ClickException("No account exists with that email.")
        user.is_admin = True
        db.session.commit()
        click.echo("Administrator access granted.")

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    return app


from . import models
