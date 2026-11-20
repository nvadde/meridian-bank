"""Classify Mira turns, dispatch specialists, and update conversation context."""

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
import re

from ..llm.llm_client import Draft
from ..mcp.accounts_mcp import Balance
from ..observability.logger import Trace
from ..security import Action, AuthenticatedUser, authorize
from ..session.session_store import Message
from . import accounts_agent, service_agent, transactions_agent
from .agent_result import AgentResult, answer, normalize_question


class Intent(StrEnum):
    BALANCE = "BALANCE"
    TRANSACTIONS = "TRANSACTIONS"
    STATEMENT = "STATEMENT"
    SERVICE = "SERVICE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class Request:
    intent: Intent
    action: Action
    question: str


@dataclass(frozen=True, slots=True)
class Tools:
    balance_enquiry: Callable[[str | None, int | None], list[Balance]]
    transaction_details: transactions_agent.TransactionDetailsTool
    statement_request: transactions_agent.StatementRequestTool
    service: service_agent.ServiceTools
    select_account: Callable[[Action, str | None], int | None]
    require_owned_account: Callable[[Action, int], None]


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    state_updates: dict
    drafts: tuple[Draft, ...] = ()
    agent_used: str = "Mira"
    tools_used: tuple[str, ...] = ()


MONEY_MOVEMENT = re.compile(
    r"\b(?:transfers?|transferring|wire|pay|withdraw|deposit|(?:move|send)\s+(?:money|funds|\$|[0-9]))",
    re.IGNORECASE,
)
JOIN = re.compile(r"\s*(?:[;,]|\b(?:and then|and|also)\b)\s*", re.IGNORECASE)
ACCOUNT_REFERENCE = re.compile(r"\b(?:that|this) account\b")
REPEAT = re.compile(r"(?:show(?: me)?|tell me) (?:it|that|them) again")
READ_INTENTS = {Intent.BALANCE, Intent.TRANSACTIONS, Intent.STATEMENT}
FALLBACK = (
    "I can help with balances, transactions, statements, and service requests. "
    "Would you like help reaching a human banker?"
)


_AGENT_NAMES = {
    Intent.BALANCE: "Accounts Agent",
    Intent.TRANSACTIONS: "Transactions Agent",
    Intent.STATEMENT: "Transactions Agent",
    Intent.SERVICE: "Service Agent",
}


_SYSTEM_PROMPTS = {
    Intent.BALANCE: accounts_agent.SYSTEM_PROMPT,
    Intent.TRANSACTIONS: transactions_agent.SYSTEM_PROMPT,
    Intent.STATEMENT: transactions_agent.SYSTEM_PROMPT,
    Intent.SERVICE: service_agent.SYSTEM_PROMPT,
}
_SERVICE_QUESTIONS = {
    Action.CHANGE_OF_ADDRESS: "The customer requested a mailing address change.",
    Action.CHEQUE_BOOK_REQUEST: "The customer requested a cheque book.",
    Action.KYC_UPDATE: "The customer requested a KYC update.",
}


def _make_draft(request: Request, result: AgentResult) -> Draft:
    return Draft(
        system_prompt=_SYSTEM_PROMPTS[request.intent],
        prompt=_SERVICE_QUESTIONS.get(request.action, request.question),
        tool_called=result["tool_called"],
        result=result["tool_result"],
        fallback=result["answer_text"],
    )


def _classify_one(text: str, user_id: str) -> Request | None:
    question = normalize_question(text)
    question = re.sub(r" (?:for|of) " + re.escape(user_id.casefold()) + r"$", "", question)
    if accounts_agent.match_question(question):
        return Request(Intent.BALANCE, Action.BALANCE_ENQUIRY, question)
    if transaction := transactions_agent.match_question(question):
        action = transaction[0]
        intent = Intent.STATEMENT if action == Action.STATEMENT_REQUEST else Intent.TRANSACTIONS
        return Request(intent, action, question)
    if service := service_agent.match_question(text):
        return Request(Intent.SERVICE, service[0], text)
    return None


def _classify_message(text: str, user_id: str) -> tuple[Request, ...]:
    if not MONEY_MOVEMENT.search(text):
        for separator in JOIN.finditer(text):
            before = _classify_one(text[:separator.start()].strip(), user_id)
            after = _classify_one(text[separator.end():].strip(), user_id)
            if before is not None and after is not None and before.intent != after.intent:
                return before, after
        if request := _classify_one(text, user_id):
            return (request,)
    return (Request(Intent.UNKNOWN, Action.CHAT, text),)


