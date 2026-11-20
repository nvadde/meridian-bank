"""Common result contract for Mira’s specialist agents."""

from typing import TypedDict


class AgentResult(TypedDict):
    answer_text: str
    tool_called: str | None
    tool_result: object
    confidence: float


def answer(text: str, tool_called: str | None = None, tool_result: object = None) -> AgentResult:
    return {"answer_text": text, "tool_called": tool_called, "tool_result": tool_result, "confidence": 1.0}


def out_of_scope() -> AgentResult:
    return {"answer_text": "OUT_OF_SCOPE", "tool_called": None, "tool_result": None, "confidence": 0.0}


def normalize_question(question: str) -> str:
    return " ".join(question.casefold().replace("’", "'").split()).rstrip(" .?!")
