"""The Cedar policies: every role against every action, and the separation-of-duties rules."""

from __future__ import annotations

from typing import Any

import pytest

from authz import cedar
from authz.cedar import GRAPHS, ROLES, Principal

CLEAN = {"proposer": "feed", "firstApprover": "", "conflict": False, "upgradesToGo": False}
FLAGGED = CLEAN | {"conflict": True}
SECOND = CLEAN | {"firstApprover": "ann", "conflict": True}
RELEASE_OK = {"proposer": "owen", "gatePassed": True, "counselApproved": True}

RESOURCE_OF = {
    "ApproveFact": ("Candidate", "c"),
    "LinkIdentity": ("IdentityPair", "p"),
    "SubmitForSecondReview": ("Candidate", "c"),
    "SecondReview": ("Candidate", "c"),
}

# action -> (resource, context, the roles that may do it). Every schema action appears here, so adding an
# action without deciding who may do it fails test_the_matrix_covers_every_action.
MATRIX: dict[str, tuple[tuple[str, str], dict[str, Any] | None, set[str]]] = {
    "AskClearance": (("Request", "r"), None, {"licensing_manager", "steward", "counsel"}),
    "ViewDecision": (("Decision", "d"), None, {"licensing_manager", "steward", "counsel", "auditor"}),
    "RerunDecision": (("Decision", "d"), None, {"licensing_manager", "steward", "counsel", "auditor"}),
    "ReadGraph": (("Graph", "release"), None, {"licensing_manager", "steward", "counsel", "ontology_owner"}),
    "ReadRoyaltyTable": (("Decision", "d"), None, {"finance_analyst", "counsel"}),
    "ReadReleaseHistory": (("Release", "x"), None, {"auditor", "ontology_owner", "counsel"}),
    "OverrideVerdict": (("Decision", "d"), None, {"counsel"}),
    "ProposeFact": (("Candidate", "c"), None, {"steward", "licensing_manager"}),
    "RejectFact": (("Candidate", "c"), None, {"steward", "counsel"}),
    "RejectLink": (("IdentityPair", "p"), None, {"steward", "counsel"}),
    "ApproveFact": (("Candidate", "c"), CLEAN, {"steward"}),
    "LinkIdentity": (("IdentityPair", "p"), CLEAN, {"steward"}),
    "SubmitForSecondReview": (("Candidate", "c"), FLAGGED, {"steward"}),
    "SecondReview": (("Candidate", "c"), SECOND, {"counsel"}),
    "ProposeRelease": (("Release", "x"), None, {"ontology_owner"}),
    "ApproveImpactReport": (("Release", "x"), RELEASE_OK, {"counsel", "ontology_owner"}),
    "PublishRelease": (("Release", "x"), RELEASE_OK, {"ontology_owner"}),
}


def can(role: str, action: str, resource: tuple[str, str], context: dict[str, Any] | None, name: str = "pat") -> bool:
    return cedar.authorize(Principal(name, role), action, resource, context).allowed


def test_the_policies_validate_against_the_schema() -> None:
    assert cedar.validate() == []


def test_the_matrix_covers_every_action() -> None:
    assert set(MATRIX) == set(cedar.schema()[""]["actions"])


@pytest.mark.parametrize("action", sorted(MATRIX))
def test_each_action_is_open_to_exactly_the_roles_listed(action: str) -> None:
    resource, context, allowed = MATRIX[action]
    got = {role for role in ROLES if can(role, action, resource, context)}
    assert got == allowed, f"{action}: {sorted(got ^ allowed)}"


@pytest.mark.parametrize(
    ("graph", "roles"),
    [
        ("release", {"licensing_manager", "steward", "counsel", "ontology_owner"}),
        ("approved", {"licensing_manager", "steward", "counsel", "ontology_owner"}),
        ("candidate", {"steward", "counsel"}),
        ("royalty", {"counsel"}),
    ],
)
def test_each_graph_is_readable_by_exactly_the_roles_listed(graph: str, roles: set[str]) -> None:
    assert {r for r in ROLES if can(r, "ReadGraph", ("Graph", graph), None)} == roles


def test_nobody_but_counsel_reads_royalty_terms_from_the_graph_and_finance_reads_none() -> None:
    assert cedar.readable_graphs(Principal("f", "finance_analyst")) == []
    assert cedar.readable_graphs(Principal("a", "auditor")) == []
    assert "royalty" not in cedar.readable_graphs(Principal("m", "licensing_manager"))
    assert set(GRAPHS) == set(cedar.readable_graphs(Principal("c", "counsel")))


