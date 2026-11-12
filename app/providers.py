"""OpenAI-compatible chat provider construction."""

import logging
from typing import Any

from groq import APIError, Groq
from openai import OpenAI

logger = logging.getLogger(__name__)


def call_with_fallback(client: Any, model: str, fallbacks: list[str], kwargs: dict[str, Any]) -> tuple[Any, str, bool]:
    from config.llm import ROLES, fallback_models, get_model

    configured_models = {get_model(role) for role in ROLES}
    if model not in configured_models:
        raise ValueError("LLM model was not resolved from server configuration.")
    configured_fallbacks = fallback_models()
    if fallbacks != configured_fallbacks:
        raise ValueError("LLM fallbacks must come from server configuration.")
    candidates = [model] + [item for item in configured_fallbacks if item != model]
    for index, candidate in enumerate(candidates):
        try:
            return client.chat.completions.create(model=candidate, **kwargs), candidate, index > 0
        except (APIError, OSError) as error:
            status = getattr(error, "status_code", None)
            retryable = status in {404, 429} or isinstance(status, int) and status >= 500
            if not retryable or index == len(candidates) - 1:
                raise
            logger.warning(
                "LLM fallback primary=%s fallback=%s reason=%s",
                model, candidates[index + 1], status or type(error).__name__,
            )


class _DemoResponse:
    def __init__(self, content: str, prompt_tokens: int = 80, completion_tokens: int = 40):
        self.choices = [type("Choice", (), {"message": type("Message", (), {"content": content})()})()]
        self.usage = type(
            "Usage",
            (),
            {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        )()


class DemoClient:
    """Deterministic provider used for local demos without an API key."""

    def __init__(self, **kwargs: Any):
        self.chat = type("Chat", (), {"completions": type("Completions", (), {"create": self.create})()})()

    def create(self, **kwargs: Any) -> _DemoResponse:
        response_type = kwargs.get("response_format", {}).get("type")
        if response_type in {"json_object", "json_schema"}:
            content = (
                '{"is_english": true, '
                '"skills": {"grammar": {"level": "B1", "confidence": 0.65}, '
                '"vocab": {"level": "B1", "confidence": 0.6}, '
                '"writing": {"level": "B1", "confidence": 0.55}}, '
                '"errors": [], "strengths": []}'
            )
        else:
            content = "Nice work. Tell me one more detail, and try using a longer sentence."
        return _DemoResponse(content)


def response_usage(response: Any) -> tuple[int | None, int | None]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None
    return getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)


def reasoning_usage(response: Any) -> int | None:
    details = getattr(getattr(response, "usage", None), "completion_tokens_details", None)
    return getattr(details, "reasoning_tokens", None) if details is not None else None


def estimated_cost(config: Any, tokens_in: int | None, tokens_out: int | None) -> float | None:
    if tokens_in is None and tokens_out is None:
        return None
    input_cost = (tokens_in or 0) / 1000 * config.get("LLM_COST_PER_1K_INPUT_USD", 0)
    output_cost = (tokens_out or 0) / 1000 * config.get("LLM_COST_PER_1K_OUTPUT_USD", 0)
    return input_cost + output_cost


def create_client(
    config: Any,
    provider: str | None = None,
    groq_client: Any = Groq,
    openai_client: Any = OpenAI,
) -> Any:
    """Create a provider client without exposing provider secrets to users."""
    if config.get("DEMO_MODE"):
        return DemoClient()
    selected = provider or config.get("LLM_PROVIDER", "groq")
    if selected == "groq":
        if not config.get("GROQ_API_KEY"):
            raise RuntimeError("GROQ_API_KEY is not configured.")
        return groq_client(api_key=config["GROQ_API_KEY"])
    if selected == "openai":
        if not config.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        return openai_client(api_key=config["OPENAI_API_KEY"], base_url=config["OPENAI_BASE_URL"])
    raise ValueError("Unsupported LLM provider.")
