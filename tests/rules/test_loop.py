"""The core loop: ask, read the verdict, approve a fact as a steward, rerun, and see why the verdict changed."""

from __future__ import annotations

from typing import Any

import pytest

from er.resolver import compare, index_parties, pair_id, propose_links
from kg.actions import (
    ActionRejectedError,
    apply_event,
    clock,
    pending_candidates,
    replay,
    to_sparql_update,
)
from kg.ns import GNG, GRAPH_APPROVED
from kg.store import Store
from rules.engine import evaluate, evaluate_now, rerun
from rules.explain import diff
from rules.model import Request
from tests.rules.helpers import AS_OF, CUTOFF, injected_cases, requests_by_id, to_request

STEWARD = "Demo Steward"


def approval_cases() -> list[dict[str, Any]]:
    return [c for c in injected_cases() if "after_approval" in c]


def steward_case() -> dict[str, Any]:
    return next(c for c in approval_cases() if c["type"] == "steward_rerun")


def candidate_iri(candidate_id: str) -> str:
    """CAND-OWN-<key> and CAND-EXP-<key> name the candidate nodes that kg/build.py writes."""
    kind, key = candidate_id.split("-", 2)[1:]
    return f"https://w3id.org/gonogo/id/{ {'OWN': 'ownership', 'EXP': 'export'}[kind] }/{key}/candidate"


def steward_candidate() -> str:
    return candidate_iri(steward_case()["after_approval"]["candidate_id"])


def approve(candidate: str, reason: str = "Assignment record checked against the USPTO.") -> dict[str, Any]:
    return {"action": "approve_fact", "steward": STEWARD, "reason": reason, "params": {"candidate": candidate}}


@pytest.fixture
def fresh(store: Store) -> Store:
    return store.fork()


@pytest.mark.parametrize("case", approval_cases(), ids=lambda c: c["case_id"])
def test_the_steward_loop_turns_no_data_into_go_and_explains_why(store: Store, case: dict[str, Any]) -> None:
    fresh = store.fork()
    request = to_request(requests_by_id()[case["request_id"]])
    before = evaluate_now(fresh, request)
    assert before.verdict == case["expected_verdict"] == "NO DATA"
    [rule] = [r for r, s in before.statuses().items() if s == "UNKNOWN"]

    candidate = candidate_iri(case["after_approval"]["candidate_id"])
    assert candidate in {str(c) for c in pending_candidates(fresh)}
    apply_event(fresh, approve(candidate))

    after = evaluate_now(fresh, request)
    assert after.verdict == case["after_approval"]["expected_verdict"] == "GO"
    assert after.statuses() == case["after_approval"]["expected_statuses"]

    d = diff(before, after)
    assert d["verdict_changed"] and d["verdict_before"] == "NO DATA" and d["verdict_after"] == "GO"
    [change] = d["changes"]
    assert change["rule"] == rule and (change["from"], change["to"]) == ("UNKNOWN", "PASS")
    assert STEWARD in change["reason"], "the explanation names the steward who approved the new evidence"
    assert change["added_facts"]


def test_an_approved_ownership_record_supersedes_the_incomplete_one(fresh: Store) -> None:
    result = apply_event(fresh, approve(steward_candidate()))
    assert result["superseded"] and result["superseded"][0].endswith("/ownership/" + steward_case_key())


def steward_case_key() -> str:
    return steward_case()["after_approval"]["candidate_id"].split("-", 2)[2]


