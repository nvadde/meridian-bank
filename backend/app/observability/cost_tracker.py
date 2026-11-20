"""Calculate provider usage and aggregate it by user and UTC day."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal


def _tokens(usage: dict, name: str) -> int | None:
    value = usage.get(name)
    return value if type(value) is int and value >= 0 else None


def call_metrics(provider: str, status: str, usage: dict, input_rate: Decimal, output_rate: Decimal) -> dict:
    input_tokens = _tokens(usage, "prompt_tokens")
    output_tokens = _tokens(usage, "completion_tokens")
    total = _tokens(usage, "total_tokens")
    cost = None
    if input_tokens is not None and output_tokens is not None:
        if total is None:
            total = input_tokens + output_tokens
        cost = format((input_tokens * input_rate + output_tokens * output_rate) / 1_000_000, "f")
    return {
        "provider": provider,
        "status": status,
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": total,
        "estimated_cost_usd": cost,
    }


def daily_usage(cursor, day: date) -> dict:
    start = datetime.combine(day, time.min)
    cursor.execute(
        """
        SELECT user_id, COUNT(*),
               SUM(JSON_VALUE(details, '$.prompt_tokens' RETURNING NUMBER)),
               SUM(JSON_VALUE(details, '$.completion_tokens' RETURNING NUMBER)),
               SUM(JSON_VALUE(details, '$.total_tokens' RETURNING NUMBER)),
               SUM(JSON_VALUE(details, '$.estimated_cost_usd' RETURNING NUMBER)),
               COUNT(*) - COUNT(JSON_VALUE(details, '$.estimated_cost_usd' RETURNING NUMBER))
        FROM bank_audit_logs
        WHERE action = 'MIRA_LLM_USAGE' AND created_at >= :day_start AND created_at < :day_end
        GROUP BY user_id
        ORDER BY user_id
        """,
        day_start=start,
        day_end=start + timedelta(days=1),
        fetch_decimals=True,
    )

    rows = []
    total_cost = Decimal(0)
    for user, calls, prompt, completion, tokens, cost, unmetered in cursor:
        total_cost += cost or Decimal(0)
        rows.append({
            "user_id": user,
            "calls": int(calls),
            "prompt_tokens": int(prompt or 0),
            "completion_tokens": int(completion or 0),
            "total_tokens": int(tokens or 0),
            "estimated_cost_usd": format(cost or Decimal(0), "f"),
            "unmetered_calls": int(unmetered),
        })
    return {
        "date": day.isoformat(),
        "users": rows,
        "calls": sum(row["calls"] for row in rows),
        "total_tokens": sum(row["total_tokens"] for row in rows),
        "estimated_cost_usd": format(total_cost, "f"),
        "unmetered_calls": sum(row["unmetered_calls"] for row in rows),
    }
