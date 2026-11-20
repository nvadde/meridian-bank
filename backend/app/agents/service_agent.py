"""Mira’s address, cheque book, and KYC specialist."""

from collections.abc import Callable
from dataclasses import dataclass
import re

from ..security import Action, AuthenticatedUser, authorize
from .agent_result import AgentResult, answer, out_of_scope


SYSTEM_PROMPT = "You only handle service requests: address, cheque book, KYC. Use service MCP tools only. Never give balances."

ADDRESS_REQUEST = re.compile(
    r"(?:please )?(?:change|update) my (?:mailing )?address(?: to (?P<address>.+))?",
    re.IGNORECASE,
)
CHEQUE_REQUEST = re.compile(
    r"(?:please )?(?:request|order) (?:a )?(?:cheque|check) ?book(?: for (?:that|this) account)?",
    re.IGNORECASE,
)
KYC_REQUEST = re.compile(
    r"(?:please )?(?:submit|update) (?:my )?kyc(?: (?:with|using) (?P<document>.+))?",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ServiceTools:
    change_of_address: Callable[[str], dict[str, str]]
    cheque_book_request: Callable[[int], dict[str, str]]
    kyc_update: Callable[[str], dict[str, str]]


def match_question(question: str) -> tuple[Action, re.Match] | None:
    message = question.strip().rstrip(".?!")
    if address := ADDRESS_REQUEST.fullmatch(message):
        return Action.CHANGE_OF_ADDRESS, address
    if cheque := CHEQUE_REQUEST.fullmatch(message):
        return Action.CHEQUE_BOOK_REQUEST, cheque
    if kyc := KYC_REQUEST.fullmatch(message):
        return Action.KYC_UPDATE, kyc
    return None


def respond(
    user: AuthenticatedUser,
    target_user_id: str,
    question: str,
    shared_state: dict,
    *,
    tools: ServiceTools,
) -> AgentResult:
    authorize(user, target_user_id, Action.CHAT)
    scope = match_question(question)
    if scope is None:
        return out_of_scope()

    action, match = scope
    authorize(user, target_user_id, action)
    if action == Action.CHANGE_OF_ADDRESS:
        value = match["address"]
        if value is None:
            return answer("What is the new address? Say ‘change my address to’ followed by the address.")
        data = tools.change_of_address(value)
        return answer(f"Address change submitted for review. Confirmation ID: {data['confirmation_id']}.",
                      "change_of_address", data)

    if action == Action.CHEQUE_BOOK_REQUEST:
        account_id = shared_state["current_account_id"]
        if account_id is None:
            return answer("Which account? Ask for your Checking or Savings balance first.")
        data = tools.cheque_book_request(account_id)
        return answer(f"Cheque book request submitted. Confirmation ID: {data['confirmation_id']}.",
                      "cheque_book_request", data)

    document_type = match["document"]
    if document_type is None:
        return answer("Which document type? Say ‘update my KYC with’ followed by the document type.")
    data = tools.kyc_update(document_type)
    return answer("Your KYC update is under review.", "kyc_update", data)
