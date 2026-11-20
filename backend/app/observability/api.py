"""Admin-only Mira observability dashboard data."""

from datetime import date, datetime, timezone
import json
from shutil import disk_usage

from fastapi import APIRouter
import psutil

from ..authorization import Action, authorized_access
from ..database import PROJECT_ROOT
from ..routes.auth_routes import SessionToken, token_value
from .cost_tracker import daily_usage


router = APIRouter()


def _recent(cursor, action: str) -> list[dict]:
    cursor.execute(
        """
        SELECT user_id, action, result, details, created_at
        FROM bank_audit_logs
        WHERE action = :event_name
        ORDER BY created_at DESC, id DESC FETCH FIRST 20 ROWS ONLY
        """,
        event_name=action,
    )
    events = []
    for user, name, status, raw_details, created in cursor:
        details = json.loads(raw_details)
        events.append({
            "timestamp": created.replace(tzinfo=timezone.utc).isoformat(),
            "user_id": user,
            "event": name,
            "status": status,
            "session_id": details.get("session_id"),
            "trace_id": details.get("trace_id"),
            "description": details.get("text") or details.get("name"),
        })
    return events


@router.get("/admin/observability")
def get_observability(credentials: SessionToken, day: date | None = None):
    with authorized_access(token_value(credentials), Action.AUDIT_READ) as (cursor, _):
        usage = daily_usage(cursor, day or datetime.now(timezone.utc).date())
        prompts = _recent(cursor, "MIRA_PROMPT")
        tools = _recent(cursor, "MIRA_TOOL_CALL")
        storage = disk_usage(PROJECT_ROOT)
        return {
            "resources": {
                "cpu": psutil.cpu_percent(interval=0.1),
                "memory": psutil.virtual_memory().percent,
                "disk": 100 * storage.used / storage.total,
            },
            "usage": usage,
            "prompts": prompts,
            "tools": tools,
        }
