"""The same rules over a SPARQL endpoint give the same decisions as the in-memory store.

This is the test that lets a decision made on Neptune stand next to one made on a laptop. It runs the rule
engine twice, once over rdflib and once over Fuseki through HTTP, and compares the signatures of every finding.
Load the graph first: uv run python -m kg all
"""

from __future__ import annotations

import os

import pytest

from kg.sparql_store import SparqlStore
from kg.store import Store
from rules.book import load_book, to_request
from rules.engine import evaluate
from tests.rules.helpers import injected_cases, requests_by_id

ENDPOINT = os.environ.get("GONOGO_SPARQL_ENDPOINT", "http://localhost:3030/gonogo/query")
NOW = "2026-11-01T00:00:00Z"


@pytest.fixture(scope="module")
def remote() -> SparqlStore:
    return SparqlStore(ENDPOINT)


@pytest.mark.docker
def test_every_request_in_the_book_decides_the_same_over_http(store: Store, remote: SparqlStore) -> None:
    for row in load_book():
        request = to_request(row)
        local = evaluate(store, request, cutoff=NOW, as_of="2026-11-01")
        over_http = evaluate(remote, request, cutoff=NOW, as_of="2026-11-01")
        assert over_http.signature == local.signature, row["request_id"]
        assert over_http.verdict == local.verdict


@pytest.mark.docker
def test_every_injected_case_decides_the_same_at_its_own_cutoff(store: Store, remote: SparqlStore) -> None:
    requests = requests_by_id()
    for case in injected_cases():
        request = to_request(requests[case["request_id"]])
        kw = {"cutoff": case["recording_cutoff"], "as_of": case["as_of"]}
        assert evaluate(remote, request, **kw).signature == evaluate(store, request, **kw).signature, case["case_id"]
        assert evaluate(remote, request, **kw).verdict == case["expected_verdict"], case["case_id"]


def test_the_endpoint_store_refuses_a_query_with_no_graphs() -> None:
    with pytest.raises(ValueError, match="FROM"):
        SparqlStore("http://unused").select("SELECT * WHERE { ?s ?p ?o }")
