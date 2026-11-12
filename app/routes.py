"""Public pages and chat API."""

import base64
import csv
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from groq import APIError, Groq
from sqlalchemy.exc import OperationalError

from config.llm import get_max_tokens, get_model, reasoning_options

from .evaluator import evaluate_message
from .extensions import db, limiter
from .learning import topic_recommendations, update_topic_mastery
from .level_service import event_from_update, update_skill
from .models import (
    ApiMetric,
    ChatTurn,
    Conversation,
    ErrorLog,
    Feedback,
    LevelChange,
    Message,
    MessageFeedback,
    RatingEvent,
    SkillRating,
    TopicMastery,
    User,
    UserSettings,
)
from .pedagogy import select_learning_plan
from .providers import create_client
from .rating import (
    displayed_level,
    is_valid_message,
    level_to_rating,
    overall_rating,
    rating_to_level,
)

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index():
    return render_template("index.html")


@main_bp.get("/chat")
@login_required
def chat():
    return render_template("chat.html", conversation_id=None, preferred_name=_preferred_name(), sidebar_mode="chat")


@main_bp.get("/chat/<int:conversation_id>")
@login_required
def conversation_page(conversation_id: int):
    conversation = _conversation_or_404(conversation_id)
    return render_template("chat.html", conversation_id=conversation.id, preferred_name=_preferred_name(), sidebar_mode="chat")


def _preferred_name() -> str:
    settings = db.session.get(UserSettings, current_user.id)
    return settings.preferred_name.strip() if settings and settings.preferred_name.strip() else "Learner"


def _conversation_or_404(conversation_id: int) -> Conversation:
    conversation = db.session.scalar(
        db.select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    if conversation is None:
        from werkzeug.exceptions import NotFound

        raise NotFound()
    return conversation


def _conversation_json(conversation: Conversation) -> dict:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "title_auto": conversation.title_auto,
        "pinned": conversation.pinned,
        "archived": conversation.archived,
        "folder": conversation.folder,
        "tags": conversation.tags or [],
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }


def _unique_conversation_title(user_id: int, title: str, exclude_id: int | None = None) -> str:
    """Return a per-user unique conversation title, adding a numeric suffix if needed."""
    base_title = title.strip()[:200]

    def title_exists(candidate: str) -> bool:
        conditions = [
            Conversation.user_id == user_id,
            db.func.lower(Conversation.title) == candidate.lower(),
        ]
        if exclude_id is not None:
            conditions.append(Conversation.id != exclude_id)
        return bool(db.session.scalar(db.select(db.exists().where(*conditions))))

    if not title_exists(base_title):
        return base_title

    suffix_number = 2
    while True:
        suffix = f" ({suffix_number})"
        candidate = f"{base_title[:200 - len(suffix)].rstrip()}{suffix}"
        if not title_exists(candidate):
            return candidate
        suffix_number += 1


@main_bp.get("/api/conversations")
@login_required
def list_conversations():
    archived = request.args.get("archived", "0") == "1"
    limit = min(max(request.args.get("limit", 30, type=int), 1), 100)
    query = request.args.get("q", "").strip()
    statement = db.select(Conversation).where(
        Conversation.user_id == current_user.id,
        Conversation.archived.is_(archived),
    )
    if query:
        escaped_query = query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        pattern = f"%{escaped_query}%"
        statement = statement.where(
            db.or_(
                Conversation.title.ilike(pattern, escape="!"),
                db.exists(
                    db.select(Message.id).where(
                        Message.conversation_id == Conversation.id,
                        Message.content.ilike(pattern, escape="!"),
                    )
                ),
            )
        )
    statement = statement.order_by(Conversation.pinned.desc(), Conversation.updated_at.desc(), Conversation.id.desc())
    cursor = request.args.get("cursor")
    if cursor:
        try:
            pinned_text, updated_text, id_text = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode().split("|", 2)
            cursor_pinned = pinned_text == "1"
            cursor_updated = datetime.fromisoformat(updated_text)
            cursor_id = int(id_text)
        except (ValueError, TypeError):
            return jsonify(error="Invalid cursor."), 400
        older_pin_group = Conversation.pinned.is_(False) if cursor_pinned else db.false()
        statement = statement.where(db.or_(
            older_pin_group,
            db.and_(Conversation.pinned == cursor_pinned, Conversation.updated_at < cursor_updated),
            db.and_(Conversation.pinned == cursor_pinned, Conversation.updated_at == cursor_updated,
                    Conversation.id < cursor_id),
        ))
    items = db.session.scalars(statement.limit(limit + 1)).all()
    next_cursor = None
    if len(items) > limit:
        last = items[limit - 1]
        raw_cursor = f"{int(last.pinned)}|{last.updated_at.isoformat()}|{last.id}".encode()
        next_cursor = base64.urlsafe_b64encode(raw_cursor).decode().rstrip("=")
    return jsonify(items=[_conversation_json(item) for item in items[:limit]], next_cursor=next_cursor)


