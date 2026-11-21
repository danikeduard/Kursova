"""Deterministic validation for incoming chat messages and rating eligibility."""

import re
import unicodedata
from dataclasses import dataclass

DEFAULT_MAX_MESSAGE_CHARS = 4000
MIN_ASSESSMENT_WORDS = 3

_ENGLISH_WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_CODE = re.compile(r"```[\s\S]*?(?:```|$)|`[^`\n]*`")
_BLOCKQUOTE = re.compile(r"(?m)^\s*>[^\n]*$")
_COMMAND = re.compile(r"^/[A-Za-z][A-Za-z0-9_-]*(?:\s|$)")


@dataclass(frozen=True)
class MessageValidation:
    """Normalized chat text or a safe, user-facing validation error."""

    content: str | None
    error: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.content is not None and self.error is None


@dataclass(frozen=True)
class AssessmentEligibility:
    """Whether a message has enough learner-authored English for assessment."""

    eligible: bool
    word_count: int
    reason: str | None = None


def _browser_character_count(value: str) -> int:
    """Match HTML maxlength, which counts UTF-16 code units rather than code points."""
    return sum(2 if ord(char) > 0xFFFF else 1 for char in value)


def validate_chat_content(value: object, max_chars: int = DEFAULT_MAX_MESSAGE_CHARS) -> MessageValidation:
    """Validate, normalize, and bound chat content before persistence or API calls."""
    if not isinstance(value, str):
        return MessageValidation(None, "Message must be text.")
    if _browser_character_count(value) > max_chars:
        return MessageValidation(None, f"Please send a message with no more than {max_chars:,} characters.")

    content = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not content:
        return MessageValidation(None, "Please enter a message.")
    if _browser_character_count(content) > max_chars:
        return MessageValidation(None, f"Please send a message with no more than {max_chars:,} characters.")
    if any(
        unicodedata.category(char) in {"Cc", "Cs"} and char not in "\n\t"
        for char in content
    ):
        return MessageValidation(None, "The message contains unsupported control characters.")
    return MessageValidation(content)


def assessment_text(content: str) -> str:
    """Remove obvious non-prose before counting evidence for an assessment."""
    text = _BLOCKQUOTE.sub(" ", content)
    text = _CODE.sub(" ", text)
    text = _URL.sub(" ", text)
    return _EMAIL.sub(" ", text)


def assessment_word_count(content: str) -> int:
    """Count English words after excluding code, URLs, email, and quote blocks."""
    return len(_ENGLISH_WORD.findall(assessment_text(content)))


def assessability(content: str) -> AssessmentEligibility:
    """Decide whether to call the evaluator; mixed-language text is left to it."""
    text = content.strip()
    if _COMMAND.match(text):
        return AssessmentEligibility(False, 0, "command")

    words = assessment_word_count(text)
    if words < MIN_ASSESSMENT_WORDS:
        return AssessmentEligibility(False, words, "insufficient_english_words")
    return AssessmentEligibility(True, words)
