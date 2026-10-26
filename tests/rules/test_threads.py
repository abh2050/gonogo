"""Decisions made at the same time on several threads all succeed and agree.

The API runs sync handlers on a thread pool, and rdflib's SPARQL parser is not safe across threads. Without the lock
in kg/store.py, parallel requests failed inside the parser with a 500.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from kg.store import Store
from rules.book import load_book, to_request
from rules.engine import evaluate


def test_parallel_decisions_succeed_and_match_the_serial_ones(store: Store) -> None:
    requests = [to_request(r) for r in load_book()[:8]]

    def decide(req):  # type: ignore[no-untyped-def]
        d = evaluate(
            store, req, cutoff="2026-11-01T00:00:00Z", as_of="2026-11-01", user="pat", role="licensing_manager"
        )
        return d.to_dict()["verdict"]

    # Parallel first: pyparsing works out each parse action's arguments on its first call, and that is the race.
    with ThreadPoolExecutor(max_workers=8) as pool:
        parallel = list(pool.map(decide, requests * 4))
    serial = [decide(r) for r in requests]
    assert parallel == serial * 4
