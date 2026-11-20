"""Mira transaction details and monthly statement MCP server."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated

from mcp.server.fastmcp import Context
from pydantic import BaseModel, Field

from ..audit import record_access
from ..authorization import owns_account
from ..security import Action, AuthError, AuthenticatedUser, authorize
from .tool_server import AccountId, ToolServer, UserId, invoke, redact_account_numbers


server = ToolServer("Meridian Transactions")
RowLimit = Annotated[int, Field(strict=True, ge=1, le=100)]
Month = Annotated[str, Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")]


class Transaction(BaseModel):
    transaction_id: int
    description: str | None
    amount: Decimal
    timestamp: datetime | None
    category: str | None


def _read_transactions(
    cursor,
    user: AuthenticatedUser,
    account_id: int,
    *,
    limit: int | None = None,
    period: tuple[datetime, datetime] | None = None,
) -> list[Transaction]:
    # Both optional SQL clauses are fixed literals. All data values are bound.
    date_filter = "AND t.txn_date >= :month_start AND t.txn_date < :month_end" if period else ""
    row_limit = "FETCH FIRST :row_limit ROWS ONLY" if limit is not None else ""
    params = {"account_id": account_id, "user_id": user.id}
    if period is not None:
        params.update(month_start=period[0], month_end=period[1])
    if limit is not None:
        params["row_limit"] = limit
    cursor.execute(
        f"""
        SELECT t.id, t.description, t.amount, t.txn_date, t.category
        FROM bank_transactions t JOIN bank_accounts a ON a.id = t.account_id
        WHERE t.account_id = :account_id AND a.user_id = :user_id
        {date_filter}
        ORDER BY t.txn_date DESC NULLS LAST, t.id DESC
        {row_limit}
        """,
        params,
        fetch_decimals=True,
    )
    return [
        Transaction(
            transaction_id=int(transaction_id),
            description=redact_account_numbers(description),
            amount=amount,
            timestamp=timestamp,
            category=redact_account_numbers(category),
        )
        for transaction_id, description, amount, timestamp, category in cursor
    ]


@server.tool()
async def transaction_details(
    user_id: UserId, account_id: AccountId, ctx: Context, limit: RowLimit = 5,
) -> list[Transaction]:
    """Return the last N transactions for an account the signed-in customer owns."""
    def read(cursor, user):
        return _read_transactions(cursor, user, account_id, limit=limit)

    return await invoke(ctx, Action.TRANSACTION_DETAILS, user_id, read, account_id=account_id)


def _month_period(month: str) -> tuple[datetime, datetime]:
    try:
        start = datetime.strptime(month, "%Y-%m")
        return start, (start + timedelta(days=32)).replace(day=1)
    except (ValueError, OverflowError):
        raise AuthError(422, "INVALID_MONTH") from None


@server.tool()
async def statement_request(user_id: UserId, account_id: AccountId, month: Month, ctx: Context) -> list[Transaction]:
    """Return the transactions for an owned account in the requested YYYY-MM month."""
    def read(cursor, user):
        return _read_transactions(cursor, user, account_id, period=_month_period(month))

    return await invoke(ctx, Action.STATEMENT_REQUEST, user_id, read, account_id=account_id)


def require_owned_account(
    user: AuthenticatedUser, target_user_id: str, cursor, account_id: int,
    *, action: Action = Action.TRANSACTION_DETAILS,
) -> None:
    authorize(user, target_user_id, action)
    if not owns_account(cursor, user.id, account_id):
        raise AuthError(403, "FORBIDDEN", target_id=account_id)


def transaction_details_in_chat(
    user: AuthenticatedUser, target_user_id: str, cursor, account_id: int, limit: int,
) -> list[Transaction]:
    require_owned_account(user, target_user_id, cursor, account_id)
    if not 1 <= limit <= 100:
        raise AuthError(422, "INVALID_REQUEST")
    record_access(cursor, Action.TRANSACTION_DETAILS, "ALLOWED", user.id, target_id=account_id)
    return _read_transactions(cursor, user, account_id, limit=limit)


def statement_request_in_chat(
    user: AuthenticatedUser, target_user_id: str, cursor, account_id: int, month: str,
) -> list[Transaction]:
    require_owned_account(user, target_user_id, cursor, account_id, action=Action.STATEMENT_REQUEST)
    period = _month_period(month)
    record_access(cursor, Action.STATEMENT_REQUEST, "ALLOWED", user.id, target_id=account_id)
    return _read_transactions(cursor, user, account_id, period=period)