@main_bp.post("/api/conversations")
@login_required
def create_conversation():
    active_count = db.session.scalar(
        db.select(db.func.count(Conversation.id)).where(
            Conversation.user_id == current_user.id, Conversation.archived.is_(False)
        )
    )
    if active_count >= 200:
        return jsonify(error="You can have at most 200 active conversations."), 409
    conversation = Conversation(
        user_id=current_user.id,
        title=_unique_conversation_title(current_user.id, "New chat"),
    )
    db.session.add(conversation)
    db.session.commit()
    return jsonify(conversation=_conversation_json(conversation)), 201


@main_bp.patch("/api/conversations/<int:conversation_id>")
@login_required
def update_conversation(conversation_id: int):
    conversation = _conversation_or_404(conversation_id)
    payload = request.get_json(silent=True) or {}
    if "title" in payload:
        title = payload["title"]
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
            return jsonify(error="Title must contain 1 to 200 characters."), 400
        conversation.title = _unique_conversation_title(
            current_user.id, title, exclude_id=conversation.id
        )
        conversation.title_auto = False
    for field in ("pinned", "archived"):
        if field in payload:
            if not isinstance(payload[field], bool):
                return jsonify(error=f"{field} must be a boolean."), 400
            setattr(conversation, field, payload[field])
    if "folder" in payload:
        folder = payload["folder"]
        if folder is not None and (not isinstance(folder, str) or len(folder.strip()) > 80):
            return jsonify(error="Folder must be under 80 characters."), 400
        conversation.folder = folder.strip() if isinstance(folder, str) and folder.strip() else None
    if "tags" in payload:
        tags = payload["tags"]
        if not isinstance(tags, list) or not all(isinstance(tag, str) and 0 < len(tag.strip()) <= 32 for tag in tags):
            return jsonify(error="Tags must be a list of non-empty strings under 32 characters."), 400
        conversation.tags = list(dict.fromkeys(tag.strip().lower() for tag in tags))[:20]
    db.session.commit()
    return jsonify(conversation=_conversation_json(conversation))


@main_bp.delete("/api/conversations/<int:conversation_id>")
@login_required
def delete_conversation(conversation_id: int):
    conversation = _conversation_or_404(conversation_id)
    message_ids = db.select(Message.id).where(Message.conversation_id == conversation.id)
    db.session.execute(
        db.update(RatingEvent)
        .where(RatingEvent.message_id.in_(message_ids))
        .values(message_id=None)
    )
    db.session.delete(conversation)
    db.session.commit()
    return "", 204


@main_bp.post("/api/conversations/<int:conversation_id>/duplicate")
@login_required
def duplicate_conversation(conversation_id: int):
    source = _conversation_or_404(conversation_id)
    active_count = db.session.scalar(
        db.select(db.func.count(Conversation.id)).where(
            Conversation.user_id == current_user.id, Conversation.archived.is_(False)
        )
    )
    if active_count >= 200:
        return jsonify(error="You can have at most 200 active conversations."), 409
    copy = Conversation(
        user_id=current_user.id,
        title=_unique_conversation_title(current_user.id, f"{source.title} (copy)"),
        title_auto=False,
    )
    db.session.add(copy)
    db.session.flush()
    source_messages = db.session.scalars(
        db.select(Message).where(Message.conversation_id == source.id).order_by(Message.ts, Message.id).limit(300)
    ).all()
    for source_message in source_messages:
        db.session.add(
            Message(
                user_id=current_user.id,
                conversation_id=copy.id,
                role=source_message.role,
                content=source_message.content,
                is_valid_for_rating=False,
                msg_index=None,
            )
        )
    db.session.commit()
    return jsonify(conversation=_conversation_json(copy)), 201


@main_bp.get("/api/conversations/<int:conversation_id>/export")
@login_required
def export_conversation(conversation_id: int):
    conversation = _conversation_or_404(conversation_id)
    messages = db.session.scalars(
        db.select(Message).where(Message.conversation_id == conversation.id).order_by(Message.ts, Message.id)
    ).all()
    export_format = request.args.get("format", "json").lower()
    if export_format == "markdown":
        lines = [f"# {conversation.title}", ""]
        for message in messages:
            lines.extend([f"## {'You' if message.role == 'user' else 'Tutor'}", "", message.content, ""])
        return Response(
            "\n".join(lines),
            mimetype="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="conversation-{conversation.id}.md"'},
        )
    if export_format != "json":
        return jsonify(error="Format must be json or markdown."), 400
    payload = {
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "messages": [
            {"role": message.role, "content": message.content, "timestamp": message.ts.isoformat()}
            for message in messages
        ],
    }
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="conversation-{conversation.id}.json"'},
    )


@main_bp.get("/api/conversations/<int:conversation_id>/messages")
@login_required
def conversation_messages(conversation_id: int):
    conversation = _conversation_or_404(conversation_id)
    limit = min(max(request.args.get("limit", 50, type=int), 1), 100)
    statement = db.select(Message).where(
        Message.conversation_id == conversation.id,
        Message.user_id == current_user.id,
    ).order_by(Message.ts.desc(), Message.id.desc())
    before = request.args.get("before", type=int)
    if before:
        statement = statement.where(Message.id < before)
    rows = db.session.scalars(statement.limit(limit + 1)).all()
    next_cursor = rows[limit].id if len(rows) > limit else None
    feedback_by_message = {
        feedback.message_id: feedback.rating
        for feedback in db.session.scalars(
            db.select(MessageFeedback).where(
                MessageFeedback.message_id.in_([row.id for row in rows[:limit]])
            )
        ).all()
    }
    return jsonify(
        messages=[
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "timestamp": row.ts.isoformat(),
                "msg_index": row.msg_index,
                "feedback": feedback_by_message.get(row.id),
            }
            for row in reversed(rows[:limit])
        ],
        next_cursor=next_cursor,
    )


