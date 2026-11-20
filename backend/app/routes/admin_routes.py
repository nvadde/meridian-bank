"""Staff customer lookup, admin unlock, and admin audit-log access."""

from typing import Annotated

from fastapi import APIRouter, Path, Query

from .. import auth
from ..authorization import Action, AuthError, USER_ID_PATTERN, authorized_access
from .auth_routes import SessionToken, token_value


router = APIRouter()
UserId = Annotated[str, Path(pattern=USER_ID_PATTERN)]
Search = Annotated[str | None, Query(max_length=150)]
PageSize = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0)]


def _customer_record(row):
    user_id, name, email, status = row
    return {"id": user_id, "name": name, "email": email, "status": status}


@router.get("/customers")
def search_customers(credentials: SessionToken, q: Search = None, limit: PageSize = 50, offset: PageOffset = 0):
    with authorized_access(token_value(credentials), Action.CUSTOMER_SEARCH) as (cursor, _):
        cursor.execute(
            """
            SELECT id, name, email, status FROM bank_users
            WHERE role = 'CUSTOMER'
              AND (:search IS NULL OR INSTR(LOWER(id), :search) > 0
                   OR INSTR(LOWER(name), :search) > 0 OR INSTR(LOWER(email), :search) > 0)
            ORDER BY id OFFSET :page_offset ROWS FETCH NEXT :page_size ROWS ONLY
            """,
            search=q.strip().lower() if q else None,
            page_offset=offset,
            page_size=limit,
        )
        return [_customer_record(row) for row in cursor]


@router.get("/customers/{user_id}")
def get_customer(user_id: UserId, credentials: SessionToken):
    with authorized_access(token_value(credentials), Action.CUSTOMER_READ, user_id=user_id) as (cursor, _):
        cursor.execute(
            "SELECT id, name, email, status FROM bank_users WHERE role = 'CUSTOMER' AND id = :user_id",
            user_id=user_id,
        )
        row = cursor.fetchone()
        if row is None:
            raise AuthError(404, "USER_NOT_FOUND")
        return _customer_record(row)


@router.get("/admin/audit-logs")
def list_audit_logs(credentials: SessionToken, limit: PageSize = 50, offset: PageOffset = 0):
    with authorized_access(token_value(credentials), Action.AUDIT_READ) as (cursor, _):
        cursor.execute(
            """
            SELECT id, user_id, action, result, details, created_at FROM bank_audit_logs
            ORDER BY created_at DESC NULLS LAST, id DESC
            OFFSET :page_offset ROWS FETCH NEXT :page_size ROWS ONLY
            """,
            page_offset=offset,
            page_size=limit,
        )
        return [
            dict(id=str(id), user_id=actor, action=action, result=result, details=details, created_at=created)
            for id, actor, action, result, details, created in cursor
        ]


@router.post("/admin/users/{user_id}/unlock", status_code=204)
def unlock_user(user_id: UserId, credentials: SessionToken) -> None:
    auth.unlock_user(token_value(credentials), user_id)
