"""Leakage through the HTTP API and through decision records: no response carries royalty terms."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.index import EXAMPLES, app
from kg.ns import GRAPH_ROYALTY
from kg.store import Store
from rules.book import load_book, to_request
from rules.engine import evaluate_now
from tests.leakage.conftest import leaks

client = TestClient(app)


def test_no_decision_in_the_request_book_carries_royalty_terms(store: Store, royalty_markers: list[str]) -> None:
    """A verdict card quotes clauses. It may quote grant, field, territory, and term clauses and never royalty ones."""
    for row in load_book():
        record = evaluate_now(store, to_request(row)).to_dict()
        assert leaks(json.dumps(record), royalty_markers) == [], row["request_id"]
        for finding in record["findings"]:
            assert all(c["kind"] != "royalty" for c in finding["clauses"]), row["request_id"]


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e["id"])
def test_no_example_answer_carries_royalty_terms(example: dict[str, Any], royalty_markers: list[str]) -> None:
    body = client.post("/api/decide", json={"text": example["text"]}).text
    assert leaks(body, royalty_markers) == []


def test_every_get_endpoint_is_clean(royalty_markers: list[str]) -> None:
    for path in ("/api/health", "/api/vocabulary", "/api/examples", "/api/authz"):
        assert leaks(client.get(path).text, royalty_markers) == [], path


def test_the_provenance_endpoint_cannot_walk_into_the_royalty_graph(
    full_store: Store, royalty_markers: list[str]
) -> None:
    """Royalty nodes are not in the demo snapshot, so asking for one finds nothing."""
    nodes = {str(s) for s in full_store.base[GRAPH_ROYALTY].subjects()}
    assert len(nodes) > 100
    for iri in sorted(nodes)[:40]:
        r = client.post("/api/provenance", json={"iri": iri})
        # The agreement node also exists in the approved graph, where only its title and clauses live.
        assert leaks(r.text, royalty_markers) == [], iri
    clause_nodes = [n for n in nodes if "/clause/" in n and n.endswith("/royalty")]
    assert len(clause_nodes) == 120, "the probe must find the royalty clauses, or it proves nothing"
    for iri in clause_nodes[:20]:
        assert client.post("/api/provenance", json={"iri": iri}).status_code == 404


def test_there_is_no_endpoint_that_takes_sparql() -> None:
    paths = {r.path for r in app.routes}
    assert not any("sparql" in p.lower() or "query" in p.lower() and p != "/api/queue" for p in paths)
    for path in ("/api/sparql", "/sparql", "/api/query", "/query", "/data", "/api/graph"):
        assert client.post(path, json={"query": "SELECT * WHERE { ?s ?p ?o }"}).status_code in (404, 405)


def test_the_snapshot_files_hold_no_royalty_text(royalty_markers: list[str]) -> None:
    from gonogo.paths import SNAPSHOT

    for f in SNAPSHOT.glob("*"):
        assert leaks(f.read_text(), royalty_markers) == [], f.name
    assert not (SNAPSHOT / "royalty.ttl").exists()
