"""The AWS handlers, driven with API Gateway events and no AWS account."""

from __future__ import annotations

import json
from typing import Any

import pytest

from kg.ns import GRAPH_APPROVED, GRAPH_ROYALTY
from kg.store import Store
from rules.book import load_book, to_request
from rules.engine import evaluate
from service import engine_lambda, handler, neptune
from service.identity import IdentityError, groups_from, principal_from_claims

NOW = "2026-11-01T00:00:00Z"
DECOY = "https://w3id.org/gonogo/id/ownership/LAR-17381-1/candidate"


def claims(user: str, *groups: str) -> dict[str, Any]:
    return {"cognito:username": user, "cognito:groups": "[" + " ".join(groups) + "]", "sub": user + "-sub"}


def gateway_event(method: str, path: str, body: dict[str, Any] | None, who: dict[str, Any] | None) -> dict[str, Any]:
    """The shape of an API Gateway REST proxy event, with the claims that the Cognito authorizer adds."""
    return {
        "resource": path,
        "path": path,
        "httpMethod": method,
        "headers": {"Content-Type": "application/json", "Host": "api.test"},
        "multiValueHeaders": {"Content-Type": ["application/json"], "Host": ["api.test"]},
        "queryStringParameters": None,
        "multiValueQueryStringParameters": None,
        "pathParameters": None,
        "stageVariables": None,
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
        "requestContext": {
            "resourceId": "r",
            "resourcePath": path,
            "httpMethod": method,
            "path": "/prod" + path,
            "stage": "prod",
            "requestId": "req-1",
            "identity": {"sourceIp": "203.0.113.9", "userAgent": "test"},
            "domainName": "api.test",
            "protocol": "HTTP/1.1",
            "authorizer": {"claims": who} if who else {},
        },
    }


