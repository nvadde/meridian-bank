"""Persist privacy-filtered Mira traces to Oracle and a rotating JSON-lines file."""

from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import secrets
from threading import Lock
from uuid import uuid4

from ..database import PROJECT_ROOT, get_connection
from ..llm.pii_redaction import redact_text
from ..security import AuthError, AuthenticatedUser


LOG_PATH = PROJECT_ROOT / "backend" / "logs" / "mira.jsonl"
_fallback = logging.getLogger("uvicorn.error.mira_observability")
_file_lock = Lock()
_file_handler: RotatingFileHandler | None = None


def _write_file(rows: list[dict]) -> None:
    global _file_handler
    with _file_lock:
        if _file_handler is None:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _file_handler = RotatingFileHandler(LOG_PATH, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        for row in rows:
            message = json.dumps(row, ensure_ascii=True)
            _file_handler.emit(logging.LogRecord("mira", logging.INFO, "", 0, message, (), None))


def _audit_details(row: dict) -> str:
    details = {"trace_id": row["trace_id"], "session_id": row["session_id"], **row["details"]}
    encoded = json.dumps(details, ensure_ascii=True, separators=(",", ":"))
    if len(encoded) <= 500:
        return encoded
    if "text" in details:
        details["text"] = details["text"][:64]
        details["truncated"] = True
        encoded = json.dumps(details, ensure_ascii=True, separators=(",", ":"))
    if len(encoded) > 500:
        details.pop("text", None)
        encoded = json.dumps(details, ensure_ascii=True, separators=(",", ":"))
    return encoded


def _write_audit(rows: list[dict]) -> None:
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO bank_audit_logs (id, user_id, action, result, details, created_at)
            VALUES (:row_id, :actor_id, :event, :outcome, :details, :occurred_at)
            """,
            [
                {
                    "row_id": secrets.randbelow(2**63 - 1) + 1,
                    "actor_id": row["user_id"],
                    "event": row["event"],
                    "outcome": row["status"],
                    "details": _audit_details(row),
                    "occurred_at": datetime.fromisoformat(row["timestamp"]).replace(tzinfo=None),
                }
                for row in rows
            ],
        )
        connection.commit()


def _error_code(error: Exception) -> str:
    return str(error) if isinstance(error, AuthError) else type(error).__name__


def _result_summary(value) -> dict:
    if isinstance(value, list):
        return {"items": len(value)}
    if isinstance(value, dict) and "tool_called" in value:
        summary = {"tool": value["tool_called"]}
        if isinstance(value.get("tool_result"), list):
            summary["items"] = len(value["tool_result"])
        return summary
    if isinstance(value, str):
        return {"characters": len(value)}
    return {}


class Trace:
    def __init__(self, *, source: str = "chat"):
        self.id = uuid4().hex[:16]
        self.source = source
        self.user_id: str | None = None
        self.session_id: str | None = None
        self._events: list[dict] = []
        self._lock = Lock()
        self._prompt_logged = False

    def bind(self, user: AuthenticatedUser) -> None:
        self.user_id = user.id
        self.session_id = str(user.session.session_id) if user.session else None
        with self._lock:
            for event in self._events:
                event["user_id"] = self.user_id
                event["session_id"] = self.session_id

    def record(self, event: str, outcome: str, **details) -> None:
        with self._lock:
            self._events.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "MIRA_" + event,
                "status": outcome,
                "user_id": self.user_id,
                "session_id": self.session_id,
                "trace_id": self.id,
                "details": {"source": self.source, **details},
            })

    def prompt(self, text: str) -> None:
        self._prompt_logged = True
        self.record("PROMPT", "RECEIVED", text=redact_text(text)[:320])

    def llm_prompt(self, text: str) -> None:
        self.record("LLM_PROMPT", "SENT", text=redact_text(text)[:320])

    def usage(self, metrics: dict) -> None:
        self.record("LLM_USAGE", metrics["status"].upper(), **metrics)

    def call(self, kind: str, name: str, operation, *args, **kwargs):
        self.record(kind + "_CALL", "STARTED", name=name)
        try:
            result = operation(*args, **kwargs)
        except Exception as error:
            self.record(kind + "_RESULT", "ERROR", name=name, error=_error_code(error))
            raise
        self.record(kind + "_RESULT", "OK", name=name, **_result_summary(result))
        return result

    def __enter__(self):
        return self

    def __exit__(self, _error_type, error, _traceback) -> None:
        if self.source == "chat" and not self._prompt_logged:
            self.prompt("[prompt withheld before validation]")
        if error is not None:
            self.record("ERROR", "ERROR", error=_error_code(error))
        if not self._events:
            return
        for sink in (_write_file, _write_audit):
            try:
                sink(self._events)
            except Exception as sink_error:
                _fallback.error("Mira trace %s sink %s failed (%s)", self.id, sink.__name__, type(sink_error).__name__)
