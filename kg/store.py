"""The knowledge graph as the rules see it: frozen base graphs plus an overlay of steward events.

The base graphs come from the build (build/kg/*.ttl) or from a frozen snapshot. Steward actions never edit
them. Each action is an event, and applying events adds triples to a small overlay graph, so one store
serves a laptop, a Vercel function, and (in Gate 3) the same actions against Neptune.

A query names its graphs in FROM clauses. The store answers it over a read-only union of those graphs and
their overlays, and it never reads a graph that the template did not name.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from rdflib import Graph, URIRef
from rdflib.graph import ReadOnlyGraphAggregate

from gonogo.paths import BUILD
from kg.ns import GRAPH_APPROVED, GRAPH_CANDIDATE, GRAPH_RELEASE, GRAPH_ROYALTY
from kg.templates import strip_from

# rdflib parses SPARQL with pyparsing, which is not safe across threads: two requests parsing at once in the API's
# thread pool fail with errors inside the parser. Every in-process query takes this lock.
SPARQL_LOCK = threading.Lock()

GRAPH_FILES = {
    GRAPH_RELEASE: "release.ttl",
    GRAPH_APPROVED: "approved.ttl",
    GRAPH_CANDIDATE: "candidate.ttl",
    GRAPH_ROYALTY: "royalty.ttl",
}
_FROM = re.compile(r"\bFROM\s+<([^>]+)>")


class Reader(Protocol):
    """What the rule engine needs from a store. The in-memory Store and the SPARQL endpoint store both provide it."""

    events: list[dict[str, Any]]

    def select(self, query: str) -> list[dict[str, Any]]: ...

    def has_type(self, iri: str, cls: URIRef) -> bool: ...


class Store:
    def __init__(self, graphs: dict[str, Graph]) -> None:
        self.base = graphs
        self.overlay: dict[str, Graph] = {iri: Graph() for iri in graphs}
        self.decided: dict[str, dict[str, Any]] = {}  # candidate IRI -> the event that decided it
        self.events: list[dict[str, Any]] = []
        # Approvals that a steward made and that wait for counsel: key -> the steward's event. They change nothing.
        self.pending: dict[str, dict[str, Any]] = {}

    # ---- loading ------------------------------------------------------------------------------

    @classmethod
    def from_build(cls, directory: Path | None = None, include_royalty: bool = False) -> Store:
        """Load the graphs that `python -m kg build` wrote. The royalty graph stays out unless asked for."""
        directory = directory or BUILD / "kg"
        graphs: dict[str, Graph] = {}
        for iri, name in GRAPH_FILES.items():
            if iri == GRAPH_ROYALTY and not include_royalty:
                continue
            graphs[iri] = Graph().parse(directory / name)
        return cls(graphs)

    def fork(self) -> Store:
        """A store over the same base graphs with no events, for replaying a log from the start."""
        return Store(self.base)

    def copy(self) -> Store:
        """A store over the same base graphs with its own copy of the events so far."""
        other = Store(self.base)
        for iri, g in self.overlay.items():
            for t in g:
                other.overlay[iri].add(t)
        other.decided = dict(self.decided)
        other.events = list(self.events)
        other.pending = dict(self.pending)
        return other

    # ---- querying -----------------------------------------------------------------------------

    def view(self, iris: Iterable[str]) -> ReadOnlyGraphAggregate:
        """A read-only union of the named graphs, with the overlay that actions wrote."""
        return self._union(iris)

    def _union(self, iris: Iterable[str]) -> ReadOnlyGraphAggregate:
        parts: list[Graph] = []
        for iri in iris:
            if iri not in self.base:
                raise KeyError(f"The store does not hold the graph {iri}")
            parts.append(self.base[iri])
            if len(self.overlay[iri]):
                parts.append(self.overlay[iri])
        return ReadOnlyGraphAggregate(parts)

    def select(self, query: str) -> list[dict[str, Any]]:
        """Run a rendered SELECT. The graphs come from its FROM clauses, and a query without any is refused."""
        iris = _FROM.findall(query)
        if not iris:
            raise ValueError("A query must name its graphs with FROM clauses.")
        with SPARQL_LOCK:
            result = self._union(iris).query(strip_from(query))
            return [dict(row.asdict()) for row in result]  # type: ignore[union-attr]

    def update(self, graph_iri: str, triples: Iterable[tuple[Any, Any, Any]]) -> None:
        """Add triples to a graph's overlay. Only actions call this."""
        target = self.overlay[graph_iri]
        for t in triples:
            target.add(t)

    def has_type(self, iri: str, cls: URIRef) -> bool:
        """Whether the approved or release graph says `iri` is an instance of `cls`."""
        from rdflib import RDF

        return any((URIRef(iri), RDF.type, cls) in self.base[g] for g in (GRAPH_APPROVED, GRAPH_RELEASE))

    def graph_size(self, graph_iri: str) -> int:
        return len(self.base[graph_iri]) + len(self.overlay[graph_iri])

    def subjects_of_type(self, graph_iri: str, cls: URIRef) -> list[URIRef]:
        from rdflib import RDF

        found = set(self.base[graph_iri].subjects(RDF.type, cls)) | set(self.overlay[graph_iri].subjects(RDF.type, cls))
        return sorted((s for s in found if isinstance(s, URIRef)), key=str)
