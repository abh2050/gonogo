"""The relational side of GoNoGo: three tables that Snowflake holds and the R2RML mapping describes.

    PATENT_MASTER  the patent master, loaded nightly
    LICENSEE       the licensee list, loaded nightly
    VERDICT_LOG    one row per decision, written back after each clearance

One specification produces the DDL for Snowflake (the real target), PostgreSQL (the Ontop test), and SQLite (the
writeback tests). Names are unquoted lowercase, so each database folds them its own way and the mapping reads
the same on all three.
"""

from __future__ import annotations

from typing import Any

# (column, type, nullable). Types are logical: "text", "timestamp", "date".
TABLES: dict[str, dict[str, Any]] = {
    "patent_master": {
        "key": "patent_key",
        "columns": [
            ("patent_key", "text", False),
            ("case_number", "text", True),
            ("patent_number", "text", True),
            ("application_sn", "text", True),
            ("title", "text", False),
            ("center_code", "text", True),
        ],
    },
    "licensee": {
        "key": "licensee_key",
        "columns": [
            ("licensee_key", "text", False),
            ("origin", "text", False),  # 'real' for a name read from a notice, 'synthetic' for a generated one
            ("legal_name", "text", False),
            ("country", "text", True),
            ("address", "text", True),
        ],
    },
    "verdict_log": {
        "key": "decision_id",
        "columns": [
            ("decision_id", "text", False),
            ("patent_key", "text", False),
            ("verdict", "text", False),
            ("signature", "text", False),
            ("decided_by", "text", False),
            ("role", "text", False),
            ("release_version", "text", False),
            ("combiner_policy_version", "text", False),
            ("recording_cutoff", "timestamp", False),
        ],
    },
}
TYPES = {
    "snowflake": {"text": "STRING", "timestamp": "TIMESTAMP_NTZ", "date": "DATE"},
    "postgres": {"text": "TEXT", "timestamp": "TIMESTAMP", "date": "DATE"},
    "sqlite": {"text": "TEXT", "timestamp": "TEXT", "date": "TEXT"},
}


def ddl(dialect: str) -> list[str]:
    types = TYPES[dialect]
    out = []
    for name, spec in TABLES.items():
        cols = ",\n".join(
            f"  {c} {types[t]}{'' if nullable else ' NOT NULL'}{' PRIMARY KEY' if c == spec['key'] else ''}"
            for c, t, nullable in spec["columns"]
        )
        out.append(f"CREATE TABLE {name} (\n{cols}\n)")
    return out


def columns(table: str) -> list[str]:
    return [c for c, _, _ in TABLES[table]["columns"]]


def literal(value: Any) -> str:
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


def inserts(table: str, rows: list[dict[str, Any]]) -> list[str]:
    cols = columns(table)
    return [
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(literal(r.get(c)) for c in cols)})" for r in rows
    ]


def rows_from_graph(store: Any) -> dict[str, list[dict[str, Any]]]:
    """Patent master and licensee rows, read from the built graph so that the tables and the graph agree."""
    from rdflib import RDF
    from rdflib.namespace import DCTERMS

    from kg.ns import GNG, GRAPH_APPROVED, SCHEMA

    g = store.base[GRAPH_APPROVED]
    patents = []
    for node in sorted(g.subjects(RDF.type, GNG.Patent)):
        center = g.value(node, GNG.center)
        patents.append(
            {
                "patent_key": str(node).rsplit("/", 1)[-1],
                "case_number": _str(g.value(node, GNG.caseNumber)),
                "patent_number": _str(g.value(node, GNG.patentNumber)),
                "application_sn": _str(g.value(node, GNG.applicationSerial)),
                "title": _str(g.value(node, DCTERMS.title)) or "",
                "center_code": str(center).rsplit("/", 1)[-1] if center is not None else None,
            }
        )
    licensees = []
    for node in sorted(g.subjects(RDF.type, GNG.Licensee)):
        tail = str(node).split("/licensee/", 1)[1]
        real = tail.startswith("real/")
        licensees.append(
            {
                "licensee_key": tail.removeprefix("real/"),
                "origin": "real" if real else "synthetic",
                "legal_name": _str(g.value(node, SCHEMA.legalName)) or "",
                "country": _str(g.value(node, GNG.countryCode)),
                # One company can carry two spellings of an address, one per notice ("La Mesa, CA" and
                # "La Mesa, California"). The graph keeps both. The table has one column, so it takes the first
                # in sorted order, which makes the choice the same on every run.
                "address": _first(g.objects(node, GNG.registeredAddress)),
            }
        )
    return {"patent_master": patents, "licensee": licensees}


def _first(values: Any) -> str | None:
    found = sorted(str(v) for v in values)
    return found[0] if found else None


def _str(value: Any) -> str | None:
    return None if value is None else str(value)
