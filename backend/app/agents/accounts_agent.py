"""Mira’s account and balance specialist."""

from collections.abc import Callable
import re

from ..mcp.accounts_mcp import Balance
from ..security import Action, AuthenticatedUser, authorize
from .agent_result import AgentResult, answer, normalize_question, out_of_scope


SYSTEM_PROMPT = "You only answer balance and account questions. Use balance_enquiry only."

BalanceEnquiryTool = Callable[[str | None], list[Balance]]
ACCOUNT_NAMES = {"CHECKING": "Checking", "SAVINGS": "Savings", "CREDIT_CARD": "Rewards Card"}
ACCOUNT_TYPES = {"checking": "CHECKING", "savings": "SAVINGS", "rewards card": "CREDIT_CARD"}
ACCOUNT_QUESTION = re.compile(
    r"(?:(?:(?:please |can you )?(?:show(?: me)?|check|tell me|list)|what is|what's|what are) )?"
    r"(?:my )?(?:(?P<kind>checking|savings|rewards card)(?: account)?(?: balances?)?"
    r"|(?:account )?balances?|accounts?)(?: please)?"
)


def match_question(question: str) -> re.Match | None:
    return ACCOUNT_QUESTION.fullmatch(normalize_question(question))


def respond(
    user: AuthenticatedUser,
    target_user_id: str,
    question: str,
    *,
    balance_enquiry: BalanceEnquiryTool,
) -> AgentResult:
    authorize(user, target_user_id, Action.BALANCE_ENQUIRY)
    scope = match_question(question)
    if scope is None:
        return out_of_scope()

    balances = balance_enquiry(ACCOUNT_TYPES.get(scope["kind"]))
    tool_result = [
        {
            "account_id": row.account_id,
            "account_type": row.enquiry.type,
            "balance": format(row.enquiry.balance, ".2f"),
            "masked_number": row.enquiry.masked_number,
        }
        for row in balances
    ]
    if not balances:
        return answer("I couldn’t find an account matching that request.", "balance_enquiry", tool_result)
    summary = ", ".join(
        f"{ACCOUNT_NAMES.get(row.enquiry.type, row.enquiry.type)} "
        f"${row.enquiry.balance:,.2f} ({row.enquiry.masked_number})"
        for row in balances
    )
    return answer(f"Your balances: {summary}.", "balance_enquiry", tool_result)
