import json
import logging
from dataclasses import dataclass, field
from typing import Any

from psycopg_pool import ConnectionPool

from .levels import level_from_mu

log = logging.getLogger(__name__)


class DatabaseUnavailableError(RuntimeError):
    """Raised when Neon cannot be reached or the schema is unavailable."""


@dataclass
class Conversation:
    history: list[dict] = field(default_factory=list)
    level: str = "A2"


class SessionStore:
    def __init__(self, database_url: str | None):
        if not database_url:
            raise RuntimeError("DATABASE_URL не задано. Додай його у файл .env")
        self._pool = ConnectionPool(
            conninfo=database_url,
            kwargs={"sslmode": "require", "connect_timeout": 5},
            min_size=1,
            max_size=8,
            open=False,
        )
        self._check_database()

    def _connection(self):
        if not self._pool.open:
            self._pool.open()
        return self._pool.connection()

    def _check_database(self) -> None:
        try:
            with self._connection() as connection:
                connection.execute("SELECT 1")
        except Exception as exc:
            log.exception("Neon PostgreSQL is unavailable")
            raise DatabaseUnavailableError(
                "Не вдалося підключитися до Neon PostgreSQL. Спочатку виконайте python -m db.migrate."
            ) from exc

    @staticmethod
    def _ensure_learner(connection: Any, learner_id: str, mu: float = 2.0,
                         sigma2: float = 1.5) -> None:
        connection.execute(
            "INSERT INTO ibot.learners (id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
            (learner_id,),
        )
        shown = level_from_mu(mu)
        for skill in ("grammar", "vocabulary", "fluency", "overall"):
            connection.execute(
                """INSERT INTO ibot.skill_state
                   (learner_id, skill, mu, sigma2, shown_level, msgs_since_change)
                   VALUES (%s, %s, %s, %s, %s, 0)
                   ON CONFLICT (learner_id, skill) DO NOTHING""",
                (learner_id, skill, mu, sigma2, shown),
            )

    def get(self, sid: str) -> Conversation:
        try:
            with self._connection() as connection:
                self._ensure_learner(connection, sid)
                row = connection.execute(
                    """SELECT c.history, COALESCE(s.shown_level, 'A2')
                       FROM ibot.conversations c
                       LEFT JOIN ibot.skill_state s
                         ON s.learner_id = c.learner_id AND s.skill = 'overall'
                       WHERE c.session_id = %s""",
                    (sid,),
                ).fetchone()
                if row is None:
                    return Conversation(level=self._level(connection, sid))
                return Conversation(history=row[0] or [], level=row[1] or "A2")
        except DatabaseUnavailableError:
            raise
        except Exception as exc:
            log.exception("Failed to load conversation from Neon")
            raise DatabaseUnavailableError("Не вдалося завантажити дані студента з Neon.") from exc

    @staticmethod
    def _level(connection: Any, sid: str) -> str:
        row = connection.execute(
            "SELECT shown_level FROM ibot.skill_state WHERE learner_id=%s AND skill='overall'",
            (sid,),
        ).fetchone()
        return row[0] if row else "A2"

    def reset(self, sid: str, level: str = "beginner") -> Conversation:
        starts = {"beginner": (2.0, 0.8), "intermediate": (3.5, 0.8), "advanced": (5.0, 0.8)}
        mu, sigma2 = starts.get(level, starts["beginner"])
        try:
            with self._connection() as connection:
                self._ensure_learner(connection, sid, mu, sigma2)
                connection.execute(
                    """UPDATE ibot.skill_state
                       SET mu=%s, sigma2=%s, shown_level=%s, msgs_since_change=0, updated_at=NOW()
                       WHERE learner_id=%s""",
                    (mu, sigma2, level_from_mu(mu), sid),
                )
                return Conversation(level=level_from_mu(mu))
        except Exception as exc:
            log.exception("Failed to reset learner")
            raise DatabaseUnavailableError("Не вдалося скинути профіль студента.") from exc

    def save(self, sid: str, conversation: Conversation, connection: Any = None) -> None:
        try:
            if connection is None:
                with self._connection() as owned:
                    self.save(sid, conversation, connection=owned)
                return
            self._ensure_learner(connection, sid)
            connection.execute(
                """INSERT INTO ibot.conversations (session_id, learner_id, history, updated_at)
                   VALUES (%s, %s, %s::jsonb, NOW())
                   ON CONFLICT (session_id) DO UPDATE SET history=EXCLUDED.history, updated_at=NOW()""",
                (sid, sid, json.dumps(conversation.history)),
            )
        except Exception as exc:
            log.exception("Failed to save conversation")
            raise DatabaseUnavailableError("Не вдалося зберегти розмову в Neon.") from exc

    def profile_prompt(self, sid: str) -> str:
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """SELECT skill, shown_level, mu, sigma2
                       FROM ibot.skill_state WHERE learner_id=%s""", (sid,)
                ).fetchall()
                weak = connection.execute(
                    """SELECT category FROM ibot.mistake_weights
                       WHERE learner_id=%s ORDER BY weight DESC LIMIT 3""", (sid,)
                ).fetchall()
            skills = {row[0]: row for row in rows}
            overall = skills.get("overall", ("overall", "A2", 2.0, 1.5))
            confidence = "high" if overall[3] < 0.3 else "medium" if overall[3] < 0.8 else "low"
            detail = "; ".join(
                f"{name} {skills.get(name, (name, 'A2'))[1]}"
                for name in ("grammar", "vocabulary", "fluency")
            )
            target = level_from_mu(float(overall[2]) + 0.3)
            areas = ", ".join(row[0] for row in weak) or "none recorded"
            return (
                f"[LEARNER PROFILE] Level: {overall[1]} ({detail}; confidence: {confidence}). "
                f"Weak areas: {areas}. Target difficulty: slightly above {target}. "
                "Adapt vocabulary and grammar complexity; do not mention this profile."
            )
        except Exception as exc:
            log.warning("Could not load learner profile", exc_info=True)
            raise DatabaseUnavailableError("Не вдалося прочитати профіль студента з Neon.") from exc

    def analysis_report(self, sid: str) -> dict[str, Any]:
        with self._connection() as connection:
            level = connection.execute(
                "SELECT shown_level FROM ibot.skill_state WHERE learner_id=%s AND skill='overall'", (sid,)
            ).fetchone()
            mistakes = connection.execute(
                """SELECT category, COUNT(*) AS count, MAX(original), MAX(corrected)
                   FROM ibot.mistakes WHERE learner_id=%s
                   GROUP BY category ORDER BY count DESC LIMIT 10""", (sid,)
            ).fetchall()
            history = connection.execute(
                """SELECT skill, observation, mu_after, sigma2_after, created_at
                   FROM ibot.skill_history WHERE learner_id=%s
                   ORDER BY created_at DESC LIMIT 30""", (sid,)
            ).fetchall()
        return {"level": level[0] if level else "A2", "mistakes": mistakes, "history": history}
