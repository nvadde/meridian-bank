"""Mira’s transaction and statement specialist."""

from collections.abc import Callable
import re

from ..mcp.transactions_mcp import Transaction
from ..security import Action, AuthenticatedUser, authorize
from .agent_result import AgentResult, answer, normalize_question, out_of_scope


SYSTEM_PROMPT = "You only answer transaction and statement questions. Use transaction_details and statement_request only."

TransactionDetailsTool = Callable[[int, int], list[Transaction]]
StatementRequestTool = Callable[[int, str], list[Transaction]]
RECENT = re.compile(
    r"(?:(?:please |can you )?(?:show(?: me)?|list) )?(?:my |the )?"
    r"(?:(?:last|recent) )?(?:(?P<limit>[1-9][0-9]?) )?transactions"
    r"(?: for (?:that|this) account)?(?: please)?"
)
STATEMENT = re.compile(
    r"(?:(?:please |can you )?(?:show(?: me)?|request) )?(?:my |the |a )?"
    r"statement(?: for (?:that|this) account)?(?: (?:for )?(?P<month>[0-9]{4}-(?:0[1-9]|1[0-2])))?"
    r"(?: please)?"
)


def match_question(question: str) -> tuple[Action, re.Match] | None:
    message = normalize_question(question)
    if recent := RECENT.fullmatch(message):
        return Action.TRANSACTION_DETAILS, recent
    if statement := STATEMENT.fullmatch(message):
        return Action.STATEMENT_REQUEST, statement
    return None


def respond(
    user: AuthenticatedUser,
    target_user_id: str,
    question: str,
    shared_state: dict,
    *,
    transaction_details: TransactionDetailsTool,
    statement_request: StatementRequestTool,
) -> AgentResult:
    authorize(user, target_user_id, Action.TRANSACTION_READ)
    scope = match_question(question)
    if scope is None:
        return out_of_scope()

    action, match = scope
    authorize(user, target_user_id, action)
    account_id = shared_state["current_account_id"]
    if account_id is None:
        return answer("Which account? Ask for your Checking or Savings balance first.")

    if action == Action.STATEMENT_REQUEST:
        month = match["month"]
        if month is None:
            return answer("Which statement month? Enter it as YYYY-MM.")
        rows = statement_request(account_id, month)
        tool_called = "statement_request"
        introduction = f"Here is the {month} statement for that account:"
    else:
        rows = transaction_details(account_id, int(match["limit"] or 5))
        tool_called = "transaction_details"
        introduction = "Here are the latest transactions for that account:"

    tool_result = [
        {
            "transaction_id": row.transaction_id,
            "description": row.description,
            "amount": format(row.amount, ".2f"),
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "category": row.category,
        }
        for row in rows
    ]
    if not rows:
        return answer("That account has no transactions for this request.", tool_called, tool_result)

    entries = "\n".join(
        f"- {row.description or 'Transaction'}: ${row.amount:,.2f}" for row in rows
    )
    return answer(f"{introduction}\n{entries}", tool_called, tool_result)
