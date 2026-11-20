"""Mira account balance MCP server."""

from dataclasses import dataclass
from decimal import Decimal

from mcp.server.fastmcp import Context
from pydantic import BaseModel

from ..audit import record_access
from ..authorization import owns_account
from ..security import Action, AuthError, AuthenticatedUser, authorize
from .tool_server import AccountId, ToolServer, UserId, invoke, masked_number


server = ToolServer("Meridian Accounts")


class BalanceEnquiry(BaseModel):
    balance: Decimal
    type: str
    masked_number: str


@dataclass(frozen=True, slots=True)
class Balance:
    account_id: int
    enquiry: BalanceEnquiry


def _enquire(cursor, user: AuthenticatedUser, *, account_id=None, account_type=None) -> list[Balance]:
    cursor.execute(
        """
        SELECT id, balance, account_type, masked_number
        FROM bank_accounts
        WHERE user_id = :owner_id
          AND (:account_id IS NULL OR id = :account_id)
          AND (:account_type IS NULL OR account_type = :account_type)
        ORDER BY id
        """,
        owner_id=user.id,
        account_id=account_id,
        account_type=account_type,
        fetch_decimals=True,
    )
    return [
        Balance(int(row_id), BalanceEnquiry(balance=balance, type=kind, masked_number=masked_number(number)))
        for row_id, balance, kind, number in cursor
    ]


@server.tool()
async def balance_enquiry(user_id: UserId, account_id: AccountId, ctx: Context) -> BalanceEnquiry:
    """Return the signed-in customer's balance, account type, and masked account number."""
    def read(cursor, user):
        balances = _enquire(cursor, user, account_id=account_id)
        if not balances:
            raise AuthError(403, "FORBIDDEN")
        return balances[0].enquiry

    return await invoke(ctx, Action.BALANCE_ENQUIRY, user_id, read, account_id=account_id)


def balance_enquiry_in_chat(
    user: AuthenticatedUser,
    target_user_id: str,
    cursor,
    account_type: str | None,
    *,
    account_id: int | None = None,
) -> list[Balance]:
    """Use the balance enquiry implementation within Mira's authenticated turn."""
    authorize(user, target_user_id, Action.BALANCE_ENQUIRY)
    if account_id is not None and not owns_account(cursor, user.id, account_id):
        raise AuthError(403, "FORBIDDEN", target_id=account_id)
    audit_target = account_id if account_id is not None else target_user_id
    record_access(cursor, Action.BALANCE_ENQUIRY, "ALLOWED", user.id, target_id=audit_target)
    return _enquire(cursor, user, account_id=account_id, account_type=account_type)


def select_account_for_chat(
    user: AuthenticatedUser, target_user_id: str, cursor, action: Action, account_type: str | None,
) -> int | None:
    """Resolve only owned account IDs, without retrieving a balance."""
    authorize(user, target_user_id, action)
    cursor.execute(
        """
        SELECT id FROM bank_accounts
        WHERE user_id = :owner_id AND (:account_type IS NULL OR account_type = :account_type)
        ORDER BY CASE account_type WHEN 'CHECKING' THEN 0 WHEN 'SAVINGS' THEN 1 ELSE 2 END, id
        FETCH FIRST 1 ROW ONLY
        """,
        owner_id=user.id,
        account_type=account_type,
    )
    row = cursor.fetchone()
    return int(row[0]) if row is not None else None
