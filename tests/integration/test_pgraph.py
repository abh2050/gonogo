"""R2 in Cypher on Neo4j returns the same grants as R2 in SPARQL, for every request (ADR 0003). Needs Docker."""

from __future__ import annotations

import pytest

from kg.store import Store
from pgraph import compare, load


@pytest.mark.docker
def test_cypher_and_sparql_agree_on_every_request(store: Store) -> None:
    load.load(store)
    result = compare.main()
    assert result["agree"] == result["requests"], result["differ"][:3]
    assert result["with_a_conflict"] > 300  # the comparison is not an agreement about nothing
