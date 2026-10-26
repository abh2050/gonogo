from __future__ import annotations

import re

import pytest
from rdflib import Graph, Literal

from kg.ns import GRAPH_APPROVED, GRAPH_CANDIDATE, GRAPH_RELEASE, GRAPH_ROYALTY
from kg.store import Store

# Patterns that only a royalty clause or an agreement's full text contains. The ontology may define royalty terms
# ("The running royalty as a percentage of net sales"), so these match the data, such as "a running royalty of 3.0".
ROYALTY_PATTERNS = [
    r"running royalty of [0-9]",
    r"minimum annual royalty of [0-9]",
    r"percent of Net Sales",
    r"This Article is confidential",
    r"Article 5\. Royalties",
    r"PATENT LICENSE AGREEMENT AGR-[0-9]+\s+SYNTHETIC DOCUMENT",  # the title alone is not confidential
]


@pytest.fixture(scope="session")
def full_store(kg_graphs: dict[str, Graph]) -> Store:
    """A store that holds all four graphs, as Neptune does. Only the service's checks stand between a user and them."""
    return Store(kg_graphs)


@pytest.fixture(scope="session")
def royalty_markers(kg_graphs: dict[str, Graph]) -> list[str]:
    """Every long literal in the royalty graph that no other graph holds, plus the royalty phrases."""
    elsewhere = {
        str(o)
        for g in (GRAPH_APPROVED, GRAPH_RELEASE, GRAPH_CANDIDATE)
        for _, _, o in kg_graphs[g]
        if isinstance(o, Literal)
    }
    marks = {str(o) for _, _, o in kg_graphs[GRAPH_ROYALTY] if isinstance(o, Literal) and len(str(o)) >= 8}
    return sorted(marks - elsewhere)


def leaks(text: str, markers: list[str]) -> list[str]:
    """The royalty literals and royalty patterns found in `text`. An empty list means nothing leaked."""
    flat = re.sub(r"\s+", " ", text)
    found = [m[:60] for m in markers if m in text or re.sub(r"\s+", " ", m) in flat]
    found += [p for p in ROYALTY_PATTERNS if re.search(p, text)]
    return found
