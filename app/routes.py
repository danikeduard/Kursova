import logging
import uuid

from flask import Blueprint, current_app, jsonify, render_template, request, session

from .services.prompts import build_system_prompt
from .services.store import DatabaseUnavailableError

bp = Blueprint("main", __name__)
log = logging.getLogger(__name__)


def _sid() -> str:
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex
    return session["sid"]


@bp.get("/")
def index():
    return render_template("index.html")


@bp.post("/reset")
def reset():
    level = (request.get_json(silent=True) or {}).get("level", "beginner")
    try:
        current_app.extensions["store"].reset(_sid(), level)
    except DatabaseUnavailableError as exc:
        return jsonify({"error": str(exc)}), 503
    return jsonify({"ok": True})


@bp.post("/chat")
def chat():
    data = request.get_json(silent=True) or {}
    user_msg = (data.get("message") or "").strip()
    if not user_msg:
        return jsonify({"reply": "Порожнє повідомлення."}), 400

    llm = current_app.extensions["llm"]
    try:
        conv = current_app.extensions["store"].get(_sid())
    except DatabaseUnavailableError as exc:
        return jsonify({"reply": str(exc)}), 503
    limit = current_app.config["HISTORY_LIMIT"]

    is_analysis = user_msg.lower().startswith("/analysis")

    if is_analysis:
        report = current_app.extensions["store"].analysis_report(_sid())
        reply = (
            f"Поточний рівень: {report['level']}\n"
            f"Топ категорії помилок: {report['mistakes'] or 'даних ще немає'}\n"
            f"Останні спостереження: {report['history'][:5] or 'даних ще немає'}"
        )
        return jsonify({"reply": reply, "level": report["level"]})
    else:
        conv.history.append({"role": "user", "content": user_msg})

    profile = current_app.extensions["store"].profile_prompt(_sid())
    level = conv.level
    messages = [
        {"role": "system", "content": build_system_prompt(level, is_analysis, profile)},
        *conv.history[-limit:],
    ]

    try:
        reply = llm.complete(messages)
    except Exception:
        log.exception("LLM request failed")
        if not is_analysis:
            conv.history.pop()  # не зберігаємо повідомлення без відповіді
        return jsonify({"reply": "Помилка сервера. Спробуй ще раз пізніше."}), 500

    if not is_analysis:
        conv.history.append({"role": "assistant", "content": reply})
        try:
            current_app.extensions["store"].save(_sid(), conv)
        except DatabaseUnavailableError as exc:
            return jsonify({"reply": str(exc)}), 503
        current_app.extensions["analyzer"].enqueue(
            _sid(), user_msg, conv.history[-2]["content"] if len(conv.history) > 1 else ""
        )

    return jsonify({"reply": reply, "level": conv.level})