@main_bp.get("/api/settings")
@login_required
def get_settings():
    settings = db.session.get(UserSettings, current_user.id)
    if settings is None:
        settings = UserSettings(user_id=current_user.id)
        db.session.add(settings)
        db.session.commit()
    return jsonify(
        reply_length=settings.reply_length,
        use_emojis=settings.use_emojis,
        theme=settings.theme,
        preferred_name=settings.preferred_name,
    )


@main_bp.get("/api/levels")
@login_required
def get_levels():
    ratings = db.session.scalars(
        db.select(SkillRating).where(SkillRating.user_id == current_user.id)
    ).all()
    return jsonify(levels={row.skill: row.display_level or rating_to_level(row.rating) for row in ratings})


@main_bp.get("/api/mastery")
@login_required
def mastery():
    return jsonify(
        topics=[
            {
                "topic": row.topic,
                "mastery": row.mastery,
                "uncertainty": row.uncertainty,
                "attempts": row.attempts,
                "errors": row.errors,
                "last_seen_at": row.last_seen_at.isoformat(),
            }
            for row in topic_recommendations(db, current_user.id, limit=20)
        ]
    )


@main_bp.patch("/api/settings")
@login_required
def update_settings():
    payload = request.get_json(silent=True) or {}
    if "model" in payload or "provider" in payload:
        return jsonify(error="Model and provider are configured by the server."), 400
    settings = db.session.get(UserSettings, current_user.id)
    if settings is None:
        settings = UserSettings(user_id=current_user.id)
        db.session.add(settings)
    allowed = {
        "reply_length": {"concise", "balanced", "detailed"},
        "theme": {"dark", "light", "system"},
    }
    for field, values in allowed.items():
        if field in payload:
            if not isinstance(payload[field], str) or payload[field] not in values:
                return jsonify(error=f"Invalid {field}."), 400
            setattr(settings, field, payload[field])
    if "use_emojis" in payload:
        if not isinstance(payload["use_emojis"], bool):
            return jsonify(error="use_emojis must be a boolean."), 400
        settings.use_emojis = payload["use_emojis"]
    if "preferred_name" in payload:
        preferred_name = payload["preferred_name"]
        if not isinstance(preferred_name, str) or len(preferred_name.strip()) > 40:
            return jsonify(error="Name must be 40 characters or fewer."), 400
        settings.preferred_name = preferred_name.strip()
    db.session.commit()
    return jsonify(
        reply_length=settings.reply_length, use_emojis=settings.use_emojis,
        theme=settings.theme, preferred_name=settings.preferred_name,
    )


@main_bp.post("/api/messages/<int:message_id>/feedback")
@login_required
def message_feedback(message_id: int):
    message = db.session.scalar(
        db.select(Message).where(Message.id == message_id, Message.user_id == current_user.id)
    )
    if message is None or message.role != "assistant":
        return jsonify(error="Assistant message not found."), 404
    payload = request.get_json(silent=True) or {}
    rating = payload.get("rating")
    comment = payload.get("comment", "")
    if rating not in {"up", "down"}:
        return jsonify(error="Rating must be up or down."), 400
    if not isinstance(comment, str) or len(comment) > 1000:
        return jsonify(error="Comment must be under 1,000 characters."), 400
    feedback = db.session.scalar(
        db.select(MessageFeedback).where(MessageFeedback.message_id == message.id)
    )
    if feedback is None:
        feedback = MessageFeedback(user_id=current_user.id, message_id=message.id)
        db.session.add(feedback)
    feedback.rating = rating
    feedback.comment = comment.strip() or None
    db.session.commit()
    return jsonify(rating=feedback.rating)


@main_bp.get("/privacy")
def privacy():
    return render_template("privacy.html")


@main_bp.get("/progress")
@login_required
def progress():
    return render_template("progress.html", preferred_name=_preferred_name(), sidebar_mode="progress")


