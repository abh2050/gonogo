"""A read-only store that sends SPARQL to an endpoint: Fuseki on a laptop, Neptune on AWS.

The rule engine asks its store two things: run this SELECT, and does this node have this type. A store that
answers both from an endpoint runs the same rules, templates, and combiner as the in-memory store, so a decision
made on Neptune can be compared with the decision made on a laptop. Writes are not here: steward actions run in
the engine and reach Neptune as SPARQL UPDATE (kg.actions.to_sparql_update).

Neptune requires every request to carry an AWS Signature Version 4 header, so the store takes a `sign` function
that adds one. Without it the store sends plain requests, as Fuseki expects.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from rdflib import Literal, URIRef
from rdflib.term import BNode, Node

Sign = Callable[[str, str, bytes, dict[str, str]], dict[str, str]]  # (method, url, body, headers) -> signed headers


def term(binding: dict[str, str]) -> Node:
    """A SPARQL JSON binding as an rdflib term."""
    kind, value = binding["type"], binding["value"]
    if kind == "uri":
        return URIRef(value)
    if kind == "bnode":
        return BNode(value)
    return Literal(
        value, lang=binding.get("xml:lang"), datatype=URIRef(binding["datatype"]) if "datatype" in binding else None
    )


class SparqlStore:
    """The read side of a Store, over HTTP."""

    def __init__(self, endpoint: str, sign: Sign | None = None, timeout: float = 30.0) -> None:
        self.endpoint = endpoint
        self.sign = sign
        self.client = httpx.Client(timeout=timeout)
        self.events: list[dict[str, Any]] = []  # a read-only store has applied no steward actions
        self.queries_run = 0

    def _post(self, query: str) -> dict[str, Any]:
        body = str(httpx.QueryParams({"query": query})).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/sparql-results+json"}
        if self.sign:
            headers = self.sign("POST", self.endpoint, body, headers)
        response = self.client.post(self.endpoint, content=body, headers=headers)
        response.raise_for_status()
        self.queries_run += 1
        return dict(response.json())

    def select(self, query: str) -> list[dict[str, Any]]:
        """Run a rendered SELECT. Each FROM clause stays in the query: the endpoint builds the dataset from them."""
        if "FROM <" not in query:
            raise ValueError("A query must name its graphs with FROM clauses.")
        out = self._post(query)
        return [{k: term(v) for k, v in row.items()} for row in out["results"]["bindings"]]

    def ask(self, query: str) -> bool:
        return bool(self._post(query)["boolean"])

    def has_type(self, iri: str, cls: URIRef) -> bool:
        from kg.ns import GRAPH_APPROVED, GRAPH_RELEASE

        return self.ask(f"ASK\nFROM <{GRAPH_APPROVED}>\nFROM <{GRAPH_RELEASE}>\n{{ <{iri}> a <{cls}> }}")