def test_the_approved_fact_carries_full_provenance(fresh: Store) -> None:
    candidate = steward_candidate()
    new = apply_event(fresh, approve(str(candidate)))["new_facts"][0]
    rows = fresh.select(
        f"""PREFIX gng: <https://w3id.org/gonogo/ontology#> PREFIX prov: <http://www.w3.org/ns/prov#>
        SELECT ?approver ?action ?reason ?derived ?supersedes
FROM <{GRAPH_APPROVED}>
        WHERE {{ <{new}> gng:approvedBy ?approver ; prov:wasGeneratedBy ?action ; prov:wasDerivedFrom ?derived ;
                 gng:supersedes ?supersedes . ?action gng:actionReason ?reason }}"""
    )
    assert len(rows) == 1
    row = rows[0]
    assert str(row["approver"]).endswith("/steward/demo-steward")
    assert str(row["derived"]) == str(candidate)
    assert "USPTO" in str(row["reason"])


def test_a_past_decision_reproduces_after_later_approvals(fresh: Store) -> None:
    """The bitemporal guarantee: a stored cutoff hides everything recorded afterward, so the answer never changes."""
    case = steward_case()
    request = to_request(requests_by_id()[case["request_id"]])
    original = evaluate_now(fresh, request)
    apply_event(fresh, approve(steward_candidate()))
    assert evaluate_now(fresh, request).verdict == "GO"

    again = rerun(fresh, original)
    assert again.signature == original.signature
    assert again.verdict == original.verdict == "NO DATA"
    assert again.statuses() == original.statuses()
    assert again.facts_read == original.facts_read


def test_every_injected_decision_reproduces_from_its_stored_context(store: Store) -> None:
    requests = requests_by_id()
    for case in injected_cases():
        original = evaluate(
            store, to_request(requests[case["request_id"]]), cutoff=case["recording_cutoff"], as_of=AS_OF
        )
        stored = type(original).from_dict(original.to_dict())  # survives a round trip through JSON-shaped data
        assert rerun(store, stored).signature == original.signature, case["case_id"]


def test_an_event_log_replays_to_the_same_graph(store: Store) -> None:
    live = store.fork()
    apply_event(live, approve(steward_candidate()))
    parties = index_parties(live)
    links = propose_links(parties)
    first = links[0]
    apply_event(
        live,
        {
            "action": "link_identity",
            "steward": STEWARD,
            "reason": "Same company, same city.",
            "params": {"a": first["a"]["iri"], "b": first["b"]["iri"], "score": first["score"]},
        },
    )
    again = replay(store, live.events)
    assert [str(u) for u in to_sparql_update(again)] == [str(u) for u in to_sparql_update(live)]
    assert again.events == live.events


def test_a_candidate_can_be_decided_once_and_needs_a_steward_and_a_reason(fresh: Store) -> None:
    candidate = steward_candidate()
    with pytest.raises(ActionRejectedError, match="reason"):
        apply_event(fresh, {**approve(candidate), "reason": ""})
    with pytest.raises(ActionRejectedError, match="steward"):
        apply_event(fresh, {**approve(candidate), "steward": " "})
    apply_event(fresh, approve(candidate))
    with pytest.raises(ActionRejectedError, match="already"):
        apply_event(fresh, approve(candidate))
    assert candidate not in {str(c) for c in pending_candidates(fresh)}


def test_rejecting_a_candidate_leaves_the_verdict_alone(fresh: Store) -> None:
    case = steward_case()
    request = to_request(requests_by_id()[case["request_id"]])
    before = evaluate_now(fresh, request)
    apply_event(
        fresh,
        {
            "action": "reject_fact",
            "steward": STEWARD,
            "reason": "The source record is unreadable.",
            "params": {"candidate": steward_candidate()},
        },
    )
    after = evaluate_now(fresh, request)
    assert after.verdict == before.verdict == "NO DATA"
    assert diff(before, after)["changes"] == []


def test_an_unknown_candidate_is_refused(fresh: Store) -> None:
    with pytest.raises(ActionRejectedError, match="No candidate"):
        apply_event(fresh, approve("https://w3id.org/gonogo/id/ownership/NOPE/candidate"))


def test_the_event_clock_is_deterministic(fresh: Store) -> None:
    result = apply_event(fresh, approve(steward_candidate()))
    assert result["event"]["at"] == clock(1) == "2026-11-01T00:00:01Z"