@main_bp.get("/api/progress")
@login_required
def progress_api():
    selected_range = request.args.get("range", "all")
    if selected_range not in {"all", "30d", "7d"}:
        return jsonify(error="Range must be all, 30d, or 7d."), 400
    cutoff = None
    if selected_range != "all":
        cutoff = datetime.now(UTC) - timedelta(days=int(selected_range[:-1]))

    rating_rows = db.session.scalars(
        db.select(SkillRating).where(SkillRating.user_id == current_user.id)
    ).all()
    rating_by_skill = {row.skill: row for row in rating_rows}
    valid_messages = db.session.scalar(
        db.select(db.func.count(Message.id)).where(
            Message.user_id == current_user.id,
            Message.role == "user",
            Message.is_valid_for_rating.is_(True),
        )
    ) or 0
    assessed_messages = db.session.scalar(
        db.select(db.func.count(db.func.distinct(ChatTurn.user_message_id))).where(
            ChatTurn.user_id == current_user.id,
            ChatTurn.evaluation_status.in_(("success", "low_confidence")),
        )
    ) or 0
    assessment_failures = db.session.scalar(
        db.select(db.func.count(ApiMetric.id)).where(
            ApiMetric.user_id == current_user.id,
            ApiMetric.kind == "evaluator",
            ApiMetric.status == "failure",
        )
    ) or 0
    active_dates = db.session.execute(
        db.select(db.func.date(Message.ts)).where(Message.user_id == current_user.id)
    ).scalars().all()
    events_query = db.select(RatingEvent).where(RatingEvent.user_id == current_user.id)
    if cutoff is not None:
        events_query = events_query.where(RatingEvent.ts >= cutoff)
    events = db.session.scalars(
        events_query.order_by(RatingEvent.skill, RatingEvent.msg_index, RatingEvent.id)
    ).all()
    events_by_skill = {skill: [] for skill in ("grammar", "vocab", "writing")}
    for event in events:
        if event.skill in events_by_skill:
            events_by_skill[event.skill].append(event)

    def point(event, previous_rating, message_index):
        return {
            "n": message_index,
            "ts": event.ts.isoformat(),
            "rating": event.rating_after,
            "observed_level": event.observed_level,
            "confidence": event.confidence,
            "skipped": event.skipped,
            "label": event.display_level or rating_to_level(event.rating_after),
            "change": event.rating_after - previous_rating,
        }

    skills = {}
    for skill in ("grammar", "vocab", "writing"):
        row = rating_by_skill.get(skill)
        initial_rating = level_to_rating(current_user.self_level)
        skill_events = events_by_skill[skill]
        if cutoff is not None and skill_events:
            initial_rating = skill_events[0].rating_before
        previous = initial_rating
        points = []
        for event in skill_events:
            points.append(point(event, previous, event.msg_index))
            previous = event.rating_after
        current_rating = row.rating if row else initial_rating
        skills[skill] = {
            "label": (row.display_level or rating_to_level(current_rating)) if row else rating_to_level(current_rating),
            "rating": current_rating,
            "start_rating": initial_rating,
            "points": points,
        }

    overall = overall_rating({
        skill: (rating_by_skill.get(skill).rating if rating_by_skill.get(skill) else level_to_rating(current_user.self_level))
        for skill in ("grammar", "vocab", "writing")
    })
    changes = db.session.scalars(
        db.select(LevelChange)
        .where(LevelChange.user_id == current_user.id)
        .order_by(LevelChange.created_at.desc())
        .limit(50)
    ).all()
    recent_errors = db.session.scalars(
        db.select(ErrorLog)
        .where(ErrorLog.user_id == current_user.id, ErrorLog.ts >= datetime.now(UTC) - timedelta(days=30))
        .order_by(ErrorLog.ts.desc(), ErrorLog.id.desc())
        .limit(200)
    ).all()
    topic_groups = {}
    for error in recent_errors:
        group = topic_groups.setdefault(error.topic, {"count": 0, "example_original": error.original, "example_corrected": error.corrected})
        group["count"] += 1
    weak_topics = [
        {"topic": topic, **data}
        for topic, data in sorted(topic_groups.items(), key=lambda item: item[1]["count"], reverse=True)[:5]
    ]
    return jsonify(
        user={
            "self_level": current_user.self_level,
            "overall": {"rating": overall, "label": rating_to_level(overall)},
            "valid_messages": valid_messages,
            "assessed_messages": assessed_messages,
            "assessment_failures": assessment_failures,
            "days_active": len({str(value)[:10] for value in active_dates}),
        },
        skills=skills,
        level_changes=[
            {
                "id": change.id,
                "ts": change.created_at.isoformat(),
                "skill": change.skill,
                "from": change.evidence.get("display_level_before", rating_to_level(change.rating_before)),
                "to": change.label,
            }
            for change in changes
        ],
        weak_topics=weak_topics,
    )


@main_bp.get("/api/level-changes/<int:change_id>")
@login_required
@limiter.limit("10 per minute")
def level_change(change_id: int):
    change = db.session.scalar(
        db.select(LevelChange).where(LevelChange.id == change_id, LevelChange.user_id == current_user.id)
    )
    if change is None:
        return jsonify(error="Level change not found."), 404
    if change.explanation is None:
        change.explanation = _generate_explanation(change)
        db.session.commit()
    return jsonify(
        id=change.id, skill=change.skill, label=change.label,
        rating_before=change.rating_before, rating_after=change.rating_after,
        explanation=change.explanation,
    )


def _deterministic_explanation(evidence):
    errors = evidence.get("errors", [])
    topics = ", ".join(item["topic"] for item in errors[:3]) or "no recurring error topics"
    levels = [item["observed_level"] for item in evidence.get("events", [])]
    trend = " -> ".join(reversed(levels[-3:])) if levels else "limited observations"
    return {
        "summary": f"The displayed level changed based on recent observations and {sum(item.get('count', 0) for item in errors)} logged errors.",
        "reasons": [
            {"kind": "errors", "text": f"Most frequent topics: {topics}."},
            {"kind": "pattern", "text": f"Recent observed levels: {trend}."},
        ],
        "caveat": "This is an estimate from limited messages and is not a guarantee of future performance.",
    }


