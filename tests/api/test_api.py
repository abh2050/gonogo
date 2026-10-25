"""The API over the frozen snapshot: the same engine, a stateless server, and a session the client holds."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.index import EXAMPLES, app
from gonogo.paths import SNAPSHOT

client = TestClient(app)
STEWARD = {"steward": "Demo Steward", "reason": "Checked against the source record."}


def post(path: str, **body: Any) -> dict[str, Any]:
    r = client.post(path, json=body)
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_the_snapshot_holds_no_royalty_graph() -> None:
    assert sorted(p.name for p in SNAPSHOT.glob("*.ttl")) == ["approved.ttl", "candidate.ttl", "release.ttl"]
    health = client.get("/api/health").json()
    assert set(health["graphs"]) == {"release", "approved", "candidate"}
    for name in ("approved.ttl", "candidate.ttl"):
        text = (SNAPSHOT / name).read_text()
        assert "royaltyRate" not in text and "RoyaltyTerm" not in text


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e["id"])
def test_every_example_reaches_its_stated_verdict(example: dict[str, Any]) -> None:
    out = post("/api/decide", text=example["text"])
    assert out["parse"]["complete"], out["parse"]["missing"]
    assert out["decision"]["verdict"] == example["expect"], out["decision"]["explanation"]


def test_an_incomplete_question_returns_the_parse_and_no_decision() -> None:
    out = post("/api/decide", text="Can Acme get a license to LEW-17915-1?")
    assert out["decision"] is None
    assert {"field", "territory", "start", "end"} <= set(out["parse"]["missing"])


def test_a_structured_request_with_an_unknown_concept_is_refused() -> None:
    r = client.post(
        "/api/decide",
        json={
            "request": {
                "patent_key": "LEW-17915-1",
                "exclusivity": "non-exclusive",
                "field": "time-travel",
                "territory": "US",
                "start": "2027-01-01",
                "end": "2031-12-31",
            }
        },
    )
    assert r.status_code == 422


def test_the_whole_loop_over_http() -> None:
    text = next(e["text"] for e in EXAMPLES if e["id"] == "export")
    first = post("/api/decide", text=text)["decision"]
    assert first["verdict"] == "NO DATA"

    queue = post("/api/queue")
    fact = next(f for f in queue["facts"] if f["kind"] == "UnrestrictedExport")
    acted = post("/api/act", event={"action": "approve_fact", **STEWARD, "params": {"candidate": fact["id"]}})
    events = acted["events"]
    assert len(events) == 1 and acted["sparql_update"][0].startswith("INSERT DATA")

    second = post("/api/decide", text=text, events=events, previous=first)
    assert second["decision"]["verdict"] == "GO"
    assert second["diff"]["changes"][0]["rule"] == "R5"

    again = post("/api/rerun", record=first, events=events)
    assert again["reproduced"] and again["decision"]["verdict"] == "NO DATA"

    assert fact["id"] not in {f["id"] for f in post("/api/queue", events=events)["facts"]}
    assert post("/api/queue")["facts"], "another visitor's session is untouched"


def test_a_rejected_action_changes_nothing() -> None:
    r = client.post(
        "/api/act",
        json={"event": {"action": "approve_fact", "steward": "x", "reason": "", "params": {"candidate": "nope"}}},
    )
    assert r.status_code == 422


def test_a_tampered_event_log_is_refused() -> None:
    r = client.post(
        "/api/queue",
        json={"events": [{"action": "approve_fact", **STEWARD, "params": {"candidate": "https://example.org/x"}}]},
    )
    assert r.status_code == 422


def test_identity_links_appear_in_the_queue_and_leave_it_once_decided() -> None:
    link = post("/api/queue")["links"][0]
    acted = post(
        "/api/act",
        event={
            "action": "link_identity",
            **STEWARD,
            "params": {"a": link["a"]["iri"], "b": link["b"]["iri"], "score": link["score"]},
        },
    )
    assert link["id"] not in {x["id"] for x in post("/api/queue", events=acted["events"])["links"]}


def test_the_provenance_graph_reaches_the_steward_after_an_approval() -> None:
    fact = post("/api/queue")["facts"][0]
    acted = post("/api/act", event={"action": "approve_fact", **STEWARD, "params": {"candidate": fact["id"]}})
    new = acted["result"]["new_facts"][0]
    g = post("/api/provenance", iri=new, events=acted["events"])
    labels = {lk["label"] for lk in g["links"]}
    assert {"gng:approvedBy", "prov:wasGeneratedBy", "prov:wasDerivedFrom"} <= labels
    assert any(n["id"].endswith("/steward/demo-steward") for n in g["nodes"])


def test_vocabulary_trees() -> None:
    v = client.get("/api/vocabulary").json()
    assert len(v["fields"]) == 51 and len(v["territories"]) == 22
    assert any(f["id"] == "lasers" and f["broader"] == "optics" for f in v["fields"])


# ---- Separation of duties over HTTP -------------------------------------------------------------------------

DECOY = "https://w3id.org/gonogo/id/ownership/LAR-17381-1/candidate"


def event(who: str, role: str, action: str, **params: Any) -> dict[str, Any]:
    return {"steward": who, "role": role, "action": action, "reason": "Checked the record.", "params": params}


def test_the_decoy_is_held_for_counsel_over_http() -> None:
    held = post("/api/act", event=event("Ann", "steward", "approve_fact", candidate=DECOY))
    assert held["result"]["route"] == "pending_second_review" and held["result"]["new_facts"] == []
    events = held["events"]

    queue = post("/api/queue", events=events)
    waiting = next(f for f in queue["facts"] if f["id"] == DECOY)
    assert waiting["state"] == "pending_second_review" and waiting["needs"] == "counsel"
    assert waiting["first_approver"] == "Ann" and waiting["conflicts"]
    assert queue["why"][DECOY], "the queue says why the approval waits"

    text = next(e["text"] for e in EXAMPLES if e["id"] == "coowner")
    assert post("/api/decide", text=text, events=events)["decision"]["verdict"] == "COUNSEL"

    r = client.post(
        "/api/act", json={"events": events, "event": event("Ann", "counsel", "second_review", candidate=DECOY)}
    )
    assert r.status_code == 422 and "different counsel" in r.json()["detail"]

    done = post("/api/act", events=events, event=event("Cy", "counsel", "second_review", candidate=DECOY))
    assert done["result"]["route"] == "approved"
    assert post("/api/decide", text=text, events=done["events"])["decision"]["verdict"] == "GO"


def test_the_sessions_own_questions_are_checked_before_an_approval_stands_alone() -> None:
    """A clean-looking link that would move this visitor's question to GO still waits for counsel."""
    link = post("/api/queue")["links"][0]
    ask = (
        "Can GenH2 Corporation get a non-exclusive license to US Patent 10,431,355 for energy generation "
        "in the USA for five years starting January 1, 2027?"
    )
    params = {"a": link["a"]["iri"], "b": link["b"]["iri"], "score": link["score"]}
    alone = post("/api/act", event=event("Ann", "steward", "link_identity", **params))
    assert alone["result"]["route"] == "immediate", "with no session question, nothing moves to GO"
    held = post("/api/act", event=event("Ann", "steward", "link_identity", **params), requests=[{"text": ask}])
    assert held["result"]["route"] == "pending_second_review"
    assert held["result"]["flags"]["upgrades"]


