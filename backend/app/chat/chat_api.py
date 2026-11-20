"""Authenticate and scope a Mira request before dispatching any agent."""

from contextlib import ExitStack
import json
import re
from typing import Annotated

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr, StringConstraints, ValidationError

from ..agents import coordinator
from ..agents.service_agent import ServiceTools
from ..agents.agent_result import normalize_question
from ..authorization import USER_ID_PATTERN, authorized_context
from ..llm.llm_client import render_replies
from ..llm.pii_redaction import split_account_hint
from ..mcp import accounts_mcp, service_mcp, transactions_mcp
from ..mcp.tool_server import run_chat_read
from ..observability.logger import Trace
from ..routes.auth_routes import SessionToken, token_value
from ..security import Action, AuthError, AuthenticatedUser, authorize
from ..session.session_store import open_conversation, require_mira_session


router = APIRouter()
MAX_REQUEST_BYTES = 16_384
USER_ID_IN_MESSAGE = re.compile(r"(?<![\w-])(?:MT|STAFF)-[0-9]{1,14}(?![\w-])", re.IGNORECASE)
FOREIGN_REFERENCE = re.compile(
    r"\b(?:(?!(?:what|who|where|how|it|that)\b)[a-z][a-z-]*'s|her|his|their) "
    r"(?:[a-z-]+ )?(?:balances?|checking|savings|transactions?|statements?|address)\b"
    r"|\b(?:balances?|transactions?|statements?) (?:for|of) "
    r"(?!(?:that|this|my|the|me|a|an)\b)[a-z][a-z-]+\b"
)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_token: SecretStr | None = Field(default=None, repr=False, exclude=True)
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    target_user_id: Annotated[str, StringConstraints(pattern=USER_ID_PATTERN)] | None = Field(
        default=None, validation_alias=AliasChoices("target_user_id", "user_id"),
    )


class ChatReply(BaseModel):
    text: str
    agent_used: str
    tools_used: list[str]


class ChatSession(BaseModel):
    display_name: str


def _authorize_target(user: AuthenticatedUser, body: ChatRequest) -> str:
    target = body.target_user_id or user.id
    authorize(user, target, Action.CHAT)
    for mention in USER_ID_IN_MESSAGE.finditer(body.message):
        mentioned_id = mention.group()
        if mentioned_id.casefold() != user.id.casefold():
            authorize(user, mentioned_id.upper(), Action.CHAT)
    return target


def _parse_payload(raw: bytes | None) -> object:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None


def _process_chat(bearer_token: str | None, raw: bytes | None) -> ChatReply:
    payload = _parse_payload(raw)
    body_token = payload.get("session_token") if isinstance(payload, dict) else None
    token = bearer_token if bearer_token is not None else (body_token if isinstance(body_token, str) else None)
    with Trace() as trace, ExitStack() as stack:
        with authorized_context(token, Action.CHAT, on_authenticated=trace.bind) as (cursor, user):
            if bearer_token is not None and body_token is not None and body_token != bearer_token:
                raise AuthError(401, "INVALID_SESSION")
            if user.session is None:
                raise AuthError(401, "INVALID_SESSION")
            conversation = stack.enter_context(open_conversation(user.session))
            if raw is None:
                raise AuthError(413, "INVALID_REQUEST")
            try:
                body = ChatRequest.model_validate(payload)
            except ValidationError:
                raise AuthError(422, "INVALID_REQUEST") from None

            target = _authorize_target(user, body)
            state = conversation.get_shared_state()
            question, account_hint = split_account_hint(body.message)
            if account_hint and not question:
                question = "what is my checking balance?"
            plan = coordinator.classify(question, conversation.get_history(), state, user.id)
            if plan[0].intent == coordinator.Intent.UNKNOWN and FOREIGN_REFERENCE.search(normalize_question(body.message)):
                raise AuthError(403, "FORBIDDEN")
            log_prompt = "\n".join(
                item.question if item.intent in coordinator.READ_INTENTS else f"[{item.action.value} request]"
                for item in plan
            )
            trace.prompt(log_prompt + ("\n" + account_hint if account_hint else ""))
            parallel = len(plan) > 1

            def balance_enquiry(account_type: str | None, account_id: int | None):
                return run_chat_read(cursor, parallel, lambda worker:
                    trace.call(
                        "TOOL", "balance_enquiry", accounts_mcp.balance_enquiry_in_chat,
                        user, target, worker, account_type, account_id=account_id,
                    )
                )

            def transaction_details(account_id: int, limit: int):
                return run_chat_read(cursor, parallel, lambda worker:
                    trace.call(
                        "TOOL", "transaction_details", transactions_mcp.transaction_details_in_chat,
                        user, target, worker, account_id, limit,
                    )
                )

            def statement_request(account_id: int, month: str):
                return run_chat_read(cursor, parallel, lambda worker:
                    trace.call(
                        "TOOL", "statement_request", transactions_mcp.statement_request_in_chat,
                        user, target, worker, account_id, month,
                    )
                )

            def select_account(action: Action, account_type: str | None):
                return accounts_mcp.select_account_for_chat(user, target, cursor, action, account_type)

            def require_owned_account(action: Action, account_id: int):
                if action == Action.CHEQUE_BOOK_REQUEST:
                    service_mcp.require_owned_account(user, target, cursor, account_id)
                else:
                    transactions_mcp.require_owned_account(user, target, cursor, account_id, action=action)

            def change_of_address(address: str):
                return trace.call("TOOL", "change_of_address", service_mcp.change_of_address_in_chat,
                                  user, target, cursor, address)

            def cheque_book_request(account_id: int):
                return trace.call("TOOL", "cheque_book_request", service_mcp.cheque_book_request_in_chat,
                                  user, target, cursor, account_id)

            def kyc_update(document: str):
                return trace.call("TOOL", "kyc_update", service_mcp.kyc_update_in_chat,
                                  user, target, cursor, document)

            tools = coordinator.Tools(
                balance_enquiry, transaction_details, statement_request,
                ServiceTools(change_of_address, cheque_book_request, kyc_update),
                select_account, require_owned_account,
            )
            reply = trace.call(
                "COORDINATOR", "Mira", coordinator.reply, user, target, plan, state, tools, trace=trace,
            )

        # Tool and audit writes commit before any provider call.
        text = render_replies(reply.drafts, account_hint, trace=trace) if reply.drafts else reply.text
        trace.record("RESULT", "OK", agent=reply.agent_used, tools=list(reply.tools_used), characters=len(text))
        conversation.record_exchange(body.message, text, reply.state_updates)
    return ChatReply(text=text, agent_used=reply.agent_used, tools_used=list(reply.tools_used))


@router.get("/chat/session")
def chat_session(credentials: SessionToken) -> ChatSession:
    with authorized_context(token_value(credentials), Action.CHAT) as (_, user):
        require_mira_session(user.session)
        return ChatSession(display_name=user.display_name or user.id)


@router.post(
    "/chat",
    response_model=ChatReply,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": ChatRequest.model_json_schema()}},
        },
    },
)
async def chat(request: Request, credentials: SessionToken) -> ChatReply:
    token = token_value(credentials)

    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_REQUEST_BYTES:
            return await run_in_threadpool(_process_chat, token, None)
        raw.extend(chunk)
    return await run_in_threadpool(_process_chat, token, bytes(raw))
