"""Redact sensitive text before it crosses the language-model boundary."""

import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation


EMAIL = re.compile(r"([\w.!#$%&'*+/=?^`{|}~-]+)@([\w.-]+\.[a-z]{2,})", re.IGNORECASE)
CREDENTIAL = re.compile(
    r"\b(?:passwords?|passphrases?|passcodes?|pin|otps?|"
    r"(?:one[ -]time|verification|security|authentication)[ -](?:password|code|pin)|"
    r"(?:api|access)[ -]key|(?:session|access|refresh)[ -]token|authorization\s*:\s*bearer|bearer)"
    r"\b(?:[ \t]*(?:=|:|\bis\b)[ \t]*|[ \t]+)[^\r\n]+",
    re.IGNORECASE,
)
NUMBER = re.compile(r"(?<![0-9])[0-9](?:[ \t()./\-]*[0-9]){7,}(?![0-9])")
ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
LABELED_NUMBER = re.compile(
    r"\b(?P<label>(?:account|card)(?: number)?\s*(?:(?:is\b|:|#|=)\s*)?)"
    r"(?P<number>[0-9](?:[ \t()./\-]*[0-9]){7,})",
    re.IGNORECASE,
)
PAYMENT_SECRET = re.compile(
    r"\b(?:cvv|cvc|cvv2|cvc2|card[ -]security[ -]code)\b[^\r\n]+", re.IGNORECASE,
)
ACCOUNT_HINT = re.compile(
    r"(?<!\w)my (?:bank )?account(?: number)?\s*(?:is\b|:|#)\s*"
    r"(?P<number>[0-9](?:[ \t()./\-]*[0-9]){7,})[ \t]*[.!?]?$",
    re.IGNORECASE,
)
STANDALONE_OTP = re.compile(r"^\s*[0-9](?:[ -]*[0-9]){3,7}\s*$")
UNLABELLED_CODE = re.compile(r"(?<![•*$0-9])\b[0-9]{4,7}\b(?![-./][0-9])")


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return "".join(
        str(unicodedata.decimal(char)) if char.isdecimal()
        else "-" if unicodedata.category(char) == "Pd"
        else char
        for char in normalized
        if unicodedata.category(char) != "Cf"
    )


def mask_number(text: str) -> str:
    digits = re.sub(r"[^0-9]", "", _normalize(text))
    return "••" + digits[-4:] if len(digits) >= 4 else "••"


def _mask_unless_date(match: re.Match) -> str:
    value = match[0]
    if ISO_DATE.fullmatch(value):
        try:
            datetime.fromisoformat(value)
            return value
        except ValueError:
            pass
    return mask_number(value)


def redact_text(text: str) -> str:
    text = _normalize(text)
    text = CREDENTIAL.sub("[REDACTED_CREDENTIAL]", text)
    text = PAYMENT_SECRET.sub("[REDACTED_CREDENTIAL]", text)
    text = EMAIL.sub(lambda match: match[1][0] + "***@" + match[2], text)
    text = LABELED_NUMBER.sub(lambda match: match["label"] + mask_number(match["number"]), text)
    if STANDALONE_OTP.fullmatch(text) and len(re.sub(r"[^0-9]", "", text)) < 8:
        return "[REDACTED_CODE]"
    return NUMBER.sub(_mask_unless_date, text)


def split_account_hint(message: str) -> tuple[str, str | None]:
    """Extract a redacted hint for drafting. The hint never selects an account."""
    normalized = _normalize(message)
    match = ACCOUNT_HINT.search(normalized)
    if match is None:
        return message, None
    question = normalized[:match.start()].rstrip(" ,;:-")
    return question, "my account is " + mask_number(match["number"])


def tool_facts(tool: str, result: object) -> object:
    """Project tool outputs into the small set of fields needed to draft a reply."""
    fields = {
        "balance_enquiry": ("name", "account_type", "masked_number", "balance"),
        "transaction_details": ("name", "description", "amount", "timestamp", "category"),
        "statement_request": ("name", "description", "amount", "timestamp", "category"),
    }.get(tool)
    if fields is None:
        # Service input and confirmation IDs stay local. A tool call exists only after submission.
        return {"status": "under review" if tool in ("change_of_address", "kyc_update") else "submitted"}
    if not isinstance(result, list):
        return []

    safe_rows = []
    for row in result:
        if not isinstance(row, dict):
            continue
        safe_row = {}
        for field in fields:
            value = row.get(field)
            if not isinstance(value, str):
                continue
            if field == "masked_number":
                safe_row[field] = mask_number(value)
            elif field in ("balance", "amount"):
                try:
                    number = Decimal(value)
                    if number.is_finite() and max(number.adjusted(), 0) <= 12:
                        safe_row[field] = f"{number:.2f}"
                except InvalidOperation:
                    continue
            elif field == "timestamp":
                try:
                    safe_row[field] = datetime.fromisoformat(value).isoformat()
                except ValueError:
                    continue
            else:
                safe_row[field] = UNLABELLED_CODE.sub("[REDACTED_CODE]", redact_text(value))[:500]
        safe_rows.append(safe_row)
    return safe_rows