def test_a_refused_role_is_a_422_with_the_reason() -> None:
    r = client.post("/api/act", json={"event": event("Pat", "licensing_manager", "approve_fact", candidate=DECOY)})
    assert r.status_code == 422 and "licensing manager role may not" in r.json()["detail"]


def test_a_stewards_own_proposal_goes_to_someone_else() -> None:
    proposed = post(
        "/api/act",
        event=event(
            "Ann", "steward", "propose_fact", kind="export", patent_key="LAR-17317-2", classification="unrestricted"
        ),
    )
    candidate = proposed["result"]["candidate"]
    own = client.post(
        "/api/act",
        json={"events": proposed["events"], "event": event("Ann", "steward", "approve_fact", candidate=candidate)},
    )
    assert own.status_code == 422 and "You proposed this fact" in own.json()["detail"]
    other = post(
        "/api/act", events=proposed["events"], event=event("Ben", "steward", "approve_fact", candidate=candidate)
    )
    assert other["result"]["route"] == "immediate"


def test_the_authz_matrix_comes_from_the_policies() -> None:
    m = client.get("/api/authz").json()
    assert m["roles"] == ["licensing_manager", "steward", "counsel", "ontology_owner", "finance_analyst", "auditor"]
    row = {r["label"]: r["allowed"] for r in m["rows"]}
    assert row["Read the royalty graph"] == {r: r == "counsel" for r in m["roles"]}
    assert row["Approve a conflicting fact alone"] == {r: False for r in m["roles"]}
    assert row["Second review"]["counsel"] and not row["Second review"]["steward"]
