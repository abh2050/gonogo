"""The verdict writeback: idempotent, atomic, and the same on every database that takes '?' placeholders.

A live Snowflake account is not exercised here. These tests use SQLite for the connection, which accepts the same
placeholders, and they check the Snowflake DDL as text. What a real account would add is covered in docs/status.md.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from kg.store import Store
from mappings import tables
from rules.book import load_book, to_request
from rules.engine import evaluate
from service import snowflake


@pytest.fixture(scope="module")
def decisions(store: Store) -> list[dict[str, Any]]:
    return [
        evaluate(
            store,
            to_request(r),
            cutoff="2026-11-01T00:00:00Z",
            as_of="2026-11-01",
            user="pat",
            role="licensing_manager",
        ).to_dict()
        for r in load_book()
    ]


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    for statement in tables.ddl("sqlite"):
        c.execute(statement)
    return c


def count(c: sqlite3.Connection) -> int:
    return int(c.execute("SELECT COUNT(*) FROM verdict_log").fetchone()[0])


def test_every_decision_in_the_book_lands_as_one_row(conn: sqlite3.Connection, decisions: list[dict[str, Any]]) -> None:
    assert snowflake.write_verdicts(conn, decisions) == len(decisions) == 43
    assert count(conn) == 43
    row = conn.execute(
        "SELECT * FROM verdict_log WHERE decision_id = ?", [snowflake.row_for(decisions[0])["decision_id"]]
    ).fetchone()
    assert dict(zip(tables.columns("verdict_log"), row, strict=True)) == snowflake.row_for(decisions[0])


def test_writing_twice_leaves_one_row_each(conn: sqlite3.Connection, decisions: list[dict[str, Any]]) -> None:
    snowflake.write_verdicts(conn, decisions)
    snowflake.write_verdicts(conn, decisions)
    assert count(conn) == 43


def test_a_changed_decision_replaces_its_row(conn: sqlite3.Connection, decisions: list[dict[str, Any]]) -> None:
    snowflake.write_verdicts(conn, decisions[:1])
    changed = {**decisions[0], "verdict": "NO GO", "signature": "f" * 64}
    snowflake.write_verdicts(conn, [changed])
    assert conn.execute("SELECT verdict, signature FROM verdict_log").fetchall() == [("NO GO", "f" * 64)]


def test_a_failure_part_way_writes_nothing(conn: sqlite3.Connection, decisions: list[dict[str, Any]]) -> None:
    snowflake.write_verdicts(conn, decisions[:2])
    broken = {**decisions[5], "signature": None}  # the column is NOT NULL
    with pytest.raises(sqlite3.IntegrityError):
        snowflake.write_verdicts(conn, [decisions[3], decisions[4], broken])
    assert count(conn) == 2, "the batch was rolled back, including the two rows that were valid"


def test_the_row_holds_no_free_text_and_no_royalty_terms(decisions: list[dict[str, Any]]) -> None:
    row = snowflake.row_for(decisions[0])
    assert set(row) == set(tables.columns("verdict_log"))
    assert all(len(str(v)) < 80 for v in row.values()), "a summary row, not the record"


def test_an_empty_batch_is_a_no_op(conn: sqlite3.Connection) -> None:
    assert snowflake.write_verdicts(conn, []) == 0 and count(conn) == 0


def test_the_snowflake_ddl_uses_snowflake_types_and_the_same_columns_as_the_others() -> None:
    sf, pg, lite = (tables.ddl(d) for d in ("snowflake", "postgres", "sqlite"))
    assert "TIMESTAMP_NTZ" in sf[2] and "STRING" in sf[0]
    for name in tables.TABLES:
        for col in tables.columns(name):
            assert all(
                f" {col} " in text
                for text in (
                    sf[list(tables.TABLES).index(name)],
                    pg[list(tables.TABLES).index(name)],
                    lite[list(tables.TABLES).index(name)],
                )
            )


def test_the_tables_are_read_from_the_graph_so_the_two_agree(store: Store) -> None:
    rows = tables.rows_from_graph(store)
    assert len(rows["patent_master"]) == 300
    assert {r["origin"] for r in rows["licensee"]} == {"real", "synthetic"}
    assert sum(1 for r in rows["patent_master"] if r["patent_number"] is None) > 0, "a missing number stays NULL"
