"""Check the w3id.org redirect rules against a local Apache that mirrors the live service.

Start the server first (docs/w3id/README.md), then run: uv run pytest -m w3id
After the rules are live on w3id.org, run the same checks against the real service:
    W3ID_BASE=https://w3id.org uv run pytest -m w3id
"""

from __future__ import annotations

import os

import httpx
import pytest
from rdflib import Graph

pytestmark = pytest.mark.w3id

BASE = os.environ.get("W3ID_BASE", "http://localhost:8080").rstrip("/")
SITE = "https://gonogo-livid.vercel.app"
BROWSER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
TURTLE = "text/turtle"

CASES = [
    # path, Accept header, expected status, expected location
    ("ontology", BROWSER, 303, f"{SITE}/ontology/index.html"),
    ("ontology", None, 303, f"{SITE}/ontology/index.html"),
    ("ontology", TURTLE, 303, f"{SITE}/ontology/gonogo.ttl"),
    ("ontology", "application/rdf+xml, text/turtle;q=0.9", 303, f"{SITE}/ontology/gonogo.ttl"),
    ("ontology/0.1.0", TURTLE, 303, f"{SITE}/ontology/gonogo.ttl"),
    ("ontology/0.1.0", BROWSER, 303, f"{SITE}/ontology/index.html"),
    ("shapes", TURTLE, 303, f"{SITE}/ontology/gonogo-shapes.ttl"),
    ("shapes", BROWSER, 303, f"{SITE}/ontology/shapes.html"),
    ("field/optics", BROWSER, 303, f"{SITE}/ontology/fields.html"),
    ("field/optics", TURTLE, 303, f"{SITE}/ontology/fields.ttl"),
    ("scheme/field-of-use", TURTLE, 303, f"{SITE}/ontology/fields.ttl"),
    ("territory/US", BROWSER, 303, f"{SITE}/ontology/territories.html"),
    ("scheme/territory", TURTLE, 303, f"{SITE}/ontology/territories.ttl"),
    ("exclusivity/exclusive", BROWSER, 303, f"{SITE}/ontology/exclusivity.html"),
    ("legal-state/lapsed", TURTLE, 303, f"{SITE}/ontology/legal-states.ttl"),
    ("id/patent/LEW-18089-1", BROWSER, 302, f"{SITE}/"),
    ("graph/approved", TURTLE, 302, f"{SITE}/"),
]


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    c = httpx.Client(follow_redirects=False, timeout=30)
    try:
        c.get(f"{BASE}/gonogo/ontology")
    except httpx.TransportError:
        pytest.skip(f"No w3id server at {BASE}")
    return c


@pytest.mark.parametrize(("path", "accept", "status", "location"), CASES)
def test_redirect(client: httpx.Client, path: str, accept: str | None, status: int, location: str) -> None:
    r = client.get(f"{BASE}/gonogo/{path}", headers={"Accept": accept} if accept else {})
    assert r.status_code == status
    assert r.headers["location"] == location


@pytest.mark.network
def test_the_turtle_that_a_client_receives_parses_and_declares_the_namespace(client: httpx.Client) -> None:
    redirect = client.get(f"{BASE}/gonogo/ontology", headers={"Accept": TURTLE})
    final = httpx.get(redirect.headers["location"], timeout=60)
    assert final.status_code == 200
    assert final.headers["content-type"].startswith("text/turtle")
    graph = Graph().parse(data=final.text, format="turtle")
    assert any(str(s).startswith("https://w3id.org/gonogo/ontology#") for s in graph.subjects())
