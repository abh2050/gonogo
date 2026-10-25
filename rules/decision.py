"""The decision record: everything needed to rerun a verdict and get the same answer."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from rules.model import Finding


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def signature(findings: list[dict[str, Any]]) -> str:
    """A hash of what each rule concluded and which facts it read. A rerun must reproduce it exactly."""
    core = [(f["rule"], f["status"], sorted(x["iri"] for x in f["facts"])) for f in findings]
    return hashlib.sha256(canonical_json(core).encode()).hexdigest()


@dataclass
class DecisionRecord:
    id: str
    request: dict[str, Any]
    user: str
    role: str
    release_version: str
    rule_versions: dict[str, str]
    combiner_policy_version: str
    evaluation_time: str
    recording_cutoff: str
    findings: list[dict[str, Any]]
    facts_read: list[str]
    verdict: str
    signature: str
    explanation: list[str] = field(default_factory=list)
    model_id: str | None = None
    parse: dict[str, Any] | None = None
    override: dict[str, Any] | None = None
    events_applied: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DecisionRecord:
        return cls(**d)

    def finding(self, rule: str) -> dict[str, Any]:
        return next(f for f in self.findings if f["rule"] == rule)

    def statuses(self) -> dict[str, str]:
        return {f["rule"]: f["status"] for f in self.findings}


def decision_id(request: dict[str, Any], cutoff: str, as_of: str, release: str, policy: str) -> str:
    digest = hashlib.sha256(canonical_json([request, cutoff, as_of, release, policy]).encode()).hexdigest()
    return f"dec-{digest[:12]}"


def findings_to_dicts(findings: list[Finding]) -> list[dict[str, Any]]:
    return [f.to_dict() for f in findings]
