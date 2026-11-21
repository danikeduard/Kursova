"""Public pages and chat API."""

import base64
import csv
import hashlib
import io
import json
import unicodedata
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
from sqlalchemy.exc import IntegrityError, OperationalError

from config.llm import get_max_tokens, get_model, reasoning_options

from .evaluator import evaluate_message
from .extensions import db, limiter
from .learning import topic_recommendations, update_topic_mastery
from .level_service import event_from_update, update_skill
from .message_validation import assessability, validate_chat_content
from .models import (
    ApiMetric,
    ChatTurn,
    Conversation,
    ErrorLog,
    Feedback,
    BugReport,
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
    level_to_rating,
    overall_rating,
    rating_to_level,
)

main_bp = Blueprint("main", __name__)

FEEDBACK_QUESTIONS = (
    ("q1", "The system was easy to use."),
    ("q2", "The tutor adjusted its language to my level."),
    ("q3", "The level shown by the system matches my real English level."),
    ("q4", "The corrections and explanations helped me learn."),
    ("q5", "I would use this system again."),
)
FEEDBACK_STATUSES = ("new", "read", "archived")
BUG_CATEGORIES = (
    "Something is broken",
    "Wrong level or rating",
    "Confusing or hard to use",
    "Idea or suggestion",
    "Other",
)
BUG_STATUSES = ("new", "in_progress", "resolved", "wont_fix")


@main_bp.get("/")
def index():
    return render_template("index.html")


@main_bp.get("/chat")
@login_required
def chat():
    return render_template(
        "chat.html", conversation_id=None, preferred_name=_preferred_name(), sidebar_mode="chat",
        max_message_chars=current_app.config["CHAT_MESSAGE_MAX_CHARS"],
    )


@main_bp.get("/chat/<int:conversation_id>")
@login_required
def conversation_page(conversation_id: int):
    conversation = _conversation_or_404(conversation_id)
    return render_template(
        "chat.html", conversation_id=conversation.id, preferred_name=_preferred_name(), sidebar_mode="chat",
        max_message_chars=current_app.config["CHAT_MESSAGE_MAX_CHARS"],
    )


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
    record = db.session.scalar(
        db.select(Feedback).where(Feedback.user_id == current_user.id)
    )
    if request.method == "GET":
        return _render_feedback_page(
            record=record,
            submitted=request.args.get("submitted") == "1",
        )

    form = request.get_json(silent=True) if request.is_json else request.form
    if not isinstance(form, dict):
        form = {}
    raw_answers = {key: str(form.get(key, "")) for key, _ in FEEDBACK_QUESTIONS}
    answers = {}
    errors = {}
    for key, _ in FEEDBACK_QUESTIONS:
        value = raw_answers[key]
        if value not in {"1", "2", "3", "4", "5"}:
            errors[key] = "Choose a score from 1 to 5."
        else:
            answers[key] = int(value)

    raw_comment = form.get("free_text", form.get("comment", ""))
    comment = _clean_feedback_comment(str(raw_comment or ""))
    if len(comment) > 1000:
        errors["free_text"] = "Comments must be 1,000 characters or fewer."
    consent_value = str(form.get("consent_research", "")).lower()
    consent = consent_value in {"yes", "on", "true", "1"}

    if errors:
        message = (
            "Please answer all five questions."
            if any(key in errors for key, _ in FEEDBACK_QUESTIONS)
            else errors["free_text"]
        )
        if request.accept_mimetypes.best == "application/json":
            return jsonify(error=message, fields=errors), 400
        return _render_feedback_page(
            record=record,
            answers=answers,
            comment=comment,
            consent=consent,
            errors=errors,
        ), 400

    context_snapshot = _feedback_context_snapshot(current_user.id)
    submitted_at = datetime.now(UTC)
    replaced = record is not None
    if record is None:
        record = Feedback(
            user_id=current_user.id,
            sus_answers=None,
            free_text=comment,
            answers=answers,
            schema_version=2,
            revision=1,
            created_at=submitted_at,
            context=context_snapshot,
            consent_research=consent,
            admin_status="new",
            ts=submitted_at,
            updated_at=submitted_at,
        )
        db.session.add(record)
    else:
        record.answers = answers
        record.schema_version = 2
        record.context = context_snapshot
        record.consent_research = consent
        record.free_text = comment
        record.admin_status = "new"
        record.revision = (record.revision or 1) + 1
        record.updated_at = submitted_at

    try:
        db.session.commit()
    except IntegrityError:
        # A concurrent first submission can win the unique-user constraint.
        db.session.rollback()
        record = db.session.scalar(
            db.select(Feedback).where(Feedback.user_id == current_user.id)
        )
        if record is None:
            raise
        record.answers = answers
        record.schema_version = 2
        record.context = context_snapshot
        record.consent_research = consent
        record.free_text = comment
        record.admin_status = "new"
        record.revision = (record.revision or 1) + 1
        record.updated_at = datetime.now(UTC)
        db.session.commit()

    if request.accept_mimetypes.best == "application/json":
        return jsonify(
            ok=True,
            replaced=replaced,
            message="Your answers were updated." if replaced else "Thank you!",
        ), 200
    return redirect(url_for("main.feedback", submitted="1", updated="1" if replaced else "0"))


