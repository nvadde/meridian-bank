"""Oracle-backed session identities with process-local Mira conversations."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import secrets
from threading import RLock
from typing import Literal, TypedDict

from ..database import get_connection
from ..security import AuthError, SessionInfo, session_digest, utc_now


MIRA_SESSION_DURATION = timedelta(hours=2)
MessageRole = Literal["user", "assistant", "system", "tool"]


class Message(TypedDict):
    role: MessageRole
    text: str
    timestamp: str


@dataclass(frozen=True, slots=True)
class CreatedSession:
    session_id: int
    token: str = field(repr=False)


@dataclass(slots=True)
class Conversation:
    session: SessionInfo
    messages: list[Message] = field(default_factory=list)
    shared_state: dict = field(default_factory=lambda: {
        "current_account_id": None,
        "last_intent": None,
        "last_tool_result": None,
    })
    lock: RLock = field(default_factory=RLock, repr=False)

    def get_history(self) -> list[Message]:
        return deepcopy(self.messages)

    def get_shared_state(self) -> dict:
        return deepcopy(self.shared_state)

    def add_message(self, role: MessageRole, text: str) -> None:
        if role not in ("user", "assistant", "system", "tool"):
            raise ValueError("Invalid Mira message role")
        self.messages.append({
            "role": role,
            "text": text,
            "timestamp": utc_now().replace(tzinfo=timezone.utc).isoformat(),
        })

    def update_shared_state(self, key: str, value: object) -> None:
        if key not in self.shared_state:
            raise KeyError(key)
        self.shared_state[key] = deepcopy(value)

    def record_exchange(self, message: str, reply: str, state_updates: dict) -> None:
        for key, value in state_updates.items():
            self.update_shared_state(key, value)
        self.add_message("user", message)
        self.add_message("assistant", reply)


_sessions: dict[int, Conversation] = {}
_sessions_lock = RLock()


def create_session(user_id: str, *, cursor=None, login_duration=MIRA_SESSION_DURATION) -> CreatedSession:
    """Create an Oracle session and return the bearer token once, on creation."""
    if cursor is None:
        with get_connection() as connection, connection.cursor() as session_cursor:
            result = create_session(user_id, cursor=session_cursor, login_duration=login_duration)
            connection.commit()
            return result

    session_id = secrets.randbelow(2**63 - 1) + 1
    token = secrets.token_urlsafe(32)
    now = utc_now()
    cursor.execute(
        """
        INSERT INTO bank_sessions (id, user_id, token, created_at, expires_at)
        VALUES (:session_id, :user_id, :token_digest, :issued_at, :expires_at)
        """,
        session_id=session_id,
        user_id=user_id,
        token_digest=session_digest(token),
        issued_at=now,
        expires_at=now + login_duration,
    )
    return CreatedSession(session_id, token)


def _expires_at(session: SessionInfo) -> datetime | None:
    if session.created_at is None:
        return None
    return min(session.expires_at, session.created_at + MIRA_SESSION_DURATION)


def _is_expired(session: SessionInfo, now: datetime) -> bool:
    deadline = _expires_at(session)
    return deadline is None or deadline <= now


def require_mira_session(session: SessionInfo | None) -> None:
    if session is None or _is_expired(session, utc_now()):
        raise AuthError(401, "INVALID_SESSION")


@contextmanager
def open_conversation(session: SessionInfo):
    """Use metadata from a verified Oracle session and serialize its in-memory turns."""
    with _sessions_lock:
        now = utc_now()
        for session_id in [key for key, turn in _sessions.items() if _is_expired(turn.session, now)]:
            del _sessions[session_id]
        if _is_expired(session, now):
            raise AuthError(401, "INVALID_SESSION")

        conversation = _sessions.get(session.session_id)
        if conversation is None or conversation.session != session:
            conversation = Conversation(session)
            _sessions[session.session_id] = conversation

    with conversation.lock:
        if _is_expired(session, utc_now()):
            raise AuthError(401, "INVALID_SESSION")
        yield conversation


def clear_session(session_id: int) -> None:
    with _sessions_lock:
        _sessions.pop(session_id, None)


@contextmanager
def _open_stored_session(session_id: int):
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, user_id, created_at, expires_at
            FROM bank_sessions WHERE id = :session_id
            FOR UPDATE
            """,
            session_id=session_id,
        )
        row = cursor.fetchone()
        if row is None or row[1] is None:
            clear_session(session_id)
            raise AuthError(401, "INVALID_SESSION")
        with open_conversation(SessionInfo(*row)) as conversation:
            yield conversation


def get_history(session_id: int) -> list[Message]:
    with _open_stored_session(session_id) as conversation:
        return conversation.get_history()


def add_message(session_id: int, role: MessageRole, text: str) -> None:
    with _open_stored_session(session_id) as conversation:
        conversation.add_message(role, text)


def get_shared_state(session_id: int) -> dict:
    with _open_stored_session(session_id) as conversation:
        return conversation.get_shared_state()


def update_shared_state(session_id: int, key: str, value: object) -> None:
    with _open_stored_session(session_id) as conversation:
        conversation.update_shared_state(key, value)
