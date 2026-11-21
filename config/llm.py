"""Single source of truth for LLM role configuration."""

import logging
from typing import Any

from flask import current_app

logger = logging.getLogger(__name__)

ROLES = ("tutor", "evaluator", "title", "explain")


def get_model(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"Unknown LLM role: {role}")
    config = current_app.config
    model = config["LLM_MODEL"] if role == "tutor" else config.get(f"LLM_MODEL_{role.upper()}", config["LLM_MODEL"])
    if not isinstance(model, str) or not model.strip():
        raise RuntimeError("LLM_MODEL must be configured with a non-empty model name.")
    return model.strip()


def get_max_tokens(role: str) -> int:
    if role not in ROLES:
        raise ValueError(f"Unknown LLM role: {role}")
    return int(current_app.config[f"LLM_MAX_TOKENS_{role.upper()}"])


def fallback_models() -> list[str]:
    return [item.strip() for item in current_app.config.get("LLM_MODEL_FALLBACKS", "").split(",") if item.strip()]


def reasoning_options(config: Any) -> dict[str, str]:
    value = str(config.get("LLM_REASONING_EFFORT", "")).strip().lower()
    if value not in {"low", "medium", "high"}:
        return {}
    return {"reasoning_effort": value}


def log_effective_models() -> None:
    for role in ROLES:
        logger.info("effective LLM model role=%s model=%s max_tokens=%s", role, get_model(role), get_max_tokens(role))
