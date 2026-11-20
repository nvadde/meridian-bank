"""Oracle-backed account authentication and session management."""

from datetime import timedelta

from .audit import record_access
from .authorization import Action, AuthError, authorized_access, authorized_context, utc_now
from .database import get_connection
from .security import hash_password, verify_password
from .session.session_store import clear_session, create_session


MAX_ATTEMPTS = 5
LOCK_DURATION = timedelta(minutes=15)
SESSION_DURATION = timedelta(hours=8)


def _deny_login(connection, cursor, error: AuthError, actor_id: str | None) -> None:
    record_access(cursor, Action.LOGIN, "DENIED", actor_id, reason=str(error))
    connection.commit()
    raise error


def login(email: str, password: str) -> str:
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, password_hash, salt, status, failed_attempts, locked_until
            FROM bank_users
            WHERE LOWER(email) = :email
            FOR UPDATE
            """,
            email=email.strip().lower(),
        )
        users = cursor.fetchmany(2)
        if len(users) != 1 or users[0][3] != "ACTIVE":
            hash_password(password)
            _deny_login(
                connection, cursor,
                AuthError(401, "INVALID_CREDENTIALS", attempts_remaining=MAX_ATTEMPTS - 1),
                users[0][0] if len(users) == 1 else None,
            )

        user_id, stored_hash, stored_salt, _, failed_attempts, locked_until = users[0]
        now = utc_now()
        if locked_until and locked_until > now:
            _deny_login(
                connection, cursor, AuthError(423, "ACCOUNT_LOCKED", attempts_remaining=0), user_id,
            )

        matches, needs_upgrade = verify_password(password, stored_hash, stored_salt)
        if not matches:
            failed_attempts = 1 if locked_until else (failed_attempts or 0) + 1
            attempts_remaining = max(0, MAX_ATTEMPTS - failed_attempts)
            new_deadline = now + LOCK_DURATION if attempts_remaining == 0 else None
            cursor.execute(
                """
                UPDATE bank_users
                SET failed_attempts = :attempts, locked_until = :deadline
                WHERE id = :user_id
                """,
                attempts=failed_attempts,
                deadline=new_deadline,
                user_id=user_id,
            )
            error = (
                AuthError(423, "ACCOUNT_LOCKED", attempts_remaining=0)
                if new_deadline
                else AuthError(401, "INVALID_CREDENTIALS", attempts_remaining=attempts_remaining)
            )
            _deny_login(connection, cursor, error, user_id)

        if needs_upgrade:
            stored_hash, stored_salt = hash_password(password)
        cursor.execute(
            """
            UPDATE bank_users
            SET failed_attempts = 0, locked_until = NULL,
                password_hash = :password_hash, salt = :salt
            WHERE id = :user_id
            """,
            password_hash=stored_hash,
            salt=stored_salt,
            user_id=user_id,
        )
        session = create_session(user_id, cursor=cursor, login_duration=SESSION_DURATION)
        record_access(cursor, Action.LOGIN, "ALLOWED", user_id)
        connection.commit()
        return session.token


def logout(token: str | None) -> None:
    with authorized_context(token, Action.LOGOUT) as (cursor, user):
        if user.session is None:
            raise AuthError(401, "INVALID_SESSION")
        session_id = user.session.session_id
        cursor.execute(
            "DELETE FROM bank_sessions WHERE id = :session_id AND user_id = :actor_id",
            session_id=session_id,
            actor_id=user.id,
        )
    clear_session(session_id)


def unlock_user(token: str | None, user_id: str) -> None:
    with authorized_access(token, Action.USER_UNLOCK, user_id=user_id) as (cursor, _):
        cursor.execute(
            """
            UPDATE bank_users SET failed_attempts = 0, locked_until = NULL
            WHERE id = :user_id
            """,
            user_id=user_id,
        )
        if cursor.rowcount == 0:
            raise AuthError(404, "USER_NOT_FOUND")
