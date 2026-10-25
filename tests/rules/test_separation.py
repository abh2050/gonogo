"""Separation of duties on real data: who may approve a fact, and when a second person must."""

from __future__ import annotations

from typing import Any

import pytest
from rdflib import RDF, URIRef

from kg.actions import ActionRejectedError, apply_event, describe_candidate, replay, to_sparql_update
from kg.ns import GNG, GRAPH_APPROVED
from kg.store import Store
from rules.book import to_request
from rules.engine import evaluate_now
from tests.rules.helpers import injected_cases, requests_by_id

ANN = {"steward": "Ann Steward", "role": "steward"}
CY = {"steward": "Cy Counsel", "role": "counsel"}
REASON = "Checked against the assignment record."


def decoy_case() -> dict[str, Any]:
    return next(c for c in injected_cases() if c["type"] == "decoy_approval_needs_second_approver")


def decoy_iri() -> str:
    key = decoy_case()["patent_key"]
    return f"https://w3id.org/gonogo/id/ownership/{key}/candidate"


def decoy_request():  # type: ignore[no-untyped-def]
    return to_request(requests_by_id()[decoy_case()["request_id"]])


def act(who: dict[str, str], action: str, **params: Any) -> dict[str, Any]:
    return {**who, "action": action, "reason": REASON, "params": params}


@pytest.fixture
def fresh(store: Store) -> Store:
    return store.fork()


def test_the_engine_finds_the_decoys_conflict_without_being_told(fresh: Store) -> None:
    info = describe_candidate(fresh, URIRef(decoy_iri()))
    assert info["proposed_by"] == "Orbital Lens Works, Inc." and info["origin"] == "synthetic"
    [conflict] = info["conflicts"]
    assert "COO-001" in conflict["reason"] and conflict["fact"].endswith("/ownership/" + decoy_case()["patent_key"])


def test_a_clean_candidate_has_no_conflict(fresh: Store) -> None:
    clean = "https://w3id.org/gonogo/id/ownership/LEW-18605-2/candidate"
    assert describe_candidate(fresh, URIRef(clean))["conflicts"] == []


def test_the_decoy_cannot_produce_go_without_a_second_approver(fresh: Store) -> None:
    """The injected case INJ-045, replayed from its script."""
    script = decoy_case()["governance"]
    request = decoy_request()
    assert evaluate_now(fresh, request).verdict == decoy_case()["expected_verdict"] == "COUNSEL"

    first = apply_event(fresh, act(ANN, "approve_fact", candidate=decoy_iri()))
    assert first["route"] == script["after_first_approval"]["route"] == "pending_second_review"
    assert first["new_facts"] == [], "the submission adds no fact"
    assert first["policies"] == ["steward-submits-flagged-fact"]
    assert first["flags"]["conflicts"] and first["flags"]["upgrades"], "both flags fire on the decoy"
    assert evaluate_now(fresh, request).verdict == script["after_first_approval"]["verdict"] == "COUNSEL"

    for refused in script["refused"]:
        who = {"steward": refused["name"], "role": refused["role"]}
        params = {"candidate": decoy_iri()}
        with pytest.raises(ActionRejectedError):
            apply_event(fresh, act(who, refused["action"], **params))
        assert evaluate_now(fresh, request).verdict == "COUNSEL", refused

    second = apply_event(fresh, act(CY, "second_review", candidate=decoy_iri(), decision="approve"))
    assert second["route"] == "approved" and second["new_facts"]
    assert evaluate_now(fresh, request).verdict == script["after_second_review"]["verdict"] == "GO"


def test_the_approved_fact_names_both_approvers(fresh: Store) -> None:
    apply_event(fresh, act(ANN, "approve_fact", candidate=decoy_iri()))
    [new] = apply_event(fresh, act(CY, "second_review", candidate=decoy_iri()))["new_facts"]
    view = fresh.view([GRAPH_APPROVED])
    first, second = view.value(URIRef(new), GNG.approvedBy), view.value(URIRef(new), GNG.secondApprovedBy)
    assert str(first).endswith("/steward/ann-steward") and str(second).endswith("/steward/cy-counsel")
    assert str(view.value(URIRef(new), GNG.proposedBy)).endswith("/licensee/LIC-001")
    assert (URIRef(new), RDF.type, GNG.OwnershipRecord) in view


def test_counsel_can_deny_and_the_verdict_never_moves(fresh: Store) -> None:
    request = decoy_request()
    apply_event(fresh, act(ANN, "approve_fact", candidate=decoy_iri()))
    out = apply_event(fresh, act(CY, "second_review", candidate=decoy_iri(), decision="deny"))
    assert out["route"] == "denied" and evaluate_now(fresh, request).verdict == "COUNSEL"
    with pytest.raises(ActionRejectedError, match="already has a decision"):
        apply_event(fresh, act(ANN, "approve_fact", candidate=decoy_iri()))


def test_a_second_review_needs_something_waiting(fresh: Store) -> None:
    with pytest.raises(ActionRejectedError, match="waits for counsel"):
        apply_event(fresh, act(CY, "second_review", candidate=decoy_iri()))


def test_the_same_approval_cannot_be_submitted_twice(fresh: Store) -> None:
    apply_event(fresh, act(ANN, "approve_fact", candidate=decoy_iri()))
    with pytest.raises(ActionRejectedError, match="already waits"):
        apply_event(fresh, act({"steward": "Ben Steward", "role": "steward"}, "approve_fact", candidate=decoy_iri()))


