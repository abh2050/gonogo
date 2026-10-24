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