# ---- entity resolution changes a rule's answer on real data ------------------------------------------------


def genh2_request() -> Request:
    """GenH2 Corporation asks for an exclusive license on a patent that a notice offered to 'GenH2'."""
    return Request(
        patent_key="US10431355",
        exclusivity="exclusive",
        field="energy-generation",
        territory="US",
        start="2027-01-01",
        end="2031-12-31",
        licensee_name="GenH2 Corporation",
        licensee_ids=("https://w3id.org/gonogo/id/licensee/real/genh2-corporation",),
        licensee_country=None,
    )


def test_a_steward_link_between_two_spellings_lets_r4_find_the_notice(fresh: Store) -> None:
    before = evaluate_now(fresh, genh2_request())
    assert before.statuses()["R4"] == "REVIEW", "no notice names 'GenH2 Corporation' for this patent"

    pair = next(
        p
        for p in propose_links(index_parties(fresh))
        if {p["a"]["name"], p["b"]["name"]} == {"GenH2", "GenH2 Corporation"}
    )
    assert pair["status"] == "match" and pair["id"] == pair_id(pair["a"]["iri"], pair["b"]["iri"])
    apply_event(
        fresh,
        {
            "action": "link_identity",
            "steward": STEWARD,
            "reason": "Both notices give the same Titusville address.",
            "params": {"a": pair["a"]["iri"], "b": pair["b"]["iri"], "score": pair["score"]},
        },
    )

    after = evaluate_now(fresh, genh2_request())
    assert after.statuses()["R4"] == "PASS", after.finding("R4")["summary"]
    change = next(c for c in diff(before, after)["changes"] if c["rule"] == "R4")
    assert (change["from"], change["to"]) == ("REVIEW", "PASS")
    assert "fr-2022-21473" in change["reason"], "the explanation points at the notice the link made visible"
    assert all(
        p["id"] != pair["id"]
        for p in propose_links(index_parties(fresh), linked={frozenset((pair["a"]["iri"], pair["b"]["iri"]))})
    )


def test_a_rejected_link_is_not_proposed_again(fresh: Store) -> None:
    pair = propose_links(index_parties(fresh))[0]
    apply_event(
        fresh,
        {
            "action": "reject_link",
            "steward": STEWARD,
            "reason": "Different companies.",
            "params": {"a": pair["a"]["iri"], "b": pair["b"]["iri"]},
        },
    )
    assert pair["id"] in fresh.decided
    with pytest.raises(ActionRejectedError, match="already"):
        apply_event(
            fresh,
            {
                "action": "reject_link",
                "steward": STEWARD,
                "reason": "Again.",
                "params": {"a": pair["a"]["iri"], "b": pair["b"]["iri"]},
            },
        )


def test_the_sparql_update_form_of_an_approval_is_valid_sparql(fresh: Store) -> None:
    from rdflib import Dataset

    apply_event(fresh, approve(steward_candidate()))
    updates = to_sparql_update(fresh)
    assert updates and all(u.startswith("INSERT DATA { GRAPH <") for u in updates)
    ds = Dataset()
    for u in updates:
        ds.update(u)
    assert len(ds) == sum(len(g) for g in fresh.overlay.values())


def test_candidate_facts_never_reach_the_rules_before_approval(fresh: Store) -> None:
    """The candidate graph is not in the rules' allowlist, so an unapproved fact cannot change a verdict."""
    case = steward_case()
    request = to_request(requests_by_id()[case["request_id"]])
    decision = evaluate(fresh, request, cutoff=CUTOFF, as_of=AS_OF)
    assert decision.verdict == "NO DATA"
    assert all("/candidate" not in iri for iri in decision.facts_read)
    assert str(GNG.IdentityLink)


def test_name_comparison_is_symmetric() -> None:
    assert compare("GenH2", "GenH2 Corporation").status == compare("GenH2 Corporation", "GenH2").status