def classify(
    message: str, history: Sequence[Message], shared_state: dict, user_id: str,
) -> tuple[Request, ...]:
    if REPEAT.fullmatch(normalize_question(message)) and shared_state.get("last_intent") in READ_INTENTS:
        previous = next((entry["text"] for entry in reversed(history) if entry["role"] == "user"), None)
        if previous:
            plan = _classify_message(previous, user_id)
            if all(request.intent in READ_INTENTS for request in plan):
                return plan
    return _classify_message(message, user_id)


def _select_account(plan: Sequence[Request], shared_state: dict, tools: Tools) -> int | None:
    account_id = shared_state.get("current_account_id")
    account_reads = [item for item in plan if item.intent in (Intent.TRANSACTIONS, Intent.STATEMENT)]
    if not account_reads:
        return account_id

    balance_request = next((item for item in plan if item.intent == Intent.BALANCE), None)
    explicit_type = None
    if balance_request and (match := accounts_agent.match_question(balance_request.question)):
        explicit_type = accounts_agent.ACCOUNT_TYPES.get(match["kind"])

    if explicit_type is not None:
        return tools.select_account(account_reads[0].action, explicit_type)
    if account_id is not None:
        return account_id
    if balance_request or any(not ACCOUNT_REFERENCE.search(item.question) for item in account_reads):
        return tools.select_account(account_reads[0].action, None)
    return None


def _dispatch(
    user: AuthenticatedUser,
    target_user_id: str,
    request: Request,
    state: dict,
    tools: Tools,
    *,
    shared_balance_account: int | None,
) -> AgentResult:
    if request.intent == Intent.BALANCE:
        def balance_enquiry(account_type):
            return tools.balance_enquiry(account_type, shared_balance_account)

        return accounts_agent.respond(user, target_user_id, request.question, balance_enquiry=balance_enquiry)
    if request.intent == Intent.SERVICE:
        return service_agent.respond(user, target_user_id, request.question, state, tools=tools.service)
    return transactions_agent.respond(
        user, target_user_id, request.question, state,
        transaction_details=tools.transaction_details, statement_request=tools.statement_request,
    )


def reply(
    user: AuthenticatedUser,
    target_user_id: str,
    plan: Sequence[Request],
    shared_state: dict,
    tools: Tools,
    *,
    trace: Trace | None = None,
) -> Reply:
    authorize(user, target_user_id, Action.CHAT)
    if plan[0].intent == Intent.UNKNOWN:
        return Reply(FALLBACK, {"last_intent": Intent.UNKNOWN.value})

    for request in plan:
        authorize(user, target_user_id, request.action)
    account_id = _select_account(plan, shared_state, tools)
    if account_id is not None:
        for request in plan:
            if request.intent in (Intent.TRANSACTIONS, Intent.STATEMENT) or request.action == Action.CHEQUE_BOOK_REQUEST:
                tools.require_owned_account(request.action, account_id)

    shares_account = any(item.intent == Intent.BALANCE for item in plan) and any(
        item.intent in (Intent.TRANSACTIONS, Intent.STATEMENT) for item in plan
    )
    state = {**shared_state, "current_account_id": account_id}

    def run(item: Request) -> AgentResult:
        args = (user, target_user_id, item, state, tools)
        kwargs = {'shared_balance_account': account_id if shares_account else None}
        if trace is not None:
            return trace.call('AGENT', _AGENT_NAMES[item.intent], _dispatch, *args, **kwargs)
        return _dispatch(*args, **kwargs)

    if len(plan) == 1:
        results = [run(plan[0])]
    else:
        with ThreadPoolExecutor(max_workers=2) as workers:
            # Service writes stay in the chat transaction. Read specialists use separate cursors.
            service = next((item for item in plan if item.intent == Intent.SERVICE), None)
            pending = {item: workers.submit(run, item) for item in plan if item != service}
            service_result = run(service) if service else None
            results = [service_result if item == service else pending[item].result() for item in plan]

    for request, result in zip(plan, results):
        if request.intent == Intent.BALANCE and result["tool_called"] == "balance_enquiry":
            balances = result["tool_result"]
            if isinstance(balances, list) and len(balances) == 1:
                account_id = balances[0]["account_id"]
            elif not shares_account:
                account_id = None

    return Reply("\n\n".join(result["answer_text"] for result in results), {
        "current_account_id": account_id,
        "last_intent": plan[-1].intent.value,
        "last_tool_result": results[0]["tool_result"] if len(results) == 1 else {
            item.intent.value: result["tool_result"] for item, result in zip(plan, results)
        },
    },
        drafts=tuple(_make_draft(item, result) for item, result in zip(plan, results)),
        agent_used=" + ".join(dict.fromkeys(_AGENT_NAMES[item.intent] for item in plan)),
        tools_used=tuple(dict.fromkeys(
            result["tool_called"] for result in results if result["tool_called"] is not None
        )),
    )
