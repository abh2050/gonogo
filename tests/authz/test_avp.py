"""The namespaced copy of the policies that goes to Verified Permissions decides exactly as the local one does."""

from __future__ import annotations

import cedarpy
import pytest

from authz import avp, cedar, matrix
from authz.cedar import ROLES, Principal


def test_every_policy_is_carried_over_with_a_namespace_and_no_comments() -> None:
    statements = avp.statements()
    assert [i for i, _ in statements] == [i for i, _ in cedar._policy_meta()]
    for _, text in statements:
        assert "//" not in text
        assert "GoNoGo::Action::" in text or "forbid" in text
    assert 'Role::"steward"' not in avp.policy_text().replace('GoNoGo::Role::"steward"', "")


def test_the_namespaced_policies_validate_against_the_namespaced_schema() -> None:
    result = cedarpy.validate_policies(avp.policy_text(), avp.schema())
    assert result.validation_passed, [str(e) for e in result.errors]


def namespaced_decision(role: str, action: str, resource: tuple[str, str], ctx: dict | None) -> bool:  # type: ignore[type-arg]
    who = Principal("pat", role)
    ns = avp.NAMESPACE
    entities = [
        {
            "uid": {"type": f"{ns}::User", "id": "pat"},
            "attrs": {"name": "pat"},
            "parents": [{"type": f"{ns}::Role", "id": role}],
        },
        {"uid": {"type": f"{ns}::Role", "id": role}, "attrs": {}, "parents": []},
        {"uid": {"type": f"{ns}::{resource[0]}", "id": resource[1]}, "attrs": {}, "parents": []},
    ]
    out = cedarpy.is_authorized(
        {
            "principal": {"type": f"{ns}::User", "id": who.name},
            "action": {"type": f"{ns}::Action", "id": action},
            "resource": {"type": f"{ns}::{resource[0]}", "id": resource[1]},
            "context": ctx or {},
        },
        avp.policy_text(),
        entities,
        avp.schema(),
    )
    assert not out.diagnostics.errors, out.diagnostics.errors
    return bool(out.allowed)


@pytest.mark.parametrize("case", matrix.CASES, ids=lambda c: c[0])
def test_the_namespaced_policies_agree_with_the_local_ones_for_every_role(case: tuple) -> None:  # type: ignore[type-arg]
    _, action, resource, ctx = case
    for role in ROLES:
        local = cedar.authorize(Principal("pat", role), action, resource, ctx).allowed
        assert namespaced_decision(role, action, resource, ctx) == local, (action, role)


def test_the_cases_cover_every_action_in_the_schema() -> None:
    assert {c[1] for c in matrix.CASES} == set(cedar.schema()[""]["actions"])


def test_the_request_has_the_shape_verified_permissions_expects() -> None:
    req = avp.request(Principal("pat", "steward"), "ApproveFact", ("Candidate", "c"), matrix.CLEAN)
    assert req["principal"] == {"entityType": "GoNoGo::User", "entityId": "pat"}
    assert req["action"] == {"actionType": "GoNoGo::Action", "actionId": "ApproveFact"}
    assert req["context"]["contextMap"]["conflict"] == {"boolean": False}
    assert req["context"]["contextMap"]["proposer"] == {"string": "feed"}
