"""Password hashing, Oracle sessions, and server-side authorization."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import hmac
import re
import secrets

from .database import get_connection


PBKDF2_ITERATIONS = 120_000
SALT_BYTES = 16
DIGEST_BYTES = 32


def _derive_password(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _derive_password(password, salt, PBKDF2_ITERATIONS)
    salt_hex = salt.hex()
    return f"pbkdf2${PBKDF2_ITERATIONS}${salt_hex}${digest.hex()}", salt_hex


def verify_password(password: str, stored_hash: str, stored_salt: str) -> tuple[bool, bool]:
    """Return whether the password matches and whether its verified hash needs upgrading."""
    try:
        algorithm, rounds, salt_hex, digest_hex = stored_hash.split("$")
        iterations = int(rounds)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False, False

    if (
        algorithm != "pbkdf2"
        or not 0 < iterations <= PBKDF2_ITERATIONS
        or salt_hex != stored_salt
        or not salt
        or len(expected) != DIGEST_BYTES
    ):
        return False, False

    calculated = _derive_password(password, salt, iterations)
    matches = hmac.compare_digest(calculated, expected)
    return matches, matches and (iterations < PBKDF2_ITERATIONS or len(salt) < SALT_BYTES)


def session_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Action(StrEnum):
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    ACCOUNT_READ = "ACCOUNT_READ"
    TRANSACTION_READ = "TRANSACTION_READ"
    TRANSFER = "TRANSFER"
    CARD_FREEZE = "CARD_FREEZE"
    CARD_UNFREEZE = "CARD_UNFREEZE"
    CUSTOMER_SEARCH = "CUSTOMER_SEARCH"
    CUSTOMER_READ = "CUSTOMER_READ"
    AUDIT_READ = "AUDIT_READ"
    USER_UNLOCK = "USER_UNLOCK"
    API_REQUEST = "API_REQUEST"
    CHAT = "CHAT"
    BALANCE_ENQUIRY = "BALANCE_ENQUIRY"
    TRANSACTION_DETAILS = "TRANSACTION_DETAILS"
    STATEMENT_REQUEST = "STATEMENT_REQUEST"
    CHANGE_OF_ADDRESS = "CHANGE_OF_ADDRESS"
    CHEQUE_BOOK_REQUEST = "CHEQUE_BOOK_REQUEST"
    KYC_UPDATE = "KYC_UPDATE"


STAFF_READS = {Action.CUSTOMER_SEARCH, Action.CUSTOMER_READ}
CUSTOMER_ACCOUNT_ACTIONS = {
    Action.ACCOUNT_READ, Action.TRANSACTION_READ, Action.TRANSFER, Action.CARD_FREEZE, Action.CARD_UNFREEZE,
    Action.BALANCE_ENQUIRY, Action.TRANSACTION_DETAILS, Action.STATEMENT_REQUEST, Action.CHEQUE_BOOK_REQUEST,
}
CUSTOMER_SCOPED_ACTIONS = {
    Action.CHAT, Action.CHANGE_OF_ADDRESS, Action.KYC_UPDATE, *CUSTOMER_ACCOUNT_ACTIONS,
}
ROLE_ACCESS = {
    "CUSTOMER": {Action.LOGOUT, *CUSTOMER_SCOPED_ACTIONS},
    "TELLER": {Action.LOGOUT, *STAFF_READS},
    "ADMIN": {Action.LOGOUT, *STAFF_READS, Action.AUDIT_READ, Action.USER_UNLOCK},
}
SESSION_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


class AuthError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        *,
        attempts_remaining: int | None = None,
        actor_id: str | None = None,
        target_id: str | int | None = None,
    ):
        super().__init__(code)
        self.status = status
        self.detail = {"code": code}
        self.actor_id = actor_id
        self.target_id = target_id
        if attempts_remaining is not None:
            self.detail["attempts_remaining"] = attempts_remaining


@dataclass(frozen=True, slots=True)
class SessionInfo:
    session_id: int
    user_id: str
    created_at: datetime | None
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: str
    role: str
    session: SessionInfo | None = None
    display_name: str | None = None


def utc_now() -> datetime:
    # Oracle's session and lock expiry timestamps have no time zone.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def authenticate(token: str | None, *, cursor=None, revoking: bool = False) -> AuthenticatedUser:
    """Resolve a bearer token and its current user against Oracle."""
    if token is None or SESSION_TOKEN_PATTERN.fullmatch(token) is None:
        raise AuthError(401, "INVALID_SESSION")

    if cursor is None:
        with get_connection() as connection, connection.cursor() as session_cursor:
            return authenticate(token, cursor=session_cursor, revoking=revoking)

    cursor.execute(
        """
        SELECT u.id, u.role, u.status, s.expires_at, u.locked_until, s.id, s.created_at, u.name
        FROM bank_sessions s
        JOIN bank_users u ON u.id = s.user_id
        WHERE s.token = :token_digest
        FOR UPDATE OF s.token
        """,
        token_digest=session_digest(token),
    )
    row = cursor.fetchone()
    if row is None:
        raise AuthError(401, "INVALID_SESSION")

    user_id, role, status, expires_at, locked_until, session_id, created_at, display_name = row
    now = utc_now()
    inactive = status != "ACTIVE" or expires_at <= now or (locked_until and locked_until > now)
    if role is None or (inactive and not revoking):
        raise AuthError(401, "INVALID_SESSION", actor_id=user_id)
    return AuthenticatedUser(
        user_id, role, SessionInfo(session_id, user_id, created_at, expires_at), display_name,
    )


def authorize(user: AuthenticatedUser, target_user_id: str, action: Action) -> None:
    """Check the current user's role and ownership before acting on a target."""
    if action not in ROLE_ACCESS.get(user.role, ()):
        raise AuthError(403, "FORBIDDEN", target_id=target_user_id)
    if action in CUSTOMER_SCOPED_ACTIONS and target_user_id != user.id:
        raise AuthError(403, "FORBIDDEN", target_id=target_user_id)