def _render_feedback_page(
    record=None,
    answers=None,
    comment=None,
    consent=None,
    errors=None,
    submitted=False,
):
    if answers is None:
        answers = (
            record.answers
            if record is not None and record.schema_version == 2 and isinstance(record.answers, dict)
            else {}
        )
    if comment is None:
        comment = record.free_text or "" if record is not None else ""
    if consent is None:
        consent = bool(record.consent_research) if record is not None else False
    return render_template(
        "feedback.html",
        preferred_name=_preferred_name(),
        sidebar_mode="feedback",
        feedback_questions=FEEDBACK_QUESTIONS,
        feedback_answers=answers,
        feedback_comment=comment,
        consent_research=consent,
        already_submitted=record is not None,
        legacy_submission=record is not None and record.schema_version == 1,
        feedback_errors=errors or {},
        submitted=submitted,
        feedback_updated=request.args.get("updated") == "1",
        feedback_draft_key=_hash_user(current_user.id),
    )


def _clean_feedback_comment(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        character
        for character in normalized
        if character in "\n\t" or unicodedata.category(character) not in {"Cc", "Cs"}
    ).strip()


def _feedback_context_snapshot(user_id: int) -> dict:
    user = db.session.get(User, user_id)
    rating_rows = db.session.scalars(
        db.select(SkillRating).where(SkillRating.user_id == user_id)
    ).all()
    ratings = {row.skill: row.rating for row in rating_rows}
    overall = overall_rating({
        skill: ratings.get(skill, level_to_rating(user.self_level))
        for skill in ("grammar", "vocab", "writing")
    })
    rated_units = db.session.scalar(
        db.select(db.func.count(db.func.distinct(ChatTurn.user_message_id))).where(
            ChatTurn.user_id == user_id,
            ChatTurn.evaluation_status.in_(("success", "low_confidence")),
        )
    ) or 0
    active_dates = db.session.execute(
        db.select(db.func.date(Message.ts)).where(
            Message.user_id == user_id,
            Message.role == "user",
        ).distinct()
    ).scalars().all()
    return {
        "self_level": user.self_level,
        "estimated_overall_level": rating_to_level(overall),
        "rated_units": int(rated_units),
        "days_active": len({str(value)[:10] for value in active_dates}),
    }

def _bug_user_key():
    if current_user.is_authenticated:
        return f"user:{current_user.id}"
    return f"anonymous:{request.remote_addr}"


def _clean_bug_text(value: str) -> str:
    return _clean_feedback_comment(str(value or ""))


def _csv_safe(value) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + text
    return text


