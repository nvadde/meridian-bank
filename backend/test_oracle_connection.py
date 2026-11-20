"""Verify the manually created Meridian Trust Bank schema using SELECTs."""

import re

from app.database import ConnectionSetupError, get_connection


EXPECTED_COUNTS = {
    "BANK_USERS": 5,
    "BANK_ACCOUNTS": 7,
    "BANK_TRANSACTIONS": 16,
}
EXPECTED_TABLES = (*EXPECTED_COUNTS, "SESSIONS", "AUDIT_LOGS")
EXPECTED_USER_COLUMNS = (
    "ID", "NAME", "EMAIL", "PASSWORD_HASH", "SALT", "ROLE", "STATUS",
    "FAILED_ATTEMPTS", "LOCKED_UNTIL", "CREATED_AT",
)
SAMPLE_QUERIES = {
    "BANK_USERS": "SELECT id, name, email, role, status FROM bank_users ORDER BY id",
    "BANK_ACCOUNTS": (
        "SELECT id, user_id, account_type, masked_number, balance "
        "FROM bank_accounts ORDER BY id"
    ),
    "BANK_TRANSACTIONS": (
        "SELECT id, account_id, description, amount "
        "FROM bank_transactions WHERE ROWNUM <= 3"
    ),
}


def error_label(error):
    # Display only the error type and a validated Oracle code, since a driver
    # message can include details from the connection configuration.
    details = error.args[0] if error.args else None
    code = getattr(details, "full_code", "")
    if isinstance(code, str) and re.fullmatch(r"(?:ORA|DPY|DPI)-[0-9]+", code):
        return f"{type(error).__name__} ({code})"
    return type(error).__name__


def verify_schema(cursor, results):
    cursor.execute("SELECT table_name FROM user_tables ORDER BY table_name")
    table_names = [name for (name,) in cursor]
    print("Tables in current schema:", ", ".join(table_names) or "(none)")
    missing = [name for name in EXPECTED_TABLES if name not in table_names]
    results["Required tables"] = (
        "FAIL (missing " + ", ".join(missing) + ")" if missing else "PASS"
    )

    wrong_counts = []
    for table, expected in EXPECTED_COUNTS.items():
        check = f"{table} count"
        if table not in table_names:
            results[check] = "FAIL (table missing)"
        else:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                (actual,) = cursor.fetchone()
            except Exception as error:
                results[check] = f"FAIL ({error_label(error)})"
            else:
                print(f"{table} count: {actual} (expected {expected})")
                results[check] = (
                    "PASS" if actual == expected else f"FAIL (expected {expected}, got {actual})"
                )
        if results[check] != "PASS":
            wrong_counts.append(table)

    if wrong_counts:
        print("Stopping after count failures:", ", ".join(wrong_counts))
        return

    cursor.execute(
        "SELECT column_name, data_type FROM user_tab_columns "
        "WHERE table_name = 'BANK_USERS' ORDER BY column_id"
    )
    columns = dict(cursor)
    print("BANK_USERS columns:")
    for name, data_type in columns.items():
        print(f"  {name}: {data_type}")
    missing = [name for name in EXPECTED_USER_COLUMNS if name not in columns]
    results["BANK_USERS columns"] = (
        "FAIL (missing " + ", ".join(missing) + ")" if missing else "PASS"
    )

    for table, sql in SAMPLE_QUERIES.items():
        try:
            cursor.execute(sql)
            row = cursor.fetchone()
        except Exception as error:
            results[f"{table} sample"] = f"FAIL ({error_label(error)})"
            continue
        if row is None:
            results[f"{table} sample"] = "FAIL (no rows)"
        else:
            sample = {column[0].lower(): value for column, value in zip(cursor.description, row)}
            print(f"{table} sample: {sample}")
            results[f"{table} sample"] = "PASS"


def main():
    checks = [
        "Oracle connection",
        "Required tables",
        *(f"{table} count" for table in EXPECTED_COUNTS),
        "BANK_USERS columns",
        *(f"{table} sample" for table in SAMPLE_QUERIES),
    ]
    results = dict.fromkeys(checks, "FAIL (not run)")

    print("Connecting...", flush=True)
    try:
        with get_connection() as con:
            print(con.version)
            results["Oracle connection"] = "PASS"
            with con.cursor() as cursor:
                verify_schema(cursor, results)
    except ConnectionSetupError as error:
        results["Oracle connection"] = f"FAIL ({error})"
    except Exception as error:
        check = "Oracle connection" if results["Oracle connection"] != "PASS" else "Oracle verification"
        results[check] = f"FAIL ({error_label(error)})"

    print("\nVerification results")
    for check, result in results.items():
        print(f"{check}: {result}")
    return 0 if all(result == "PASS" for result in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