class InMemoryEndpoint:
    """Stands in for Neptune: it answers the same two calls the rule engine makes, from the local graphs."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.events: list[dict[str, Any]] = []
        self.asked: list[str] = []

    def select(self, query: str) -> list[dict[str, Any]]:
        self.asked.append(query)
        return self.store.select(query) if "FROM <" in query else []

    def has_type(self, iri: str, cls: Any) -> bool:
        return self.store.has_type(iri, cls)

    def ask(self, query: str) -> bool:
        return True


@pytest.fixture
def fake_neptune(store: Store, monkeypatch: pytest.MonkeyPatch) -> InMemoryEndpoint:
    endpoint = InMemoryEndpoint(store)
    monkeypatch.setattr(neptune, "store", lambda region=None: endpoint)
    return endpoint


def call(method: str, path: str, body: dict[str, Any] | None, who: dict[str, Any] | None) -> tuple[int, Any]:
    out = handler.handler(gateway_event(method, path, body, who))
    return out["statusCode"], json.loads(out["body"])


# ---- Identity -----------------------------------------------------------------------------------------------------


def test_groups_come_as_a_list_or_a_bracketed_string() -> None:
    assert groups_from({"cognito:groups": "[steward]"}) == ["steward"]
    assert groups_from({"cognito:groups": ["steward", "counsel"]}) == ["steward", "counsel"]
    assert groups_from({}) == []


def test_exactly_one_role_group_is_required() -> None:
    assert principal_from_claims(claims("ann", "steward")).role == "steward"
    for bad in (claims("x"), claims("x", "steward", "counsel"), claims("x", "admins")):
        with pytest.raises(IdentityError):
            principal_from_claims(bad)


def test_no_identity_means_no_service() -> None:
    assert call("GET", "/health", None, None)[0] == 401
    assert call("GET", "/health", None, claims("x", "steward", "counsel"))[0] == 403


# ---- The query Lambda ---------------------------------------------------------------------------------------------


def test_health_tells_each_role_what_it_may_read() -> None:
    status, body = call("GET", "/health", None, claims("pat", "licensing_manager"))
    assert status == 200 and body["graphs"] == ["release", "approved"]
    assert call("GET", "/health", None, claims("fin", "finance_analyst"))[1]["graphs"] == []


def test_a_query_over_a_forbidden_graph_is_refused_before_it_reaches_neptune(fake_neptune: InMemoryEndpoint) -> None:
    status, body = call(
        "POST",
        "/query",
        {"query": f"SELECT * FROM <{GRAPH_ROYALTY}> WHERE {{ ?s ?p ?o }}"},
        claims("pat", "licensing_manager"),
    )
    assert status == 403 and "may not read the royalty graph" in body["error"]
    assert fake_neptune.asked == [], "Neptune never saw the query"


def test_a_permitted_query_reaches_neptune_with_its_from_clause(fake_neptune: InMemoryEndpoint) -> None:
    query = f"SELECT ?s FROM <{GRAPH_APPROVED}> WHERE {{ ?s a <https://w3id.org/gonogo/ontology#Patent> }} LIMIT 3"
    status, body = call("POST", "/query", {"query": query}, claims("pat", "licensing_manager"))
    assert status == 200 and len(body["rows"]) == 3 and body["graphs"] == [GRAPH_APPROVED]
    assert fake_neptune.asked == [query]


def test_a_decision_over_neptune_matches_the_local_decision(fake_neptune: InMemoryEndpoint, store: Store) -> None:
    row = load_book()[0]
    request = to_request(row)
    status, body = call(
        "POST",
        "/decide",
        {
            "request": {k: v for k, v in request.canonical().items() if k != "licensee_country"}
            | {"licensee_country": "US"}
        },
        claims("pat", "licensing_manager"),
    )
    assert status == 200 and body["backend"] == "neptune"
    local = evaluate(store, request, cutoff=NOW, as_of="2026-11-01", user="pat", role="licensing_manager")
    assert body["decision"]["verdict"] == local.verdict and body["decision"]["user"] == "pat"


def test_roles_that_may_not_ask_get_a_403(fake_neptune: InMemoryEndpoint) -> None:
    request = {
        "patent_key": "LAR-17317-2",
        "exclusivity": "non-exclusive",
        "field": "test-and-measurement",
        "territory": "US",
        "start": "2027-01-01",
        "end": "2031-12-31",
    }
    for role in ("finance_analyst", "auditor", "ontology_owner"):
        assert call("POST", "/decide", {"request": request}, claims("x", role))[0] == 403


# ---- The engine Lambda -----------------------------------------------------------------------------------


def engine(method: str, path: str, body: dict[str, Any] | None, who: dict[str, Any] | None) -> tuple[int, Any]:
    out = engine_lambda.handler(gateway_event(method, path, body, who), None)
    return out["statusCode"], json.loads(out["body"])


def test_the_engine_reads_identity_from_the_token_and_not_from_the_body() -> None:
    """The body claims counsel. The token says steward. The token wins, so the second review is refused."""
    held = engine(
        "POST",
        "/api/act",
        {
            "event": {
                "action": "approve_fact",
                "steward": "ann",
                "role": "steward",
                "reason": "Checked it.",
                "params": {"candidate": DECOY},
            }
        },
        claims("ann", "steward"),
    )
    assert held[0] == 200 and held[1]["result"]["route"] == "pending_second_review"
    forged = engine(
        "POST",
        "/api/act",
        {
            "events": held[1]["events"],
            "event": {
                "action": "second_review",
                "steward": "cy",
                "role": "counsel",
                "reason": "I am counsel, honest.",
                "params": {"candidate": DECOY},
            },
        },
        claims("ben", "steward"),
    )
    assert forged[0] == 422 and "role may not do SecondReview" in forged[1]["detail"]
    honest = engine(
        "POST",
        "/api/act",
        {
            "events": held[1]["events"],
            "event": {"action": "second_review", "reason": "Checked the assignment.", "params": {"candidate": DECOY}},
        },
        claims("cy", "counsel"),
    )
    assert honest[0] == 200 and honest[1]["result"]["route"] == "approved"
    log = honest[1]["events"]
    assert [(e["steward"], e["role"]) for e in log] == [("ann", "steward"), ("cy", "counsel")]


def test_the_engine_enforces_cedar_on_reads() -> None:
    assert engine("POST", "/api/queue", {}, claims("pat", "licensing_manager"))[0] == 403
    assert engine("POST", "/api/queue", {}, claims("ann", "steward"))[0] == 200
    text = (
        "Orbital Lens Works, Inc. wants a non-exclusive license to NASA case LEW-17915-1 for optical "
        "communications in United States from January 1, 2027 to December 31, 2031."
    )
    assert engine("POST", "/api/decide", {"text": text}, claims("fin", "finance_analyst"))[0] == 403
    status, body = engine("POST", "/api/decide", {"text": text}, claims("pat", "licensing_manager"))
    assert status == 200 and body["decision"]["user"] == "pat" and body["decision"]["role"] == "licensing_manager"


def test_a_manager_sees_no_candidate_nodes_through_provenance() -> None:
    iri = "https://w3id.org/gonogo/id/ownership/LAR-17381-1/candidate"
    assert engine("POST", "/api/provenance", {"iri": iri}, claims("pat", "licensing_manager"))[0] == 404
    assert engine("POST", "/api/provenance", {"iri": iri}, claims("ann", "steward"))[0] == 200
