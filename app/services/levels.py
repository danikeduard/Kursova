"""Pure CEFR adaptation math and analyzer payload validation."""

from __future__ import annotations

import json
import math
import re
import statistics
from typing import Any, Iterable, Mapping

LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
LEVEL_TO_NUMBER = {name: index for index, name in enumerate(LEVELS, 1)}
WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")


def clamp(value: float, low: float = 1.0, high: float = 6.0) -> float:
    return max(low, min(high, float(value)))


def compute_ttr(text: str) -> float:
    tokens = [token.lower() for token in WORD_RE.findall(text)]
    return len(set(tokens)) / len(tokens) if tokens else 0.0


def cyrillic_ratio(text: str) -> float:
    letters = re.findall(r"[A-Za-z\u0400-\u04ff]", text)
    return sum(bool(CYRILLIC_RE.fullmatch(char)) for char in letters) / len(letters) if letters else 0.0


def ngram_overlap(text: str, previous: str, n: int = 3) -> float:
    def grams(value: str) -> set[tuple[str, ...]]:
        words = [word.lower() for word in WORD_RE.findall(value)]
        return {tuple(words[index:index + n]) for index in range(len(words) - n + 1)}
    current, old = grams(text), grams(previous)
    return len(current & old) / len(current) if current else 0.0


def reliability(word_count: int) -> float:
    return min(1.0, max(0, word_count) / 30.0)


def kalman_update(mu: float, sigma2: float, observation: float, word_count: int,
                  task_difficulty: float = 1.0, r0: float = 0.5,
                  q: float = 0.0) -> tuple[float, float]:
    r_t = reliability(word_count)
    noise = r0 / (max(r_t, 0.05) * max(0.01, task_difficulty))
    prior = max(0.0, sigma2) + q
    gain = prior / (prior + noise)
    return clamp(mu + gain * (observation - mu)), max(0.0, (1 - gain) * prior)


def level_from_mu(mu: float) -> str:
    return LEVELS[max(0, min(5, int(math.floor(clamp(mu) + 0.5)) - 1))]


def hysteresis_level(mu: float, sigma2: float, shown_level: str,
                     msgs_since_change: int, margin: float = 0.25,
                     max_sigma2: float = 0.5,
                     required_messages: int = 5) -> tuple[str, int]:
    current = LEVEL_TO_NUMBER.get(shown_level, 2)
    candidate = int(math.floor(clamp(mu) + 0.5))
    beyond = (mu >= current + 0.5 + margin or mu <= current - 0.5 - margin)
    if candidate != current and beyond and sigma2 < max_sigma2 and msgs_since_change >= required_messages:
        return LEVELS[candidate - 1], 0
    return shown_level if shown_level in LEVEL_TO_NUMBER else LEVELS[current - 1], msgs_since_change + 1


def error_weight(severity: str, structure_level: int, grammar_mu: float,
                 category: str, is_typo: bool = False) -> float:
    if is_typo or (category == "spelling" and severity == "low"):
        return 0.0
    severity_factor = {"low": 0.5, "medium": 1.0, "high": 1.5}.get(severity, 1.0)
    if structure_level > grammar_mu + 0.5:
        level_factor = 0.3
    elif structure_level <= grammar_mu:
        level_factor = 1.0 + 0.25 * (grammar_mu - structure_level)
    else:
        level_factor = 1.0
    return severity_factor * level_factor


def decay_weights(weights: Mapping[str, float], decay: float = 0.9) -> dict[str, float]:
    return {category: float(value) * decay for category, value in weights.items()}


def _percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 1.0
    position = (len(ordered) - 1) * percentile
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def obs_grammar(features: Mapping[str, Any], analysis: Mapping[str, Any],
                error_total: float = 0.0) -> float:
    structures = [item["level"] for item in analysis.get("structures_correct", [])
                  if isinstance(item, dict) and isinstance(item.get("level"), (int, float))]
    base = _percentile(structures, 0.75) if structures else clamp(float(features.get("avg_sentence_len", 1)) / 5 + 1)
    words = max(1, int(features.get("word_count", 0)))
    return clamp(base - error_total / words * 100 * 0.02)


def obs_vocab(features: Mapping[str, Any], analysis: Mapping[str, Any]) -> float:
    levels = [LEVEL_TO_NUMBER.get(str(item.get("cefr", "")).upper())
              for item in analysis.get("words", []) if isinstance(item, dict)]
    levels = [level for level in levels if level]
    base = statistics.mean(sorted(levels)[len(levels) // 2:]) if levels else 2.0
    return clamp(base + (compute_ttr(str(features.get("text", ""))) - 0.5) * 0.6)


def obs_fluency(features: Mapping[str, Any], analysis: Mapping[str, Any]) -> float:
    sentence_length = float(features.get("avg_sentence_len", 0))
    word_count = int(features.get("word_count", 0))
    return clamp(1.0 + min(3.0, sentence_length / 6) + min(1.0, word_count / 80))


def sanitize_analyzer_json(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if not isinstance(value, dict):
        return None
    categories = {"tense", "article", "preposition", "word_order", "vocabulary",
                  "spelling", "agreement", "punctuation", "other"}
    errors = []
    for item in value.get("errors", []):
        if not isinstance(item, dict) or item.get("category") not in categories:
            continue
        try:
            structure_level = int(item.get("structure_level", 2))
        except (TypeError, ValueError):
            structure_level = 2
        errors.append({
            "category": item["category"], "original": str(item.get("original", ""))[:500],
            "corrected": str(item.get("corrected", ""))[:500],
            "severity": item.get("severity") if item.get("severity") in {"low", "medium", "high"} else "medium",
            "structure_level": max(1, min(6, structure_level)),
            "is_typo": bool(item.get("is_typo", False)),
        })
    structures = []
    for item in value.get("structures_correct", []):
        if isinstance(item, dict):
            try:
                level = int(item.get("level", 2))
            except (TypeError, ValueError):
                level = 2
            structures.append({"name": str(item.get("name", ""))[:100], "level": max(1, min(6, level))})
    words = [{"word": str(item.get("word", ""))[:80], "cefr": str(item.get("cefr", "")).upper()}
             for item in value.get("words", [])[:15]
             if isinstance(item, dict) and str(item.get("cefr", "")).upper() in LEVEL_TO_NUMBER]
    try:
        difficulty = max(0.5, min(1.5, float(value.get("task_difficulty", 1.0))))
        estimate = max(1, min(6, float(value.get("overall_estimate", 2.0))))
    except (TypeError, ValueError):
        return None
    return {"errors": errors, "structures_correct": structures, "words": words,
            "topic": str(value.get("topic", ""))[:120], "task_difficulty": difficulty,
            "overall_estimate": estimate}


def extract_json_object(value: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", value):
        try:
            parsed, _ = decoder.raw_decode(value[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None
