"""Evaluate the Cedar policies in authz/policies/ for one request.

The same policy text goes to Amazon Verified Permissions in the AWS deployment. This module is the in-process
evaluator that the rule engine, the demo API, and the tests use, so a policy change is tested before it ships.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import cedarpy

ROOT = Path(__file__).resolve().parent
POLICY_FILE = ROOT / "policies" / "gonogo.cedar"
SCHEMA_FILE = ROOT / "gonogo.cedarschema.json"

ROLES = ("licensing_manager", "steward", "counsel", "ontology_owner", "finance_analyst", "auditor")
GRAPHS = ("release", "approved", "candidate", "royalty")

_ID = re.compile(r'@id\("([^"]+)"\)')
_REASON = re.compile(r'@reason\("([^"]+)"\)')


class UnknownRoleError(ValueError):
    pass


class PolicyError(RuntimeError):
    """The request or the policies are malformed. A denial must mean 'not allowed', never 'could not ask'."""


@dataclass(frozen=True)
class Principal:
    name: str
    role: str

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise UnknownRoleError(f"Unknown role: {self.role!r}")
        if not self.name.strip():
            raise ValueError("A principal needs a name.")


@dataclass
class Decision:
    allowed: bool
    action: str
    policies: list[str] = field(default_factory=list)  # ids of the policies that decided
    reasons: list[str] = field(default_factory=list)  # sentences for a person
    errors: list[str] = field(default_factory=list)


@cache
def policy_text() -> str:
    return POLICY_FILE.read_text()


@cache
def _policy_meta() -> list[tuple[str, str | None]]:
    """(id, reason) for each policy, in file order. Cedar names its policies policy0, policy1, and so on."""
    out: list[tuple[str, str | None]] = []
    for block in re.split(r"\n(?=@id\()", "\n" + policy_text()):
        m = _ID.search(block)
        if m:
            r = _REASON.search(block)
            out.append((m.group(1), r.group(1) if r else None))
    return out


@cache
def schema() -> dict[str, Any]:
    import json

    return dict(json.loads(SCHEMA_FILE.read_text()))


def validate() -> list[str]:
    """Policy errors against the schema. An empty list means the policies are well formed."""
    result = cedarpy.validate_policies(policy_text(), schema())
    return [str(e) for e in result.errors] if not result.validation_passed else []


def _entities(principal: Principal, resource: tuple[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [
        {
            "uid": {"type": "User", "id": principal.name},
            "attrs": {"name": principal.name},
            "parents": [{"type": "Role", "id": principal.role}],
        },
        {"uid": {"type": "Role", "id": principal.role}, "attrs": {}, "parents": []},
        {"uid": {"type": resource[0], "id": resource[1]}, "attrs": {}, "parents": []},
    ]
    return out


def authorize(
    principal: Principal, action: str, resource: tuple[str, str], context: dict[str, Any] | None = None
) -> Decision:
    result = cedarpy.is_authorized(
        {
            "principal": {"type": "User", "id": principal.name},
            "action": {"type": "Action", "id": action},
            "resource": {"type": resource[0], "id": resource[1]},
            "context": context or {},
        },
        policy_text(),
        _entities(principal, resource),
        schema(),
    )
    if result.diagnostics.errors:
        raise PolicyError(f"Cedar could not evaluate {action}: {'; '.join(str(e) for e in result.diagnostics.errors)}")
    meta = _policy_meta()
    ids: list[str] = []
    for r in result.diagnostics.reasons:
        n = int(str(r).removeprefix("policy"))
        ids.append(meta[n][0])
    decision = Decision(bool(result.allowed), action, ids, [], [str(e) for e in result.diagnostics.errors])
    if not decision.allowed:
        decision.reasons = [meta[int(str(r).removeprefix("policy"))][1] or "" for r in result.diagnostics.reasons]
        decision.reasons = [r for r in decision.reasons if r]
        if not decision.reasons:
            decision.reasons = [f"The {principal.role.replace('_', ' ')} role may not do {action}."]
    return decision


def may_read_graph(principal: Principal, graph: str) -> bool:
    return authorize(principal, "ReadGraph", ("Graph", graph)).allowed


def readable_graphs(principal: Principal) -> list[str]:
    """The named graphs the query service may put in this principal's FROM clauses."""
    return [g for g in GRAPHS if may_read_graph(principal, g)]
