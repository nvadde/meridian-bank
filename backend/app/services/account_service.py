"""Account transfers and card controls for the authenticated customer."""

from decimal import Decimal
import secrets
from uuid import UUID

from ..authorization import Action, AuthError, authorized_access


DEPOSIT_ACCOUNTS = {"CHECKING", "SAVINGS"}
MAX_BALANCE = Decimal("9999999999.99")


def transfer(
    token: str | None, source_id: int, destination_id: int, amount: Decimal, request_id: UUID,
) -> dict:
    with authorized_access(
        token, Action.TRANSFER, account_id=source_id, destination_id=destination_id,
    ) as (cursor, actor_id):
        if source_id == destination_id:
            raise AuthError(422, "SAME_ACCOUNT")

        # Serialize each customer's requests, including retries from another session.
        cursor.execute("SELECT 1 FROM bank_users WHERE id = :actor_id FOR UPDATE", actor_id=actor_id)
        cursor.fetchone()
        balances = {}
        for account_id in sorted((source_id, destination_id)):
            cursor.execute(
                """
                SELECT account_type, balance FROM bank_accounts
                WHERE id = :account_id AND user_id = :actor_id FOR UPDATE
                """,
                account_id=account_id,
                actor_id=actor_id,
                fetch_decimals=True,
            )
            row = cursor.fetchone()
            if row is None:
                raise AuthError(403, "FORBIDDEN")
            kind, balance = row
            if kind not in DEPOSIT_ACCOUNTS:
                raise AuthError(422, "INVALID_TRANSFER_ACCOUNT")
            balances[account_id] = balance

        transfer_key = f"{actor_id}:{request_id}"
        cursor.execute(
            "SELECT account_id, amount FROM bank_transactions WHERE transfer_key = :transfer_key",
            transfer_key=transfer_key,
            fetch_decimals=True,
        )
        previous = dict(cursor)
        legs = {source_id: -amount, destination_id: amount}
        receipt = {"request_id": str(request_id), "amount": format(amount, ".2f")}
        if previous:
            if previous != legs:
                raise AuthError(409, "TRANSFER_REQUEST_CONFLICT")
            return receipt

        if amount > balances[source_id]:
            raise AuthError(409, "INSUFFICIENT_FUNDS")
        if balances[destination_id] + amount > MAX_BALANCE:
            raise AuthError(409, "BALANCE_LIMIT")

        cursor.executemany(
            """
            UPDATE bank_accounts SET balance = balance + :delta
            WHERE id = :account_id AND user_id = :actor_id
            """,
            [
                {"delta": delta, "account_id": account_id, "actor_id": actor_id}
                for account_id, delta in legs.items()
            ],
        )
        cursor.executemany(
            """
            INSERT INTO bank_transactions
                (id, account_id, txn_date, description, amount, category, transfer_key)
            VALUES
                (:id, :account_id, SYS_EXTRACT_UTC(SYSTIMESTAMP), :description, :delta, 'Transfer', :transfer_key)
            """,
            [
                {
                    "id": secrets.randbelow(2**53 - 1) + 1,
                    "account_id": account_id,
                    "description": "Transfer out" if delta < 0 else "Transfer in",
                    "delta": delta,
                    "transfer_key": transfer_key,
                }
                for account_id, delta in legs.items()
            ],
        )
        return receipt


def set_card_status(token: str | None, account_id: int, frozen: bool) -> dict:
    status = "FROZEN" if frozen else "ACTIVE"
    action = Action.CARD_FREEZE if frozen else Action.CARD_UNFREEZE
    with authorized_access(token, action, account_id=account_id) as (cursor, actor_id):
        cursor.execute(
            """
            UPDATE bank_accounts SET card_status = :card_status
            WHERE id = :account_id AND user_id = :actor_id AND account_type = 'CREDIT_CARD'
            """,
            card_status=status,
            account_id=account_id,
            actor_id=actor_id,
        )
        if cursor.rowcount == 0:
            raise AuthError(422, "INVALID_CARD")
        return {"account_id": account_id, "card_status": status}
