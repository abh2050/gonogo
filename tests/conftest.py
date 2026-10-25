"""Shared fixtures. The knowledge graph builds once per test session."""

from __future__ import annotations

import pytest
from rdflib import Graph

from kg import build, materialize


@pytest.fixture(scope="session")
def kg_graphs() -> dict[str, Graph]:
    graphs = build.build_graphs()
    materialize.apply(graphs)
    return graphs


@pytest.fixture(scope="session")
def store(kg_graphs: dict[str, Graph]):  # type: ignore[no-untyped-def]
    """The graph as the rules see it: release, approved, and candidate graphs, with no royalty graph."""
    from kg.ns import GRAPH_ROYALTY
    from kg.store import Store

    return Store({iri: g for iri, g in kg_graphs.items() if iri != GRAPH_ROYALTY})