def _generate_explanation(change):
    if change.skill == "overall":
        return _deterministic_explanation(change.evidence)
    language = "English"
    started = datetime.now(UTC)
    try:
        client = create_client(current_app.config, groq_client=Groq)
        from .providers import call_with_fallback

        response, model, fallback_used = call_with_fallback(
            client, get_model("explain"),
            [item.strip() for item in current_app.config.get("LLM_MODEL_FALLBACKS", "").split(",") if item.strip()],
            {"temperature": 0.2, "max_tokens": get_max_tokens("explain"),
             "response_format": {"type": "json_object"}, "messages": [{
                "role": "system",
                "content": (
                    f"Explain this level change in {language}. Return JSON with summary (max 2 sentences), "
                    "reasons (kind errors|strengths|pattern, text, optional exact quote), and one-sentence caveat. "
                    "Use only the supplied evidence. Never promise exam results or certainty."
                ),
            }, {"role": "user", "content": json.dumps(change.evidence, ensure_ascii=False)}]},
        )
        result = json.loads(response.choices[0].message.content)
        explanation = _sanitize_explanation(result, change.evidence)
        if explanation is not None:
            db.session.add(ApiMetric(user_id=current_user.id, kind="explain",
                                     latency_ms=(datetime.now(UTC) - started).total_seconds() * 1000,
                                     provider=current_app.config["LLM_PROVIDER"], model=model,
                                     fallback_used=fallback_used))
            return explanation
    except Exception as error:  # noqa: BLE001 - provider SDK failures vary by provider/version.
        current_app.logger.warning("Level explanation failed type=%s", type(error).__name__)
    db.session.add(ApiMetric(user_id=current_user.id, kind="explain",
                             latency_ms=(datetime.now(UTC) - started).total_seconds() * 1000,
                             provider=current_app.config["LLM_PROVIDER"], model=get_model("explain"),
                             status="failure"))
    return _deterministic_explanation(change.evidence)


def _sanitize_explanation(value, evidence):
    if not isinstance(value, dict) or not isinstance(value.get("summary"), str):
        return None
    reasons = []
    quotes = []
    def collect(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"message", "original", "corrected", "example"} and isinstance(child, str):
                    quotes.append(child)
                collect(child)
        elif isinstance(item, list):
            for child in item:
                collect(child)
    collect(evidence)
    for reason in value.get("reasons", []):
        if not isinstance(reason, dict) or reason.get("kind") not in {"errors", "strengths", "pattern"}:
            continue
        quote = reason.get("quote")
        if quote is not None and (not isinstance(quote, str) or not any(
            quote.casefold() in source.casefold() for source in quotes
        )):
            continue
        item = {"kind": reason["kind"], "text": str(reason.get("text", ""))}
        if quote:
            item["quote"] = quote
        reasons.append(item)
    if not reasons:
        return None
    return {
        "summary": value["summary"],
        "reasons": reasons,
        "caveat": str(value.get("caveat") or "This is an estimate from limited messages and is not a guarantee."),
    }


@main_bp.route("/feedback", methods=["GET", "POST"])
@login_required
def feedback():
    if request.method == "POST":
        answers = [request.form.get(f"q{i}", "") for i in range(1, 11)]
        if not all(answer in {"1", "2", "3", "4", "5"} for answer in answers):
            flash("Please answer all ten questions.", "error")
        else:
            db.session.add(Feedback(user_id=current_user.id, sus_answers=answers,
                                    free_text=request.form.get("free_text", "")[:4000]))
            db.session.commit()
            flash("Thank you for your feedback!", "success")
            return redirect(url_for("main.chat"))
    return render_template("feedback.html")


@main_bp.post("/account/delete")
@login_required
@limiter.limit("3 per hour")
def delete_account():
    user_id = current_user.id
    for model in (
        MessageFeedback,
        LevelChange,
        RatingEvent,
        ErrorLog,
        Message,
        Conversation,
        UserSettings,
        TopicMastery,
        SkillRating,
        ApiMetric,
        Feedback,
    ):
        db.session.execute(db.delete(model).where(model.user_id == user_id))
    db.session.execute(db.delete(User).where(User.id == user_id))
    db.session.commit()
    from flask_login import logout_user
    logout_user()
    flash("Your account and stored data have been deleted.", "success")
    return redirect(url_for("main.index"))


@main_bp.get("/admin/export")
@login_required
def admin_export():
    if not current_user.is_admin:
        return jsonify(error="Not found"), 404
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["dataset", "user_hash", "kind", "skill", "rating_before", "rating_after",
                     "latency_ms", "tokens_in", "tokens_out", "est_cost_usd", "ts"])
    for event in db.session.scalars(db.select(RatingEvent)):
        writer.writerow(["rating_event", _hash_user(event.user_id), "", event.skill, event.rating_before,
                         event.rating_after, "", "", "", "", event.ts.isoformat()])
    for metric in db.session.scalars(db.select(ApiMetric)):
        writer.writerow(["api_metric", _hash_user(metric.user_id), metric.kind, "", "", "",
                         metric.latency_ms, metric.tokens_in, metric.tokens_out, metric.est_cost_usd,
                         metric.ts.isoformat()])
    for item in db.session.scalars(db.select(Feedback)):
        writer.writerow(["feedback", _hash_user(item.user_id), "", "", "", "", "", "", "", "", item.ts.isoformat()])
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=linguapath-export.csv"})