def test_the_refusal_says_why(fresh: Store) -> None:
    with pytest.raises(ActionRejectedError, match="Counsel reviews an approval"):
        apply_event(fresh, act(CY, "approve_fact", candidate=decoy_iri()))
    with pytest.raises(ActionRejectedError, match="licensing manager role may not"):
        apply_event(fresh, act({"steward": "Pat", "role": "licensing_manager"}, "approve_fact", candidate=decoy_iri()))
    with pytest.raises(ActionRejectedError, match="Unknown role"):
        apply_event(fresh, act({"steward": "Pat", "role": "superuser"}, "approve_fact", candidate=decoy_iri()))


# ---- a steward cannot approve what the steward proposed ---------------------------------------------------


def propose_export(who: dict[str, str]) -> dict[str, Any]:
    return act(who, "propose_fact", kind="export", patent_key="LAR-17317-2", classification="unrestricted")


def test_a_steward_cannot_approve_a_fact_they_proposed(fresh: Store) -> None:
    proposed = apply_event(fresh, propose_export(ANN))["candidate"]
    assert describe_candidate(fresh, URIRef(proposed))["proposed_by"] == "Ann Steward"
    with pytest.raises(ActionRejectedError, match="You proposed this fact"):
        apply_event(fresh, act(ANN, "approve_fact", candidate=proposed))
    request = to_request(requests_by_id()["REQ-0025"])  # the question that waits on R5 for this patent
    assert evaluate_now(fresh, request).verdict == "NO DATA"
    done = apply_event(fresh, act({"steward": "Ben Steward", "role": "steward"}, "approve_fact", candidate=proposed))
    assert done["route"] == "immediate" and evaluate_now(fresh, request).verdict == "GO"


def test_only_a_steward_or_licensing_manager_proposes(fresh: Store) -> None:
    with pytest.raises(ActionRejectedError, match="role may not do ProposeFact"):
        apply_event(fresh, propose_export({"steward": "Fin", "role": "finance_analyst"}))


def test_a_proposal_is_a_candidate_and_changes_no_verdict(fresh: Store) -> None:
    request = to_request(requests_by_id()["REQ-0025"])
    before = evaluate_now(fresh, request)
    apply_event(fresh, propose_export(ANN))
    assert evaluate_now(fresh, request).signature == before.signature


# ---- identity links take the same path ----------------------------------------------------------------------

GENH2 = (
    "Can GenH2 Corporation get a non-exclusive license to US Patent 10,431,355 for energy generation "
    "in the USA for five years starting January 1, 2027?"
)


def test_a_link_that_moves_a_session_verdict_to_go_waits_for_counsel(fresh: Store) -> None:
    from agent.parser import Vocabulary, parse
    from er.resolver import index_parties, propose_links

    pair = next(p for p in propose_links(index_parties(fresh)) if p["a"]["name"].startswith("GenH2"))
    link = act(ANN, "link_identity", a=pair["a"]["iri"], b=pair["b"]["iri"], score=pair["score"])
    link["params"]["requests"] = [{"text": GENH2}]

    request = parse(GENH2, Vocabulary.from_store(fresh)).to_request()
    assert evaluate_now(fresh, request).verdict == "COUNSEL"

    held = apply_event(fresh, link)
    assert held["route"] == "pending_second_review" and held["flags"]["upgrades"]
    assert not any(u.startswith("INSERT") and "sameAs" in u for u in to_sparql_update(fresh))
    assert evaluate_now(fresh, parse(GENH2, Vocabulary.from_store(fresh)).to_request()).verdict == "COUNSEL"

    out = apply_event(fresh, act(CY, "second_review", a=pair["a"]["iri"], b=pair["b"]["iri"]))
    assert out["route"] == "approved"
    assert evaluate_now(fresh, parse(GENH2, Vocabulary.from_store(fresh)).to_request()).verdict == "GO"


def test_a_link_that_moves_no_verdict_to_go_needs_no_second_reviewer(fresh: Store) -> None:
    from er.resolver import index_parties, propose_links

    pair = next(p for p in propose_links(index_parties(fresh)) if p["a"]["name"].startswith("GenH2"))
    out = apply_event(fresh, act(ANN, "link_identity", a=pair["a"]["iri"], b=pair["b"]["iri"], score=pair["score"]))
    assert out["route"] == "immediate" and out["policies"] == ["steward-approves-clean-fact"]


# ---- the event log ---------------------------------------------------------------------------------------------


def test_a_log_with_a_held_approval_replays_to_the_same_world(store: Store) -> None:
    live = store.fork()
    apply_event(live, act(ANN, "approve_fact", candidate=decoy_iri()))
    apply_event(live, act(CY, "second_review", candidate=decoy_iri()))
    again = replay(store, live.events)
    assert again.events == live.events and again.decided == live.decided
    assert evaluate_now(again, decoy_request()).signature == evaluate_now(live, decoy_request()).signature


def test_a_log_that_skips_the_hold_is_rejected_on_replay(store: Store) -> None:
    live = store.fork()
    apply_event(live, act(ANN, "approve_fact", candidate=decoy_iri()))
    forged = [{**live.events[0], "route": "immediate"}]
    with pytest.raises(ActionRejectedError, match="The log was changed"):
        replay(store, forged)


def test_a_held_approval_leaves_the_royalty_graph_and_every_verdict_alone(fresh: Store) -> None:
    from rules.book import requests_for_patents

    patent = decoy_case()["patent_key"]
    before = {r.field: evaluate_now(fresh, r).signature for r in requests_for_patents({patent})}
    apply_event(fresh, act(ANN, "approve_fact", candidate=decoy_iri()))
    assert {r.field: evaluate_now(fresh, r).signature for r in requests_for_patents({patent})} == before
