"""Mira MCP tools that submit Oracle service requests for review."""

from typing import Annotated
from uuid import uuid4

from mcp.server.fastmcp import Context
from pydantic import StringConstraints, TypeAdapter, ValidationError

from ..audit import record_access
from ..authorization import owns_account
from ..security import Action, AuthError, AuthenticatedUser, authorize
from .tool_server import AccountId, ToolServer, UserId, invoke


server = ToolServer("Meridian Service")
Address = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
DocumentType = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z][A-Za-z .'-]{0,39}$"),
]


def _queue_request(cursor, action: Action, user_id: str, *, account_id=None, value=None) -> str:
    confirmation_id = uuid4().hex
    cursor.execute(
        """
        INSERT INTO bank_service_requests
            (id, user_id, account_id, request_type, request_value, status, created_at)
        VALUES
            (:confirmation_id, :user_id, :account_id, :request_type, :request_value,
             'UNDER_REVIEW', SYS_EXTRACT_UTC(SYSTIMESTAMP))
        """,
        confirmation_id=confirmation_id,
        user_id=user_id,
        account_id=account_id,
        request_type=action.value,
        request_value=value,
    )
    return confirmation_id


@server.tool()
async def change_of_address(user_id: UserId, new_address: Address, ctx: Context) -> dict[str, str]:
    """Submit an address change for the signed-in customer and return a confirmation ID."""
    def queue(cursor, user):
        confirmation = _queue_request(cursor, Action.CHANGE_OF_ADDRESS, user.id, value=new_address)
        return {"confirmation_id": confirmation}

    return await invoke(ctx, Action.CHANGE_OF_ADDRESS, user_id, queue)


@server.tool()
async def cheque_book_request(user_id: UserId, account_id: AccountId, ctx: Context) -> dict[str, str]:
    """Submit a cheque book request for an account the signed-in customer owns."""
    def queue(cursor, user):
        confirmation = _queue_request(cursor, Action.CHEQUE_BOOK_REQUEST, user.id, account_id=account_id)
        return {"confirmation_id": confirmation}

    return await invoke(ctx, Action.CHEQUE_BOOK_REQUEST, user_id, queue, account_id=account_id)


@server.tool()
async def kyc_update(user_id: UserId, document_type: DocumentType, ctx: Context) -> dict[str, str]:
    """Submit a document type for KYC review without accepting a document number."""
    def queue(cursor, user):
        _queue_request(cursor, Action.KYC_UPDATE, user.id, value=document_type)
        return {"status": "under review"}

    return await invoke(ctx, Action.KYC_UPDATE, user_id, queue)


_address_input = TypeAdapter(Address)
_document_input = TypeAdapter(DocumentType)


def _validated_text(adapter: TypeAdapter, value: str) -> str:
    try:
        return adapter.validate_python(value)
    except ValidationError:
        raise AuthError(422, "INVALID_REQUEST") from None


def change_of_address_in_chat(
    user: AuthenticatedUser, target_user_id: str, cursor, new_address: str,
) -> dict[str, str]:
    authorize(user, target_user_id, Action.CHANGE_OF_ADDRESS)
    address = _validated_text(_address_input, new_address)
    record_access(cursor, Action.CHANGE_OF_ADDRESS, "ALLOWED", user.id, target_id=target_user_id)
    return {"confirmation_id": _queue_request(cursor, Action.CHANGE_OF_ADDRESS, user.id, value=address)}


def require_owned_account(user: AuthenticatedUser, target_user_id: str, cursor, account_id: int) -> None:
    authorize(user, target_user_id, Action.CHEQUE_BOOK_REQUEST)
    if not owns_account(cursor, user.id, account_id):
        raise AuthError(403, "FORBIDDEN", target_id=account_id)


def cheque_book_request_in_chat(
    user: AuthenticatedUser, target_user_id: str, cursor, account_id: int,
) -> dict[str, str]:
    require_owned_account(user, target_user_id, cursor, account_id)
    record_access(cursor, Action.CHEQUE_BOOK_REQUEST, "ALLOWED", user.id, target_id=account_id)
    return {"confirmation_id": _queue_request(cursor, Action.CHEQUE_BOOK_REQUEST, user.id, account_id=account_id)}


def kyc_update_in_chat(user: AuthenticatedUser, target_user_id: str, cursor, document_type: str) -> dict[str, str]:
    authorize(user, target_user_id, Action.KYC_UPDATE)
    document = _validated_text(_document_input, document_type)
    record_access(cursor, Action.KYC_UPDATE, "ALLOWED", user.id, target_id=target_user_id)
    _queue_request(cursor, Action.KYC_UPDATE, user.id, value=document)
    return {"status": "under review"}
