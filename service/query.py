"""The query service: the only path from a user to the graph.

Neptune treats its default graph as the union of every named graph, so a query that names no graph reads them
all, royalty terms included. The service therefore never forwards a user's query as written. It parses the
query, accepts a SELECT or ASK only, requires FROM clauses, and lets each FROM name only a graph that Cedar
allows the principal to read. GRAPH patterns, SERVICE federation, DESCRIBE, CONSTRUCT, updates, and graph store
operations are refused. The same function runs in the Lambda behind API Gateway and in the tests.

    execute(principal, query)         a user's SPARQL, validated against the principal's graphs
    run_template(principal, ...)      a rule template, with the principal's graphs filled into FROM

A second layer limits the data itself. The store that answers the query holds only the principal's graphs, so a
mistake in validation would still find nothing to leak.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.term import URIRef

from authz import cedar
from kg.ns import GRAPH_APPROVED, GRAPH_CANDIDATE, GRAPH_RELEASE, GRAPH_ROYALTY
from kg.store import SPARQL_LOCK, Store

GRAPH_BY_NAME = {
    "release": GRAPH_RELEASE,
    "approved": GRAPH_APPROVED,
    "candidate": GRAPH_CANDIDATE,
    "royalty": GRAPH_ROYALTY,
}
NAME_BY_IRI = {v: k for k, v in GRAPH_BY_NAME.items()}
MAX_QUERY_CHARS = 8000
MAX_ROWS = 1000


class QueryRefusedError(PermissionError):
    """The query is not allowed. The message says which rule it broke, never which data it would have found."""


@dataclass
class Result:
    rows: list[dict[str, Any]]
    graphs: list[str]
    truncated: bool = False


def _walk(node: Any) -> Any:
    """Every CompValue in a parsed query, depth first."""
    if isinstance(node, CompValue):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _walk(v)
    elif hasattr(node, "asList"):
        yield from _walk(node.asList())


FORBIDDEN_PATTERNS = {
    "GraphGraphPattern": "GRAPH patterns can reach a graph that FROM did not name.",
    "ServiceGraphPattern": "SERVICE federation is not allowed.",
}
FORBIDDEN_FORMS = {
    "ConstructQuery": "CONSTRUCT is not allowed.",
    "DescribeQuery": "DESCRIBE is not allowed.",
}


def validate(principal: cedar.Principal, query: str) -> list[str]:
    """Check a query and return the graph IRIs it may read. Raises QueryRefusedError otherwise."""
    if len(query) > MAX_QUERY_CHARS:
        raise QueryRefusedError("The query is too long.")
    if re.search(
        r"(?i)\b(insert|delete|load|clear|drop|create|copy|move|add)\b\s*(data|where|silent|graph|\{|<)", query
    ):
        raise QueryRefusedError("Only SELECT and ASK queries are allowed.")
    try:
        parsed = parseQuery(query)
    except Exception as exc:
        raise QueryRefusedError("The query does not parse as SPARQL.") from exc
    body = parsed[1]
    form = getattr(body, "name", "")
    if form in FORBIDDEN_FORMS:
        raise QueryRefusedError(FORBIDDEN_FORMS[form])
    if form not in ("SelectQuery", "AskQuery"):
        raise QueryRefusedError("Only SELECT and ASK queries are allowed.")
    named: list[str] = []
    for node in _walk(parsed):
        if node.name in FORBIDDEN_PATTERNS:
            raise QueryRefusedError(FORBIDDEN_PATTERNS[node.name])
        if node.name == "DatasetClause":
            if "named" in node:  # CompValue.get() falls back to the key, so test membership
                raise QueryRefusedError("FROM NAMED is not allowed.")
            named.append(str(node["default"]))
    if not named:
        raise QueryRefusedError("A query must name its graphs with FROM clauses.")
    allowed = set(cedar.readable_graphs(principal))
    graphs: list[str] = []
    for iri in named:
        name = NAME_BY_IRI.get(iri)
        if name is None:
            raise QueryRefusedError("FROM names a graph that this service does not hold.")
        if name not in allowed:
            raise QueryRefusedError(f"The {principal.role.replace('_', ' ')} role may not read the {name} graph.")
        graphs.append(iri)
    return list(dict.fromkeys(graphs))


def form_of(query: str) -> str:
    """'ask' or 'select', read from the parse tree and not from the text."""
    return "ask" if getattr(parseQuery(query)[1], "name", "") == "AskQuery" else "select"


class Backend(Protocol):
    """Where a validated query runs. The service validates first and never lets a backend see anything else."""

    def run(self, graphs: list[str], query: str) -> list[dict[str, Any]]: ...


class LocalBackend:
    """In memory: the data a query can see is only the graphs it named, so a mistake in validation finds nothing."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def run(self, graphs: list[str], query: str) -> list[dict[str, Any]]:
        from kg.templates import strip_from

        with SPARQL_LOCK:
            out = self.store.view(graphs).query(strip_from(query))
            if out.type == "ASK":
                return [{"ask": bool(out.askAnswer)}]
            return [{str(k): str(v) for k, v in row.asdict().items()} for row in out]  # type: ignore[union-attr]


class EndpointBackend:
    """A SPARQL endpoint. Neptune builds its default graph from the validated FROM clauses."""

    def __init__(self, endpoint: Any) -> None:
        self.endpoint = endpoint  # a kg.sparql_store.SparqlStore

    def run(self, graphs: list[str], query: str) -> list[dict[str, Any]]:
        if re.match(r"(?is)^\s*(prefix[^\n]*\n\s*)*ask\b", query) or re.search(
            r"(?is)\bask\b\s*(from|\{)", query[:600]
        ):
            return [{"ask": self.endpoint.ask(query)}]
        return [{k: str(v) for k, v in row.items()} for row in self.endpoint.select(query)]


def execute(target: Store | Backend, principal: cedar.Principal, query: str) -> Result:
    """Run a validated query. `target` is a Store (tests, the demo) or a Backend (Neptune)."""
    graphs = validate(principal, query)
    backend: Backend = LocalBackend(target) if isinstance(target, Store) else target
    rows = backend.run(graphs, query)
    if len(rows) > MAX_ROWS:
        return Result(rows[:MAX_ROWS], graphs, truncated=True)
    return Result(rows, graphs)


def run_template(store: Store, principal: cedar.Principal, template: str) -> list[dict[str, Any]]:
    """Run a rule template whose graphs the service fills in, never the caller."""
    from kg.templates import strip_from

    allowed = [GRAPH_BY_NAME[g] for g in cedar.readable_graphs(principal)]
    needed = [g for g in re.findall(r"^FROM <([^>]+)>", template, flags=re.M)]
    if not needed:
        raise QueryRefusedError("A template must name its graphs with FROM clauses.")
    for g in needed:
        if g not in allowed:
            raise QueryRefusedError(
                f"The {principal.role.replace('_', ' ')} role may not read the {NAME_BY_IRI.get(g, 'unknown')} graph."
            )
    with SPARQL_LOCK:
        return [dict(r.asdict()) for r in store.view(needed).query(strip_from(template))]  # type: ignore[union-attr]


def graph_store_request(principal: cedar.Principal, method: str, graph: str) -> None:
    """The SPARQL Graph Store Protocol (GET, PUT, POST, DELETE on a graph) is not exposed to any user."""
    raise QueryRefusedError(f"{method} on a graph is not available through this service.")


def known_graph(iri: str) -> bool:
    return URIRef(iri) in {URIRef(g) for g in GRAPH_BY_NAME.values()}
