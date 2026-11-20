"""Customer account and transaction endpoints."""

from datetime import timezone
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Path, Query
from pydantic import AliasChoices, BaseModel, Field, StrictBool

from ..authorization import Action, USER_ID_PATTERN, authorized_access
from ..services.account_service import set_card_status, transfer
from .auth_routes import SessionToken, token_value


router = APIRouter()
OwnerId = Annotated[str | None, Query(pattern=USER_ID_PATTERN)]
AccountId = Annotated[int, Path(gt=0, le=10**38 - 1)]
AccountField = Annotated[int, Field(gt=0, le=10**38 - 1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


class TransferRequest(BaseModel):
    from_account: AccountField = Field(validation_alias=AliasChoices("from_account", "from_account_id"))
    to_account: AccountField = Field(validation_alias=AliasChoices("to_account", "to_account_id"))
    amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
    request_id: UUID = Field(default_factory=uuid4)


class CardRequest(BaseModel):
    account_id: AccountField
    frozen: StrictBool = True


@router.get("/accounts")
def list_accounts(credentials: SessionToken, user_id: OwnerId = None):
    with authorized_access(token_value(credentials), Action.ACCOUNT_READ, user_id=user_id) as (cursor, actor_id):
        cursor.execute(
            """
            SELECT id, user_id, account_type, masked_number, balance,
                   CASE WHEN account_type = 'CREDIT_CARD' THEN card_status END
            FROM bank_accounts WHERE user_id = :actor_id ORDER BY id
            """,
            actor_id=actor_id,
        )
        return [
            dict(id=id, user_id=owner, account_type=kind, masked_number=masked, balance=balance, card_status=status)
            for id, owner, kind, masked, balance, status in cursor
        ]


@router.get("/transactions")
def list_transactions(credentials: SessionToken, user_id: OwnerId = None, limit: PageSize = 20):
    return _transactions(token_value(credentials), limit=limit, user_id=user_id)


@router.get("/accounts/{account_id}/transactions")
def list_account_transactions(account_id: AccountId, credentials: SessionToken, limit: PageSize = 20):
    return _transactions(token_value(credentials), limit=limit, account_id=account_id)


def _transactions(
    token: str | None, *, limit: int, user_id: str | None = None, account_id: int | None = None,
):
    with authorized_access(
        token, Action.TRANSACTION_READ, user_id=user_id, account_id=account_id,
    ) as (cursor, actor_id):
        cursor.execute(
            """
            SELECT t.id, t.account_id, t.description, t.amount, t.txn_date
            FROM bank_transactions t JOIN bank_accounts a ON a.id = t.account_id
            WHERE a.user_id = :actor_id
              AND (:account_id IS NULL OR a.id = :account_id)
            ORDER BY t.txn_date DESC NULLS LAST, t.id DESC
            FETCH FIRST :limit_rows ROWS ONLY
            """,
            actor_id=actor_id,
            account_id=account_id,
            limit_rows=limit,
        )
        return [
            dict(
                id=id, account_id=account, description=description, amount=amount,
                txn_date=date.replace(tzinfo=timezone.utc) if date else None,
            )
            for id, account, description, amount, date in cursor
        ]


@router.post("/transfer")
def transfer_accounts(body: TransferRequest, credentials: SessionToken):
    return transfer(
        token_value(credentials), body.from_account, body.to_account, body.amount, body.request_id,
    )


@router.post("/freeze-card")
def freeze_card(body: CardRequest, credentials: SessionToken):
    return set_card_status(token_value(credentials), body.account_id, body.frozen)
