import json
import logging
from dataclasses import asdict, dataclass, field

import psycopg

from .adaptive import LearnerState

log = logging.getLogger(__name__)


class DatabaseUnavailableError(RuntimeError):
    """Raised when the conversation database cannot be reached."""


@dataclass
class Conversation:
    history: list[dict] = field(default_factory=list)
    state: LearnerState = field(default_factory=LearnerState)


class SessionStore:
    def __init__(self, database_url: str | None):
        if not database_url:
            raise RuntimeError("DATABASE_URL не задано. Додай його у файл .env")
        self._database_url = database_url
        self._initialize()

    def _connect(self):
        try:
            return psycopg.connect(self._database_url)
        except psycopg.Error as exc:
            log.exception("PostgreSQL connection failed")
            raise DatabaseUnavailableError(
                "Не вдалося підключитися до бази даних. Перевір DATABASE_URL і доступність PostgreSQL."
            ) from exc

    def _initialize(self) -> None:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS conversations (
                            session_id TEXT PRIMARY KEY,
                            history JSONB NOT NULL DEFAULT '[]'::jsonb,
                            state JSONB NOT NULL DEFAULT '{}'::jsonb,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
        except DatabaseUnavailableError:
            raise
        except psycopg.Error as exc:
            log.exception("PostgreSQL schema initialization failed")
            raise DatabaseUnavailableError(
                "Не вдалося підготувати таблицю розмов у базі даних."
            ) from exc

    def get(self, sid: str) -> Conversation:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT history, state
                        FROM conversations
                        WHERE session_id = %s
                        """,
                        (sid,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        conversation = Conversation()
                        self.save(sid, conversation, connection=connection)
                        return conversation
                    return self._deserialize(row[0], row[1])
        except DatabaseUnavailableError:
            raise
        except psycopg.Error as exc:
            log.exception("Failed to load conversation from PostgreSQL")
            raise DatabaseUnavailableError(
                "Не вдалося завантажити розмову з бази даних."
            ) from exc

    def reset(self, sid: str, level: str = "beginner") -> Conversation:
        conversation = Conversation(state=LearnerState.from_level(level))
        self.save(sid, conversation)
        return conversation

    def save(self, sid: str, conversation: Conversation, connection=None) -> None:
        try:
            if connection is None:
                with self._connect() as owned_connection:
                    self.save(sid, conversation, connection=owned_connection)
                return

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversations (session_id, history, state, updated_at)
                    VALUES (%s, %s::jsonb, %s::jsonb, NOW())
                    ON CONFLICT (session_id) DO UPDATE SET
                        history = EXCLUDED.history,
                        state = EXCLUDED.state,
                        updated_at = NOW()
                    """,
                    (
                        sid,
                        json.dumps(conversation.history),
                        json.dumps(asdict(conversation.state)),
                    ),
                )
        except DatabaseUnavailableError:
            raise
        except psycopg.Error as exc:
            log.exception("Failed to save conversation to PostgreSQL")
            raise DatabaseUnavailableError(
                "Не вдалося зберегти розмову в базі даних."
            ) from exc

    @staticmethod
    def _deserialize(history: list[dict], state: dict) -> Conversation:
        return Conversation(
            history=history,
            state=LearnerState(
                k=state.get("k", 0.3),
                errors=state.get("errors", 0),
                avg_response_time=state.get("avg_response_time", 1.0),
                last_time=state.get("last_time"),
            ),
        )