@main_bp.post("/api/bug-reports")
@login_required
@limiter.limit("5 per hour", key_func=_bug_user_key)
@limiter.limit("20 per day", key_func=_bug_user_key)
def create_bug_report():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Request body must be a JSON object."), 400

    category = payload.get("category")
    if category not in BUG_CATEGORIES:
        return jsonify(error="Invalid bug report category."), 400
    title = _clean_bug_text(payload.get("title") or "")
    description = _clean_bug_text(payload.get("description") or "")
    if len(title) > 120:
        return jsonify(error="Title must be 120 characters or fewer."), 400
    if len(description) < 10:
        return jsonify(error="Description must be at least 10 characters."), 400
    if len(description) > 2000:
        return jsonify(error="Description must be 2,000 characters or fewer."), 400

    raw_context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    context = {}
    limits = {
        "page_path": 300,
        "browser": 300,
        "screen": 100,
        "viewport": 100,
        "theme": 20,
        "app_version": 40,
        "timestamp": 40,
    }
    for key, limit in limits.items():
        if key in raw_context:
            context[key] = _clean_bug_text(str(raw_context[key])[:limit])
    if "conversation_id" in raw_context:
        try:
            conversation_id = int(raw_context["conversation_id"])
            context["conversation_id"] = conversation_id if conversation_id > 0 else None
        except (TypeError, ValueError):
            pass
    if context.get("conversation_id") is None:
        context.pop("conversation_id", None)

    record = BugReport(
        user_id=current_user.id,
        category=category,
        title=title or None,
        description=description,
        context=context,
        status="new",
    )
    db.session.add(record)
    db.session.commit()
    return jsonify(id=record.id), 200


@main_bp.get("/admin")
@login_required
def admin_panel():
    if not current_user.is_admin:
        return jsonify(error="Not found"), 404
    return redirect(url_for("main.admin_feedback"))


