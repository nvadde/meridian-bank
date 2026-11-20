"""Enforce and audit security decisions before accessing bank data."""

from collections.abc import Callable
from contextlib import contextmanager

from .audit import record_access
from .database import get_connection
from .security import (
    CUSTOMER_ACCOUNT_ACTIONS,
    Action,
    AuthError,
    AuthenticatedUser,
    authenticate,
    authorize,
    utc_now,
)


USER_ID_PATTERN = r"^[A-Za-z0-9_-]{1,20}$"


def owns_account(cursor, actor_id: str, account_id: int) -> bool:
    # Only check ownership here. Financial data is read after authorization.
    cursor.execute(
        "SELECT 1 FROM bank_accounts WHERE id = :account_id AND user_id = :actor_id",
        account_id=account_id,
        actor_id=actor_id,
    )
    return cursor.fetchone() is not None


@contextmanager
def authorized_context(
    token: str | None,
    action: Action,
    *,
    user_id: str | None = None,
    account_id: int | None = None,
    destination_id: int | None = None,
    on_authenticated: Callable[[AuthenticatedUser], None] | None = None,
):
    with get_connection() as connection, connection.cursor() as cursor:
        target_id = account_id if account_id is not None else user_id
        actor_id = None
        try:
            user = authenticate(token, cursor=cursor, revoking=action == Action.LOGOUT)
            actor_id = user.id
            if on_authenticated is not None:
                on_authenticated(user)
            authorize(user, user.id if user_id is None else user_id, action)
            if action in CUSTOMER_ACCOUNT_ACTIONS and any(
                not owns_account(cursor, user.id, candidate)
                for candidate in (account_id, destination_id)
                if candidate is not None
            ):
                raise AuthError(403, "FORBIDDEN")
        except AuthError as error:
            record_access(
                cursor, action, "DENIED", actor_id or error.actor_id, reason=str(error), target_id=target_id,
            )
            connection.commit()
            raise

        cursor.execute("SAVEPOINT before_operation")
        record_access(cursor, action, "ALLOWED", actor_id, target_id=target_id)
        try:
            yield cursor, user
        except Exception as error:
            cursor.execute("ROLLBACK TO SAVEPOINT before_operation")
            if isinstance(error, AuthError):
                denied_target = error.target_id if error.target_id is not None else target_id
                record_access(cursor, action, "DENIED", actor_id, reason=str(error), target_id=denied_target)
            else:
                record_access(cursor, action, "ALLOWED", actor_id, target_id=target_id)
            connection.commit()
            raise
        else:
            connection.commit()


@contextmanager
def authorized_access(
    token: str | None,
    action: Action,
    *,
    user_id: str | None = None,
    account_id: int | None = None,
    destination_id: int | None = None,
):
    with authorized_context(
        token, action, user_id=user_id, account_id=account_id, destination_id=destination_id,
    ) as (cursor, user):
        yield cursor, user.id


def audit_rejected_request(token: str | None, reason: str) -> None:
    with get_connection() as connection, connection.cursor() as cursor:
        try:
            actor_id = authenticate(token, cursor=cursor).id
        except AuthError as error:
            actor_id = error.actor_id
        record_access(cursor, Action.API_REQUEST, "DENIED", actor_id, reason=reason)
        connection.commit()
