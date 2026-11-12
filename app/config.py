"""Application configuration loaded from environment variables."""

import os
from datetime import timedelta
from pathlib import Path
from typing import ClassVar

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTANCE_DIR = PROJECT_ROOT / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)
DEFAULT_SQLITE_URI = f"sqlite:///{INSTANCE_DIR / 'linguapath.db'}"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", DEFAULT_SQLITE_URI)
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql+psycopg2://", 1)
    elif SQLALCHEMY_DATABASE_URI.startswith("postgresql://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgresql://", "postgresql+psycopg2://", 1)
    if SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
        SQLALCHEMY_ENGINE_OPTIONS: ClassVar[dict] = {
            "connect_args": {"check_same_thread": False, "timeout": 15},
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS: ClassVar[dict] = {"pool_pre_ping": True, "pool_recycle": 1800}
    APP_ENV = os.environ.get("APP_ENV", "development").lower()
    SESSION_COOKIE_SECURE = os.environ.get(
        "SESSION_COOKIE_SECURE", "true" if APP_ENV == "production" else "false"
    ).lower() == "true"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    WTF_CSRF_TIME_LIMIT = None
    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "groq")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    DAILY_MESSAGE_CAP = int(os.environ.get("DAILY_MESSAGE_CAP", "50"))
    RATE_LIMIT_CHAT = os.environ.get("RATE_LIMIT_CHAT", "30 per minute")
    TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "0"))
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", str(64 * 1024)))
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
    RATING_MODE = os.environ.get("RATING_MODE", "kalman")
    DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"
    LLM_COST_PER_1K_INPUT_USD = float(os.environ.get("LLM_COST_PER_1K_INPUT_USD", "0"))
    LLM_COST_PER_1K_OUTPUT_USD = float(os.environ.get("LLM_COST_PER_1K_OUTPUT_USD", "0"))
    LLM_MODEL_FALLBACKS = os.environ.get("LLM_MODEL_FALLBACKS", "")
    LLM_MAX_TOKENS_TUTOR = int(os.environ.get("LLM_MAX_TOKENS_TUTOR", "512"))
    LLM_MAX_TOKENS_EVALUATOR = int(os.environ.get("LLM_MAX_TOKENS_EVALUATOR", "1024"))
    LLM_MAX_TOKENS_TITLE = int(os.environ.get("LLM_MAX_TOKENS_TITLE", "16"))
    LLM_MAX_TOKENS_EXPLAIN = int(os.environ.get("LLM_MAX_TOKENS_EXPLAIN", "256"))
    LLM_REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "")


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-secret-key"
    GROQ_API_KEY = "test-key"
    RATELIMIT_ENABLED = False
    LLM_MODEL = "test-model"