@main_bp.get("/admin/feedback")
@login_required
def admin_feedback():
    if not current_user.is_admin:
        return jsonify(error="Not found"), 404

    try:
        requested_page = max(1, int(request.args.get("page", "1")))
    except (TypeError, ValueError):
        return jsonify(error="Page must be a positive integer."), 400

    total = db.session.scalar(db.select(db.func.count(Feedback.id))) or 0
    query = db.select(Feedback)
    status = request.args.get("status", "")
    if status:
        if status not in FEEDBACK_STATUSES:
            return jsonify(error="Invalid feedback status."), 400
        query = query.where(Feedback.admin_status == status)
    if request.args.get("has_comment") == "1":
        query = query.where(Feedback.free_text.is_not(None), db.func.length(Feedback.free_text) > 0)
    if request.args.get("consent") in {"0", "1"}:
        query = query.where(Feedback.consent_research == (request.args.get("consent") == "1"))
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    if date_from:
        query = query.where(Feedback.ts >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.where(Feedback.ts < datetime.fromisoformat(date_to) + timedelta(days=1))
    search = request.args.get("q", request.args.get("search", "")).strip()
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.join(User, User.id == Feedback.user_id).where(
            db.or_(Feedback.free_text.ilike(pattern, escape="\\"), User.email.ilike(pattern, escape="\\"))
        )
    filtered_total = db.session.scalar(db.select(db.func.count()).select_from(query.subquery())) or 0
    total_pages = max(1, (filtered_total + 19) // 20)
    page = min(requested_page, total_pages)
    records = db.session.scalars(
        query
        .order_by(Feedback.updated_at.desc(), Feedback.id.desc())
        .offset((page - 1) * 20)
        .limit(20)
    ).all()
    new_form_records = db.session.scalars(
        db.select(Feedback.answers).where(
            Feedback.schema_version == 2,
            Feedback.answers.is_not(None),
        )
    ).all()

    question_stats = []
    all_scores = []
    for index, (key, statement) in enumerate(FEEDBACK_QUESTIONS, start=1):
        scores = []
        for answers in new_form_records:
            if not isinstance(answers, dict):
                continue
            score = answers.get(key)
            if type(score) is int and 1 <= score <= 5:
                scores.append(score)
        all_scores.extend(scores)
        question_stats.append({
            "label": f"Q{index}",
            "statement": statement,
            "mean": round(sum(scores) / len(scores), 2) if scores else None,
            "n": len(scores),
            "distribution": [scores.count(value) for value in range(1, 6)],
        })

    unread = db.session.scalar(
        db.select(db.func.count(Feedback.id)).where(Feedback.admin_status == "new")
    ) or 0
    response_rows = []
    for record in records:
        answers = record.answers if record.schema_version == 2 and isinstance(record.answers, dict) else {}
        context_snapshot = record.context if isinstance(record.context, dict) else {}
        user = db.session.get(User, record.user_id)
        response_rows.append({
            "record": record,
            "participant_id": _hash_user(record.user_id),
            "email": user.email if user and current_app.config["ADMIN_SHOW_USER_EMAIL"] else None,
            "legacy": record.schema_version == 1,
            "scores": [answers.get(key) for key, _ in FEEDBACK_QUESTIONS],
            "self_level": context_snapshot.get("self_level", "—"),
            "estimated_level": context_snapshot.get("estimated_overall_level", "—"),
            "rated_units": context_snapshot.get("rated_units"),
            "days_active": context_snapshot.get("days_active"),
        })

    return render_template(
        "admin_feedback.html",
        preferred_name=_preferred_name(),
        sidebar_mode="admin-feedback",
        questions=FEEDBACK_QUESTIONS,
        question_stats=question_stats,
        overall_mean=round(sum(all_scores) / len(all_scores), 2) if all_scores else None,
        response_count=total,
        new_form_response_count=len(new_form_records),
        unread_count=unread,
        small_sample=len(new_form_records) < 8,
        response_rows=response_rows,
        page=page,
        total_pages=total_pages,
        bug_new_count=db.session.scalar(db.select(db.func.count(BugReport.id)).where(BugReport.status == "new")) or 0,
    )


@main_bp.post("/admin/feedback/<int:feedback_id>/status")
@login_required
def admin_feedback_status(feedback_id: int):
    if not current_user.is_admin:
        return jsonify(error="Not found"), 404
    status = request.form.get("admin_status", "")
    if status not in FEEDBACK_STATUSES:
        return jsonify(error="Invalid feedback status."), 400
    page = request.form.get("page", "1")
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    record = db.session.get(Feedback, feedback_id)
    if record is None:
        return jsonify(error="Not found"), 404
    db.session.execute(
        db.update(Feedback)
        .where(Feedback.id == feedback_id)
        .values(admin_status=status, updated_at=Feedback.updated_at)
    )
    db.session.commit()
    flash("Feedback status updated.", "success")
    return redirect(url_for("main.admin_feedback", page=page))


def _admin_bug_query():
    query = db.select(BugReport)
    status = request.args.get("status", "")
    category = request.args.get("category", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    search = request.args.get("q", request.args.get("search", "")).strip()
    if status:
        if status not in BUG_STATUSES:
            return None
        query = query.where(BugReport.status == status)
    if category:
        if category not in BUG_CATEGORIES:
            return None
        query = query.where(BugReport.category == category)
    if date_from:
        query = query.where(BugReport.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.where(BugReport.created_at < datetime.fromisoformat(date_to) + timedelta(days=1))
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.join(User, User.id == BugReport.user_id).where(
            db.or_(
                BugReport.title.ilike(pattern, escape="\\"),
                BugReport.description.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
            )
        )
    return query


@main_bp.get("/api/admin/feedback")
@login_required
def api_admin_feedback():
    if not current_user.is_admin:
        return jsonify(error="Not found"), 404
    try:
        page = max(1, int(request.args.get("page", "1")))
    except (TypeError, ValueError):
        return jsonify(error="Invalid page."), 400
    query = db.select(Feedback)
    status = request.args.get("status", "")
    if status:
        if status not in FEEDBACK_STATUSES:
            return jsonify(error="Invalid feedback status."), 400
        query = query.where(Feedback.admin_status == status)
    search = request.args.get("q", request.args.get("search", "")).strip()
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.join(User, User.id == Feedback.user_id).where(
            db.or_(Feedback.free_text.ilike(pattern, escape="\\"), User.email.ilike(pattern, escape="\\"))
        )
    total = db.session.scalar(db.select(db.func.count()).select_from(query.subquery())) or 0
    records = db.session.scalars(query.order_by(Feedback.updated_at.desc(), Feedback.id.desc()).offset((page - 1) * 20).limit(20)).all()
    items = []
    for record in records:
        user = db.session.get(User, record.user_id)
        item = {
            "id": record.id,
            "participant_id": _hash_user(record.user_id),
            "schema_version": record.schema_version,
            "revision": record.revision,
            "answers": record.answers if isinstance(record.answers, dict) else None,
            "comment": record.free_text,
            "consent_research": record.consent_research,
            "context": record.context if isinstance(record.context, dict) else {},
            "admin_status": record.admin_status,
            "created_at": (record.created_at or record.ts).isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }
        if current_app.config["ADMIN_SHOW_USER_EMAIL"]:
            item["email"] = user.email if user else None
        items.append(item)
    return jsonify(items=items, page=page, total=total, total_pages=max(1, (total + 19) // 20))


@main_bp.patch("/api/admin/feedback/<int:feedback_id>")
@login_required
def api_admin_feedback_patch(feedback_id: int):
    if not current_user.is_admin:
        return jsonify(error="Not found"), 404
    record = db.session.get(Feedback, feedback_id)
    if record is None:
        return jsonify(error="Not found"), 404
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Request body must be a JSON object."), 400
    if "admin_status" in payload:
        if payload["admin_status"] not in FEEDBACK_STATUSES:
            return jsonify(error="Invalid feedback status."), 400
        record.admin_status = payload["admin_status"]
    record.updated_at = datetime.now(UTC)
    db.session.commit()
    return jsonify(ok=True)


def _bug_json(record: BugReport) -> dict:
    user = db.session.get(User, record.user_id)
    data = {
        "id": record.id,
        "category": record.category,
        "title": record.title,
        "description": record.description,
        "context": record.context or {},
        "status": record.status,
        "admin_note": record.admin_note,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "resolved_at": record.resolved_at.isoformat() if record.resolved_at else None,
        "participant_id": _hash_user(record.user_id),
    }
    if current_app.config["ADMIN_SHOW_USER_EMAIL"]:
        data["email"] = user.email if user else None
    return data


@main_bp.get("/admin/bug-reports")
@login_required
def admin_bug_reports_page():
    if not current_user.is_admin:
        return jsonify(error="Not found"), 404
    return render_template(
        "admin_bug_reports.html",
        preferred_name=_preferred_name(),
        sidebar_mode="admin-bug-reports",
        bug_categories=BUG_CATEGORIES,
        bug_statuses=BUG_STATUSES,
    )


@main_bp.get("/api/admin/bug-reports")
@login_required
def api_admin_bug_reports():
    if not current_user.is_admin:
        return jsonify(error="Not found"), 404
    query = _admin_bug_query()
    if query is None:
        return jsonify(error="Invalid filter."), 400
    try:
        page = max(1, int(request.args.get("page", "1")))
    except (TypeError, ValueError):
        return jsonify(error="Invalid page."), 400
    sort = request.args.get("sort", "date_desc")
    if sort == "date_asc":
        query = query.order_by(BugReport.created_at.asc(), BugReport.id.asc())
    elif sort == "status":
        query = query.order_by(BugReport.status.asc(), BugReport.created_at.desc())
    else:
        query = query.order_by(BugReport.created_at.desc(), BugReport.id.desc())
    total = db.session.scalar(db.select(db.func.count()).select_from(query.subquery())) or 0
    records = db.session.scalars(query.offset((page - 1) * 20).limit(20)).all()
    counts = {
        status: db.session.scalar(db.select(db.func.count(BugReport.id)).where(BugReport.status == status)) or 0
        for status in BUG_STATUSES
    }
    category_counts = [
        {"category": category, "count": db.session.scalar(
            db.select(db.func.count(BugReport.id)).where(BugReport.category == category)
        ) or 0}
        for category in BUG_CATEGORIES
    ]
    oldest = db.session.scalar(
        db.select(BugReport.created_at)
        .where(BugReport.status.in_(("new", "in_progress")))
        .order_by(BugReport.created_at.asc())
        .limit(1)
    )
    oldest_unresolved_age = None
    if oldest:
        oldest_unresolved_age = max(0, int((datetime.now(UTC) - oldest.replace(tzinfo=UTC)).total_seconds() // 86400))
    return jsonify(
        items=[_bug_json(record) for record in records],
        page=page,
        total=total,
        total_pages=max(1, (total + 19) // 20),
        counts=counts,
        category_counts=category_counts,
        oldest_unresolved_age_days=oldest_unresolved_age,
        total_count=db.session.scalar(db.select(db.func.count(BugReport.id))) or 0,
    )


@main_bp.get("/api/admin/bug-reports/<int:report_id>")
@login_required
def api_admin_bug_report_detail(report_id: int):
    if not current_user.is_admin:
        return jsonify(error="Not found"), 404
    record = db.session.get(BugReport, report_id)
    if record is None:
        return jsonify(error="Not found"), 404
    return jsonify(_bug_json(record))


@main_bp.patch("/api/admin/bug-reports/<int:report_id>")
@login_required
def api_admin_bug_report_patch(report_id: int):
    if not current_user.is_admin:
        return jsonify(error="Not found"), 404
    record = db.session.get(BugReport, report_id)
    if record is None:
        return jsonify(error="Not found"), 404
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Request body must be a JSON object."), 400
    if "status" in payload:
        status = payload["status"]
        if status not in BUG_STATUSES:
            return jsonify(error="Invalid bug report status."), 400
        record.status = status
        record.resolved_at = datetime.now(UTC) if status == "resolved" else None
    if "admin_note" in payload:
        note = _clean_bug_text(payload["admin_note"] or "")
        if len(note) > 2000:
            return jsonify(error="Admin note must be 2,000 characters or fewer."), 400
        record.admin_note = note or None
    record.updated_at = datetime.now(UTC)
    db.session.commit()
    return jsonify(_bug_json(record))


@main_bp.post("/account/delete")
@login_required
@limiter.limit("3 per hour")
def delete_account():
    user_id = current_user.id
    for model in (
        MessageFeedback,
        BugReport,
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
    include_email = request.args.get("include_email") == "1"
    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["dataset", "user_hash"]
    if include_email and current_app.config["ADMIN_SHOW_USER_EMAIL"]:
        headers.append("email")
    headers += ["kind", "skill", "rating_before", "rating_after",
                "latency_ms", "tokens_in", "tokens_out", "est_cost_usd", "ts"]
    writer.writerow(headers)
    for event in db.session.scalars(db.select(RatingEvent)):
        row = ["rating_event", _hash_user(event.user_id)]
        if include_email and current_app.config["ADMIN_SHOW_USER_EMAIL"]:
            user = db.session.get(User, event.user_id)
            row.append(_csv_safe(user.email if user else ""))
        row += ["", event.skill, event.rating_before, event.rating_after, "", "", "", "", event.ts.isoformat()]
        writer.writerow(row)
    for metric in db.session.scalars(db.select(ApiMetric)):
        row = ["api_metric", _hash_user(metric.user_id)]
        if include_email and current_app.config["ADMIN_SHOW_USER_EMAIL"]:
            user = db.session.get(User, metric.user_id)
            row.append(_csv_safe(user.email if user else ""))
        row += [metric.kind, "", "", "", metric.latency_ms, metric.tokens_in, metric.tokens_out,
                metric.est_cost_usd, metric.ts.isoformat()]
        writer.writerow(row)
    for item in db.session.scalars(db.select(Feedback)):
        row = ["feedback", _hash_user(item.user_id)]
        if include_email and current_app.config["ADMIN_SHOW_USER_EMAIL"]:
            user = db.session.get(User, item.user_id)
            row.append(_csv_safe(user.email if user else ""))
        row += ["", "", "", "", "", "", "", "", item.ts.isoformat()]
        writer.writerow(row)
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=linguapath-export.csv"})


@main_bp.get("/admin/feedback/export.csv")
@login_required
def admin_feedback_export():
    if not current_user.is_admin:
        return jsonify(error="Not found"), 404
    include_email = request.args.get("include_email") == "1"
    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["id", "created_at", "updated_at", "schema_version", "revision", "participant_id",
               "q1", "q2", "q3", "q4", "q5", "comment", "consent_research", "admin_status"]
    if include_email and current_app.config["ADMIN_SHOW_USER_EMAIL"]:
        headers.append("email")
    writer.writerow(headers)
    for record in db.session.scalars(db.select(Feedback).order_by(Feedback.updated_at.desc(), Feedback.id.desc())):
        answers = record.answers if isinstance(record.answers, dict) else {}
        row = [
            record.id,
            record.created_at.isoformat() if record.created_at else record.ts.isoformat(),
            record.updated_at.isoformat(),
            record.schema_version,
            record.revision,
            _hash_user(record.user_id),
            *(answers.get(f"q{index}") if record.schema_version == 2 else "" for index in range(1, 6)),
            _csv_safe(record.free_text or ""),
            "true" if record.consent_research else "false",
            record.admin_status,
        ]
        if include_email and current_app.config["ADMIN_SHOW_USER_EMAIL"]:
            user = db.session.get(User, record.user_id)
            row.append(_csv_safe(user.email if user else ""))
        writer.writerow(row)
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=linguapath-feedback.csv"})


@main_bp.get("/admin/bug-reports/export.csv")
@login_required
def admin_bug_reports_export():
    if not current_user.is_admin:
        return jsonify(error="Not found"), 404
    query = _admin_bug_query()
    if query is None:
        return jsonify(error="Invalid filter."), 400
    include_email = request.args.get("include_email") == "1"
    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["id", "created_at", "status", "category", "title", "description", "page_path",
               "user_agent", "viewport", "app_version", "admin_note"]
    if include_email and current_app.config["ADMIN_SHOW_USER_EMAIL"]:
        headers.append("email")
    writer.writerow(headers)
    for record in db.session.scalars(query.order_by(BugReport.created_at.desc(), BugReport.id.desc())):
        context = record.context if isinstance(record.context, dict) else {}
        row = [
            record.id,
            record.created_at.isoformat(),
            record.status,
            _csv_safe(record.category),
            _csv_safe(record.title or ""),
            _csv_safe(record.description),
            _csv_safe(context.get("page_path", "")),
            _csv_safe(context.get("browser", "")),
            _csv_safe(context.get("viewport", "")),
            _csv_safe(context.get("app_version", "")),
            _csv_safe(record.admin_note or ""),
        ]
        if include_email and current_app.config["ADMIN_SHOW_USER_EMAIL"]:
            user = db.session.get(User, record.user_id)
            row.append(_csv_safe(user.email if user else ""))
        writer.writerow(row)
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=linguapath-bug-reports.csv"})


def _hash_user(user_id: int | None) -> str:
    return hashlib.sha256(f"{current_app.config['SECRET_KEY']}:{user_id}".encode()).hexdigest()[:16]


@main_bp.post("/api/chat")
@login_required
@limiter.limit(lambda: current_app.config["RATE_LIMIT_CHAT"])
def api_chat():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Request body must be a JSON object."), 400

    validation = validate_chat_content(
        payload.get("content", ""), current_app.config["CHAT_MESSAGE_MAX_CHARS"]
    )
    if validation.content is None:
        return jsonify(error=validation.error or "Invalid message."), 400
    content = validation.content

    conversation_id = payload.get("conversation_id")
    conversation = None
    if conversation_id is not None:
        if not isinstance(conversation_id, int) or isinstance(conversation_id, bool) or conversation_id < 1:
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
    valid = not skip_assessment and assessability(content).eligible
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
