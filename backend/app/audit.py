"""Write banking access decisions to the Oracle audit log."""

import json
import secrets
from typing import Any


def record_access(
    cursor: Any,
    action: str,
    result: str,
    actor_id: str | None,
    *,
    reason: str | None = None,
    target_id: str | int | None = None,
) -> None:
    details = {}
    if reason is not None:
        details["reason"] = reason
    if target_id is not None:
        details["target_id"] = target_id
    cursor.execute(
        """
        INSERT INTO bank_audit_logs (id, user_id, action, result, details, created_at)
        VALUES (:id, :actor_id, :action, :result, :details, SYS_EXTRACT_UTC(SYSTIMESTAMP))
        """,
        id=secrets.randbelow(2**63 - 1) + 1,
        actor_id=actor_id,
        action=action,
        result=result,
        details=json.dumps(details) if details else None,
    )
