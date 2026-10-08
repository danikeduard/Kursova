from flask import Flask

from .config import Config
from .services.llm import LLMClient
from .services.store import SessionStore


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    # Сервіси живуть в app.extensions, щоб роути не створювали їх самі
    app.extensions["llm"] = LLMClient(
        api_key=app.config["GROQ_API_KEY"],
        model=app.config["GROQ_MODEL"],
    )
    app.extensions["store"] = SessionStore()

    from .routes import bp

    app.register_blueprint(bp)
    return app
