"""Write each verdict back to the finance table.

The verdict table is the only thing the engine writes to Snowflake. A row summarizes a decision for finance
reporting; the full record stays in DynamoDB and S3. The write is idempotent, because a decision is written
under its own id and a repeat replaces the row.

`conn` is any DB-API connection that accepts '?' placeholders. snowflake-connector-python does when it is
configured with paramstyle 'qmark', and so does sqlite3, which the tests use. A live Snowflake account has not
been exercised: see docs/status.md.
"""

from __future__ import annotations

import os
from typing import Any

from mappings import tables

COLUMNS = tables.columns("verdict_log")


def row_for(decision: dict[str, Any]) -> dict[str, Any]:
    """The finance row for a decision record (rules.decision.DecisionRecord.to_dict())."""
    return {
        "decision_id": f"{decision['id']}-{decision['events_applied']}",
        "patent_key": decision["request"]["patent_key"],
        "verdict": decision["verdict"],
        "signature": decision["signature"],
        "decided_by": decision["user"],
        "role": decision["role"],
        "release_version": decision["release_version"],
        "combiner_policy_version": decision["combiner_policy_version"],
        "recording_cutoff": decision["recording_cutoff"].replace("T", " ").replace("Z", "").replace("+00:00", ""),
    }


def write_verdicts(conn: Any, decisions: list[dict[str, Any]]) -> int:
    """Replace or insert one row per decision, in one transaction. Returns the number of rows written."""
    rows = [row_for(d) for d in decisions]
    if not rows:
        return 0
    cur = conn.cursor()
    try:
        marks = ", ".join("?" for _ in rows)
        cur.execute(f"DELETE FROM verdict_log WHERE decision_id IN ({marks})", [r["decision_id"] for r in rows])
        cur.executemany(
            f"INSERT INTO verdict_log ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})",
            [[r[c] for c in COLUMNS] for r in rows],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return len(rows)


def connect() -> Any:
    """A Snowflake connection from the environment. The password comes from Secrets Manager in the deployment."""
    import snowflake.connector  # type: ignore[import-not-found,unused-ignore]

    snowflake.connector.paramstyle = "qmark"
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "GONOGO_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "GONOGO"),
        schema=os.environ.get("SNOWFLAKE_SCHEMA", "PUBLIC"),
    )
