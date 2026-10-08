import logging
import uuid

from flask import Blueprint, current_app, jsonify, render_template, request, session

from .services.prompts import build_system_prompt

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
    current_app.extensions["store"].reset(_sid(), level)
    return jsonify({"ok": True})


@bp.post("/chat")
def chat():
    data = request.get_json(silent=True) or {}
    user_msg = (data.get("message") or "").strip()
    if not user_msg:
        return jsonify({"reply": "Порожнє повідомлення."}), 400

    llm = current_app.extensions["llm"]
    conv = current_app.extensions["store"].get(_sid())
    limit = current_app.config["HISTORY_LIMIT"]

    is_analysis = user_msg.lower().startswith("/analysis")

    if is_analysis:
        if not conv.history:
            return jsonify({"reply": "Поки що немає діалогу для аналізу 🙂 Напиши щось англійською!"})
        level = conv.state.level
    else:
        level = conv.state.update(user_msg)
        conv.history.append({"role": "user", "content": user_msg})

    messages = [
        {"role": "system", "content": build_system_prompt(level, is_analysis)},
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

    return jsonify({"reply": reply, "level": level})