# ---- Separation of duties ---------------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["ApproveFact", "LinkIdentity"])
def test_a_flag_removes_a_stewards_right_to_approve_alone(action: str) -> None:
    resource = RESOURCE_OF[action]
    assert can("steward", action, resource, CLEAN)
    assert not can("steward", action, resource, CLEAN | {"conflict": True})
    assert not can("steward", action, resource, CLEAN | {"upgradesToGo": True})


def test_a_steward_may_submit_only_when_something_is_flagged() -> None:
    r = ("Candidate", "c")
    assert not can("steward", "SubmitForSecondReview", r, CLEAN)
    assert can("steward", "SubmitForSecondReview", r, CLEAN | {"conflict": True})
    assert can("steward", "SubmitForSecondReview", r, CLEAN | {"upgradesToGo": True})


@pytest.mark.parametrize(
    ("role", "action", "context"),
    [
        ("steward", "ApproveFact", CLEAN),
        ("steward", "LinkIdentity", CLEAN),
        ("steward", "SubmitForSecondReview", FLAGGED),
        ("counsel", "SecondReview", SECOND | {"firstApprover": "someone else"}),
    ],
)
def test_nobody_approves_a_fact_they_proposed(role: str, action: str, context: dict[str, Any]) -> None:
    resource = RESOURCE_OF.get(action, ("Candidate", "c"))
    assert can(role, action, resource, context, name="pat")
    d = cedar.authorize(Principal("pat", role), action, resource, context | {"proposer": "pat"})
    assert not d.allowed and "no-self-approval" in d.policies
    assert d.reasons == ["You proposed this fact, so someone else must approve it."]


def test_counsel_cannot_make_both_approvals() -> None:
    d = cedar.authorize(Principal("ann", "counsel"), "SecondReview", ("Candidate", "c"), SECOND)
    assert not d.allowed and d.policies == ["no-second-review-of-own-approval"]
    assert can("counsel", "SecondReview", ("Candidate", "c"), SECOND, name="cy")


def test_counsel_never_approves_a_fact_alone() -> None:
    for action in ("ApproveFact", "LinkIdentity"):
        d = cedar.authorize(Principal("cy", "counsel"), action, RESOURCE_OF[action], CLEAN)
        assert not d.allowed and "counsel-approves-only-after-a-steward" in d.policies


def test_a_licensing_manager_and_an_auditor_cannot_approve_anything() -> None:
    for role in ("licensing_manager", "auditor", "finance_analyst", "ontology_owner"):
        for action in ("ApproveFact", "LinkIdentity", "SubmitForSecondReview", "SecondReview"):
            assert not can(role, action, RESOURCE_OF.get(action, ("Candidate", "c")), SECOND), (role, action)


# ---- Releases -----------------------------------------------------------------------------------------------


def test_a_release_needs_a_passed_gate_and_counsels_approval() -> None:
    r = ("Release", "0.2.0")
    assert can("ontology_owner", "PublishRelease", r, RELEASE_OK)
    assert not can("ontology_owner", "PublishRelease", r, RELEASE_OK | {"counselApproved": False})
    assert not can("ontology_owner", "PublishRelease", r, RELEASE_OK | {"gatePassed": False})
    assert not can("counsel", "PublishRelease", r, RELEASE_OK)


def test_the_owner_who_proposed_a_release_cannot_approve_its_impact_report() -> None:
    r = ("Release", "0.2.0")
    d = cedar.authorize(Principal("owen", "ontology_owner"), "ApproveImpactReport", r, RELEASE_OK)
    assert not d.allowed and d.policies == ["no-self-approved-impact-report"]


# ---- Hygiene --------------------------------------------------------------------------------------------------


def test_an_unknown_role_or_blank_name_is_refused_before_cedar_runs() -> None:
    with pytest.raises(cedar.UnknownRoleError):
        Principal("x", "superuser")
    with pytest.raises(ValueError):
        Principal("  ", "steward")


def test_a_malformed_request_raises_instead_of_looking_like_a_denial() -> None:
    with pytest.raises(cedar.PolicyError):
        cedar.authorize(Principal("ann", "steward"), "LinkIdentity", ("Candidate", "c"), CLEAN)
    with pytest.raises(cedar.PolicyError):
        cedar.authorize(Principal("ann", "steward"), "ApproveFact", ("Candidate", "c"), {"conflict": False})


def test_every_policy_has_a_unique_id() -> None:
    ids = [i for i, _ in cedar._policy_meta()]
    assert len(ids) == len(set(ids)) == cedar.policy_text().count("@id(")
