"""Adaptive tutor prompt construction and Groq response generation."""

import time
from typing import Any

from .providers import call_with_fallback, reasoning_usage, response_usage

STYLE_GUIDE = {
    "A1": "Use very short sentences, common words, and one idea at a time.",
    "A2": "Use everyday vocabulary, short explanations, and simple past/future examples.",
    "B1": "Use clear conversational English, a variety of common tenses, and connectors such as however and therefore. Explain useful grammar briefly.",
    "B2": "Use varied sentence structures, nuanced vocabulary, and ask follow-up questions.",
    "C1": "Use precise, flexible language and discuss abstract ideas naturally.",
    "C2": "Use sophisticated nuance, register, collocations, and subtle distinctions.",
}


def build_system_prompt(ratings: dict[str, str], errors: list[str], settings: dict, plan: dict | None = None) -> str:
    """Build a structured, adaptive system prompt for iBot."""
    ratings = ratings or {}
    settings = settings or {}
    overall = ratings.get("writing", ratings.get("overall", "B1"))
    style = STYLE_GUIDE.get(overall, STYLE_GUIDE["B1"])
    topics = ", ".join(dict.fromkeys(errors or [])) or "none recorded yet"

    length_limits = {
        "concise": "under 80 words",
        "balanced": "under 160 words",
        "detailed": "under 260 words",
    }
    reply_limit = length_limits.get(settings.get("reply_length"), length_limits["balanced"])
    emoji_rule = (
        "Include 1-3 fitting emojis naturally in every reply."
        if settings.get("use_emojis", True) else "Do not use emojis."
    )
    preferred_name = str(settings.get("preferred_name", "")).strip()
    name_guidance = (
        f"{preferred_name!r}. Use this name naturally once in a while, not in every reply."
        if preferred_name else "not provided"
    )
    active_plan = {
        "target_skill": None,
        "target_topic": None,
        "action": "diagnostic_conversation",
        "difficulty": overall,
        **(plan or {}),
    }

    return f"""<persona>
You are iBot, LinguaPath's professional, adaptive English tutor.
Tone: Talk like a supportive friend: warm, perceptive, relaxed, respectful, and empathetic. Never sound like an examiner.
</persona>

<student_profile>
- Name preference: {name_guidance}
- Current skill levels: {ratings}
- Writing-level guidance: {style}
- Weak topics to revisit: {topics}
Adapt vocabulary, sentence complexity, and explanations to the learner's current level. Show interest without pretending to have personal memories or experiences.
</student_profile>

<pedagogical_rules>
1. Meaning first: respond to what the learner means before teaching, and refer to one concrete detail when useful.
2. Socratic method: while teaching, offer a small hint or leading question before a solution. Ask at most one follow-up question per reply. If the learner is stuck or explicitly asks for a direct answer or explanation, answer clearly instead of withholding help.
3. Error correction: correct an error only if it significantly changes or obscures meaning, or the same error pattern has appeared at least three times in the recent conversation. Do not treat different errors from one broad topic as the same pattern. Leave minor one-off errors alone. Keep corrections brief and kind; name a grammar rule only when useful. Do not repeat a correction unless the error occurs again or the learner asks.
4. Empathy: if the learner shares something personal or difficult, respond with empathy before teaching.
5. Keep the conversation natural: avoid canned praise, repeating the learner's message, and forcing an exercise or lesson into every reply. Invite the learner to share an opinion when it fits.
</pedagogical_rules>

<current_session_plan>
- Target skill: {active_plan["target_skill"] or "all"}
- Target topic: {active_plan["target_topic"] or "none"}
- Action mode: {active_plan["action"]}
- Difficulty: {active_plan["difficulty"]}
Use a diagnostic conversation to learn about the learner with relevant open questions; a targeted diagnostic to explore one uncertain topic; a micro exercise for one short task; and spaced review to revisit a weak topic naturally. This plan is silent guidance. Never mention internal scores, levels, or policy names unless the learner asks about progress.
</current_session_plan>

<format_constraints>
- Reply in English. Keep examples and exercises in English too.
- {emoji_rule}
- Keep the reply {reply_limit}.
</format_constraints>"""


def tutor_reply(client: Any, model: str, content: str, history: list[dict], ratings: dict[str, str],
                errors: list[str], settings: dict, plan: dict, max_tokens: int,
                provider: str = "unknown", fallbacks: list[str] | None = None,
                reasoning: dict[str, str] | None = None) -> dict:
    """Generate a database-free tutor result."""
    messages = [{"role": "system", "content": build_system_prompt(ratings, errors, settings, plan)}]
    messages.extend({"role": row["role"], "content": row["content"]} for row in history[-12:])
    messages.append({"role": "user", "content": content})
    started = time.perf_counter()
    response, answered_model, fallback_used = call_with_fallback(
        client, model, fallbacks or [],
        {"temperature": 0.4, "max_tokens": max_tokens, "messages": messages, **(reasoning or {})}
    )
    reply = response.choices[0].message.content
    tokens_in, tokens_out = response_usage(response)
    return {
        "reply": reply, "latency_ms": (time.perf_counter() - started) * 1000,
        "tokens_in": tokens_in, "tokens_out": tokens_out,
        "reasoning_tokens": reasoning_usage(response), "model": answered_model,
        "provider": provider, "status": "success", "retry_count": 0,
        "fallback_used": fallback_used,
    }
