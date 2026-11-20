"""Mira MCP transport, authorization, and output redaction."""

import re
from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi.concurrency import run_in_threadpool
from fastapi.security.utils import get_authorization_scheme_param
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field, ValidationError

from ..authorization import USER_ID_PATTERN, authorized_context
from ..database import get_connection
from ..observability.logger import Trace
from ..security import Action, AuthError, AuthenticatedUser
from ..session.session_store import require_mira_session


UserId = Annotated[str, Field(pattern=USER_ID_PATTERN)]
AccountId = Annotated[int, Field(strict=True, ge=1, le=10**38 - 1)]
Result = TypeVar("Result")
ACCOUNT_NUMBER = re.compile(r"[0-9](?:[ .\-\t]*[0-9]){7,}")


class ToolServer(FastMCP):
    def __init__(self, name: str):
        super().__init__(name, streamable_http_path="/", stateless_http=True, json_response=True)

    async def call_tool(self, name, arguments):
        try:
            return await super().call_tool(name, arguments)
        except ToolError as error:
            # The SDK wraps exceptions with their original messages, including input values.
            cause = error.__cause__
            if isinstance(cause, AuthError):
                raise ToolError(str(cause)) from None
            if isinstance(cause, ValidationError) or cause is None:
                raise ToolError("INVALID_TOOL_REQUEST") from None
            raise ToolError("TOOL_UNAVAILABLE") from None


def _run_tool(token, action, user_id, account_id, operation):
    with Trace(source="mcp") as trace:
        def execute():
            with authorized_context(
                token, action, user_id=user_id, account_id=account_id, on_authenticated=trace.bind,
            ) as (cursor, user):
                require_mira_session(user.session)
                return operation(cursor, user)

        return trace.call("TOOL", action.value.lower(), execute)


async def invoke(
    ctx: Context,
    action: Action,
    user_id: str,
    operation: Callable[[object, AuthenticatedUser], Result],
    *,
    account_id: int | None = None,
) -> Result:
    request = ctx.request_context.request
    header = request.headers.get("authorization") if request is not None else None
    scheme, credential = get_authorization_scheme_param(header)
    token = credential if scheme.lower() == "bearer" else None
    return await run_in_threadpool(_run_tool, token, action, user_id, account_id, operation)


def masked_number(value: str) -> str:
    match = re.search(r"[0-9]{4}$", value.rstrip())
    return "••" + match.group() if match else "••"


def redact_account_numbers(value: str | None) -> str | None:
    if value is None:
        return None
    return ACCOUNT_NUMBER.sub(lambda match: masked_number(match.group()), value)


def run_chat_read(cursor, parallel: bool, operation: Callable[[object], Result]) -> Result:
    """Run parallel read tools on separate Oracle connections while chat holds the session lock."""
    if not parallel:
        return operation(cursor)
    with get_connection() as connection, connection.cursor() as worker_cursor:
        result = operation(worker_cursor)
        connection.commit()
        return result