def _hash_user(user_id: int | None) -> str:
    return hashlib.sha256(f"{current_app.config['SECRET_KEY']}:{user_id}".encode()).hexdigest()[:16]


@main_bp.post("/api/chat")
@login_required
@limiter.limit(lambda: current_app.config["RATE_LIMIT_CHAT"])
def api_chat():
    payload = request.get_json(silent=True) or {}
    content = payload.get("content", "")
    conversation_id = payload.get("conversation_id")
    if not isinstance(content, str) or not content.strip() or len(content) > 4000:
        return jsonify(error="Please send a message under 4,000 characters."), 400
    conversation = None
    if conversation_id is not None:
        if not isinstance(conversation_id, int):
            return jsonify(error="Invalid conversation."), 400
        conversation = _conversation_or_404(conversation_id)
        message_count = db.session.scalar(
            db.select(db.func.count(Message.id)).where(Message.conversation_id == conversation.id)
        )
        if message_count >= 300:
            return jsonify(error="This conversation has reached the 300-message limit."), 409
    auto_title_pending = bool(
        conversation
        and conversation.title_auto
        and not db.session.scalar(
            db.select(db.exists().where(
                Message.conversation_id == conversation.id,
                Message.role == "user",
            ))
        )
    )
    today = datetime.now(UTC).date()
    sent_today = db.session.scalar(
        db.select(db.func.count(ChatTurn.id)).where(
            ChatTurn.user_id == current_user.id,
            ChatTurn.status == "completed",
            db.func.date(ChatTurn.started_at) == today,
        )
    )
    if sent_today >= current_user.daily_cap:
        return jsonify(error="Your daily message limit has been reached. Please try again tomorrow."), 429

    starter_prompts = {
        "Tell me about yourself in English.",
        "Describe your typical day and routine.",
        "Help me practice useful everyday vocabulary.",
        "Let's discuss an interesting news topic.",
    }
    skip_assessment = (
        payload.get("skip_assessment") is True
        and content.strip() in starter_prompts
        and auto_title_pending
    )
    valid = not skip_assessment and is_valid_message(content)
    message = Message(
        user_id=current_user.id,
        conversation_id=conversation.id if conversation else None,
        role="user",
        content=content,
        is_valid_for_rating=valid,
    )
    db.session.add(message)
    db.session.flush()
    settings = db.session.get(UserSettings, current_user.id)
    provider = current_app.config["LLM_PROVIDER"]
    model = get_model("tutor")
    turn = ChatTurn(
        user_id=current_user.id,
        conversation_id=conversation.id if conversation else None,
        user_message_id=message.id,
        provider=provider or current_app.config["LLM_PROVIDER"],
        model=model,
    )
    db.session.add(turn)
    valid_index = db.session.scalar(
        db.select(db.func.count(Message.id)).where(
            Message.user_id == current_user.id, Message.role == "user", Message.is_valid_for_rating.is_(True)
        )
    ) if valid else 0
    message.msg_index = valid_index if valid else None
    db.session.commit()

    evaluation_result = None
    try:
        client = create_client(current_app.config, groq_client=Groq)
    except (RuntimeError, ValueError):
        turn.status = "failed"
        turn.tutor_status = "failed"
        turn.error = "Tutor provider unavailable"
        turn.completed_at = datetime.now(UTC)
        db.session.commit()
        return jsonify(error="The configured AI provider is not available."), 503
    history_rows = db.session.scalars(
        db.select(Message)
        .where(
            Message.user_id == current_user.id,
            Message.conversation_id == (conversation.id if conversation else None),
            Message.id != message.id,
        )
        .order_by(Message.ts.desc())
        .limit(12)
    ).all()
    history = [{"role": row.role, "content": row.content} for row in reversed(history_rows)]
    learning_plan = select_learning_plan(db, current_user.id)
    turn.learning_action = learning_plan["action"]
    turn.target_skill = learning_plan["target_skill"]
    turn.target_topic = learning_plan["target_topic"]
    ratings = {
        row.skill: row.display_level or rating_to_level(row.rating)
        for row in db.session.scalars(db.select(SkillRating).filter_by(user_id=current_user.id))
    }
    recent_errors = list(db.session.scalars(
        db.select(ErrorLog.topic).filter_by(user_id=current_user.id).order_by(ErrorLog.ts.desc()).limit(5)
    ))
    settings_data = {
        "reply_length": settings.reply_length if settings else "balanced",
        "use_emojis": settings.use_emojis if settings else True,
        "preferred_name": settings.preferred_name if settings else "",
    }
    evaluator_context = {"current_levels": ratings, "recent_weak_topics": recent_errors}
    application = current_app._get_current_object()
    tutor_started = datetime.now(UTC)
    with ThreadPoolExecutor(max_workers=3 if auto_title_pending else 2) as executor:
        evaluation_future = executor.submit(
            _run_evaluator,
            application,
            client,
            get_model("evaluator"),
            content,
            evaluator_context,
            get_max_tokens("evaluator"),
            provider,
            dict(current_app.config),
            [item.strip() for item in current_app.config.get("LLM_MODEL_FALLBACKS", "").split(",") if item.strip()],
            reasoning_options(current_app.config),
        ) if valid else None
        tutor_future = executor.submit(
            _run_tutor,
            application,
            client,
            model,
            content,
            history,
            ratings,
            recent_errors,
            settings_data,
            learning_plan,
            get_max_tokens("tutor"),
            provider,
            [item.strip() for item in current_app.config.get("LLM_MODEL_FALLBACKS", "").split(",") if item.strip()],
            reasoning_options(current_app.config),
        )
        title_future = executor.submit(
            _run_title,
            application,
            client,
            content,
            get_max_tokens("title"),
            provider,
            [item.strip() for item in current_app.config.get("LLM_MODEL_FALLBACKS", "").split(",") if item.strip()],
            reasoning_options(current_app.config),
        ) if auto_title_pending else None
        try:
            evaluation_result = evaluation_future.result() if evaluation_future else None
            evaluation = evaluation_result.evaluation if evaluation_result else None
        except (APIError, AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
            evaluation = None
            turn.evaluation_status = "failed"
        else:
            if not valid:
                turn.evaluation_status = "skipped"
            elif evaluation is None:
                turn.evaluation_status = "failed"
            elif not evaluation.is_english:
                turn.evaluation_status = "not_english"
            else:
                turn.evaluation_status = "success"
        try:
            tutor_result = tutor_future.result()
            reply = tutor_result["reply"]
        except Exception as error:  # noqa: BLE001 - Future.result() propagates provider-specific errors.
            current_app.logger.warning("Tutor provider failure type=%s detail=%s", type(error).__name__, str(error))
            turn.status = "failed"
            turn.tutor_status = "failed"
            turn.error = "Tutor provider unavailable"
            turn.completed_at = datetime.now(UTC)
            if evaluation_result:
                evaluation_result.metric.user_id = current_user.id
                db.session.add(evaluation_result.metric)
            db.session.add(ApiMetric(
                user_id=current_user.id, kind="tutor",
                latency_ms=(datetime.now(UTC) - tutor_started).total_seconds() * 1000,
                provider=provider, model=model, status="failure",
            ))
            try:
                db.session.commit()
            except OperationalError as error:
                db.session.rollback()
                if "database is locked" in str(error).lower():
                    current_app.logger.warning("SQLite write lock while completing chat request")
                    return jsonify(error="Please try again."), 503
                raise
            return jsonify(error="The tutor is temporarily unavailable. Please try again."), 503
        turn.tutor_status = "success"
        if title_future:
            try:
                generated_title = title_future.result()
            except Exception as error:  # noqa: BLE001 - title generation is best-effort.
                current_app.logger.warning("Conversation title generation failed type=%s", type(error).__name__)
                generated_title = _fallback_conversation_title(content)
            if conversation.title_auto:
                conversation.title = _unique_conversation_title(
                    current_user.id, generated_title, exclude_id=conversation.id
                )
                conversation.title_auto = False
    if evaluation_result:
        evaluation_result.metric.user_id = current_user.id
        db.session.add(evaluation_result.metric)
    db.session.add(ApiMetric(
        user_id=current_user.id, kind="tutor", latency_ms=tutor_result["latency_ms"],
        tokens_in=tutor_result["tokens_in"], tokens_out=tutor_result["tokens_out"],
        provider=tutor_result["provider"], model=tutor_result["model"],
        status=tutor_result["status"], retry_count=tutor_result["retry_count"],
        fallback_used=tutor_result["fallback_used"],
        reasoning_tokens=tutor_result["reasoning_tokens"],
    ))

    changed = []
    accepted_skill_updates = 0
    before_overall = overall_rating({
        row.skill: row.rating for row in db.session.scalars(
            db.select(SkillRating).filter_by(user_id=current_user.id)
        )
    })
    if evaluation and evaluation.is_english and valid:
        for skill, observation in evaluation.skills.items():
            rating = db.session.execute(
                db.select(SkillRating).where(
                    SkillRating.user_id == current_user.id, SkillRating.skill == skill
                ).with_for_update()
            ).scalar_one_or_none()
            if rating is None:
                continue
            before_level = rating.display_level or rating_to_level(rating.rating)
            update = update_skill(
                rating, observation.level, observation.confidence, valid_index,
                content, evaluation.errors, current_app.config["RATING_MODE"],
            )
            accepted_skill_updates += not update["skipped"]
            after_level = displayed_level(update["after"], before_level)
            rating.display_level = after_level
            update["display_level"] = after_level
            event = event_from_update(current_user.id, message.id, skill, observation.level, update, valid_index)
            db.session.add(event)
            if before_level != after_level:
                evidence = _level_change_evidence(current_user.id, skill, content, evaluation, update)
                evidence["display_level_before"] = before_level
                change = LevelChange(
                    user_id=current_user.id, skill=skill, label=after_level,
                    rating_before=update["before"], rating_after=update["after"],
                    evidence=evidence,
                )
                db.session.add(change)
                db.session.flush()
                changed.append({"skill": skill, "label": after_level, "level": after_level, "change_id": change.id})
        for error in evaluation.errors:
            db.session.add(ErrorLog(user_id=current_user.id, message_id=message.id, topic=error.topic,
                                    error_type=error.type, original=error.original, corrected=error.corrected))
        update_topic_mastery(db, current_user.id, evaluation.errors, evaluation.strengths)
        if accepted_skill_updates == 0:
            turn.evaluation_status = "low_confidence"
        after_overall = overall_rating({
            row.skill: row.rating for row in db.session.scalars(
                db.select(SkillRating).filter_by(user_id=current_user.id)
            )
        })
        if rating_to_level(before_overall) != rating_to_level(after_overall):
            change = LevelChange(
                user_id=current_user.id, skill="overall", label=rating_to_level(after_overall),
                rating_before=before_overall, rating_after=after_overall,
                evidence={"skill": "overall", "events": [], "errors": [], "strengths": [],
                          "rating_before": before_overall, "rating_after": after_overall},
            )
            db.session.add(change)
            db.session.flush()
            changed.append({"skill": "overall", "label": change.label, "change_id": change.id})
    assistant_message = Message(
            user_id=current_user.id,
            conversation_id=conversation.id if conversation else None,
            role="assistant",
            content=reply,
        )
    db.session.add(assistant_message)
    db.session.flush()
    turn.assistant_message_id = assistant_message.id
    turn.status = "completed"
    turn.completed_at = datetime.now(UTC)
    if conversation:
        conversation.updated_at = datetime.now(UTC)
    try:
        db.session.commit()
    except OperationalError as error:
        db.session.rollback()
        if "database is locked" in str(error).lower():
            current_app.logger.warning("SQLite write lock while completing chat request")
            return jsonify(error="Please try again."), 503
        raise
    levels = {row.skill: row.display_level or rating_to_level(row.rating) for row in db.session.scalars(
        db.select(SkillRating).filter_by(user_id=current_user.id)
    )}
    return jsonify(
        reply=reply,
        conversation_title=conversation.title if conversation else None,
        levels=levels,
        level_changed=changed,
        assessment_status=turn.evaluation_status,
    )


def _level_change_evidence(user_id, skill, content, evaluation, update):
    events = db.session.scalars(
        db.select(RatingEvent)
        .where(RatingEvent.user_id == user_id, RatingEvent.skill == skill)
        .order_by(RatingEvent.ts.desc(), RatingEvent.id.desc()).limit(5)
    ).all()
    topic_rows = db.session.execute(
        db.select(ErrorLog.topic, db.func.count(ErrorLog.id))
        .where(ErrorLog.user_id == user_id).group_by(ErrorLog.topic)
        .order_by(db.func.count(ErrorLog.id).desc()).limit(3)
    ).all()
    errors = db.session.scalars(
        db.select(ErrorLog).where(ErrorLog.user_id == user_id)
        .order_by(ErrorLog.ts.desc(), ErrorLog.id.desc()).limit(50)
    ).all()
    examples = {}
    for error in errors:
        examples.setdefault(error.topic, {"original": error.original, "corrected": error.corrected})
    return {
        "skill": skill,
        "message": content,
        "events": [
            {"observed_level": item.observed_level, "c_eff": item.c_eff,
             "density": item.r_density, "rating_before": item.rating_before,
             "rating_after": item.rating_after}
            for item in events
        ],
        "errors": [
            {"topic": topic, "count": count, **examples.get(topic, {})}
            for topic, count in topic_rows
        ],
        "strengths": [
            {"topic": item.topic, "example": item.example}
            for item in evaluation.strengths[:3]
            if item.example.casefold() in content.casefold()
        ],
        "rating_before": update["before"],
        "rating_after": update["after"],
    }


def _run_evaluator(app, client, model, content, context=None, max_tokens=256, provider="unknown", config=None, fallbacks=None, reasoning=None):
    with app.app_context():
        return evaluate_message(client, model, content, None, None, context, provider, config, max_tokens=max_tokens, fallbacks=fallbacks, reasoning=reasoning)


def _run_tutor(app, client, model, content, history, ratings, errors, settings, plan, max_tokens, provider="unknown", fallbacks=None, reasoning=None):
    from .tutor import tutor_reply
    with app.app_context():
        return tutor_reply(client, model, content, history, ratings, errors, settings, plan, max_tokens, provider, fallbacks, reasoning)


def _fallback_conversation_title(content: str) -> str:
    words = " ".join(content.split())
    if len(words) > 48:
        words = words[:48].rsplit(" ", 1)[0].rstrip(".,!?;:")
    return words[:200] or "New chat"


def _run_title(app, client, content, max_tokens, provider="unknown", fallbacks=None, reasoning=None):
    from .providers import call_with_fallback

    with app.app_context():
        model = get_model("title")
        response, _, _ = call_with_fallback(
            client,
            model,
            fallbacks or [],
            {
                "temperature": 0.2,
                "max_tokens": max_tokens,
                "messages": [
                    {
                        "role": "system",
                        "content": "Create a concise, natural title for this English-learning chat based on the learner's first message. Use 2-6 words, title case, no quotes, and return only the title.",
                    },
                    {"role": "user", "content": content},
                ],
                **(reasoning or {}),
            },
        )
        title = (response.choices[0].message.content or "").strip().strip("\"'`*# ")
        title = " ".join(title.split())[:200].rstrip(".,!?;:")
        return title or _fallback_conversation_title(content)
