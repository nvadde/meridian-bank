"""Run Mira’s routing and tool evaluation against the demo Oracle schema."""

from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from ...main import app
from ..llm import llm_client
from ..session.session_store import create_session


def main() -> int:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    cases = (
        ("balance", "What's my balance?", "Accounts Agent", ("balance_enquiry",)),
        ("checking balance", "What is my checking balance?", "Accounts Agent", ("balance_enquiry",)),
        ("savings balance", "Show my savings balance", "Accounts Agent", ("balance_enquiry",)),
        ("rewards card", "Check my rewards card balance", "Accounts Agent", ("balance_enquiry",)),
        ("transactions", "Show last 5 transactions", "Transactions Agent", ("transaction_details",)),
        ("account follow-up", "Show my last 2 transactions for that account", "Transactions Agent", ("transaction_details",)),
        ("statement", f"Show my statement for {month}", "Transactions Agent", ("statement_request",)),
        ("combined", "What's my balance and last 5 transactions?", "Accounts Agent + Transactions Agent",
         ("balance_enquiry", "transaction_details")),
        ("address clarification", "Change my address", "Service Agent", ()),
        ("transfer handoff", "Transfer $200 from Checking to Savings", "Mira", ()),
    )
    session = create_session("MT-1001")
    passed = 0
    with TestClient(app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False) as client:
        try:
            with patch.object(llm_client, "load_settings", return_value=None):
                for label, question, agent, tools in cases:
                    response = client.post("/chat", json={"session_token": session.token, "message": question})
                    output = response.json() if response.status_code == 200 else {}
                    actual_agent = output.get("agent_used", f"HTTP {response.status_code}")
                    actual_tools = tuple(output.get("tools_used", ()))
                    ok = actual_agent == agent and actual_tools == tools
                    passed += int(ok)
                    tool_label = ", ".join(actual_tools) or "no tool"
                    print(f"{label} -> {actual_agent} / {tool_label} = {'PASS' if ok else 'FAIL'}")
        finally:
            response = client.post("/logout", headers={"Authorization": "Bearer " + session.token})
            if response.status_code != 204:
                print("Evaluation logout failed.")
    print(f"{passed}/{len(cases)} PASS")
    return 0 if passed >= 9 else 1


if __name__ == "__main__":
    raise SystemExit(main())
