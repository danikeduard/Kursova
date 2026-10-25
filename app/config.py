import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    DATABASE_URL = os.getenv("DATABASE_URL")

    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "30"))

    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    PORT = int(os.getenv("PORT", "5000"))
