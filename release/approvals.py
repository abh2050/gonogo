"""Counsel's approval of an impact report, and the publication that follows it.

An approval file binds each approval to the report's digest, so changing the report invalidates the approvals.
Cedar decides who may approve and who may publish (authz/policies/gonogo.cedar):

  - an owner or counsel may approve an impact report, but never the person who proposed the release;
  - an ontology owner may publish only when the regression gate passed and counsel has approved.

The identity of each approver is a name and a role that the pull request records. A real deployment takes both
from the signed-in user, as the AWS API does, or from the reviewer of a GitHub pull request.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from authz import cedar

ROOT = Path(__file__).resolve().parent.parent


class ReleaseRefusedError(PermissionError):
    pass


def path(version: str) -> Path:
    return ROOT / "release" / "approvals" / f"{version}.json"


def load(version: str) -> dict[str, Any]:
    p = path(version)
    return dict(json.loads(p.read_text())) if p.exists() else {"version": version, "approvals": []}


def counsel_approved(record: dict[str, Any], report_digest: str) -> bool:
    return any(
        a["role"] == "counsel" and a["report_digest"] == report_digest and a["name"] != record.get("proposer")
        for a in record["approvals"]
    )


def approve(version: str, report: dict[str, Any], who: cedar.Principal, reason: str, proposer: str) -> dict[str, Any]:
    record = load(version)
    record["proposer"] = proposer
    ctx = {
        "proposer": proposer,
        "gatePassed": bool(report["gate"]["regression_passed"]),
        "counselApproved": counsel_approved(record, report["digest"]),
    }
    decision = cedar.authorize(who, "ApproveImpactReport", ("Release", version), ctx)
    if not decision.allowed:
        raise ReleaseRefusedError(" ".join(decision.reasons))
    if len(reason.strip()) < 3:
        raise ReleaseRefusedError("A reason is required.")
    record["approvals"].append(
        {
            "name": who.name,
            "role": who.role,
            "reason": reason,
            "report_digest": report["digest"],
            "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    path(version).parent.mkdir(parents=True, exist_ok=True)
    path(version).write_text(json.dumps(record, indent=2) + "\n")
    return record


def publish(version: str, report: dict[str, Any], who: cedar.Principal, manifest: dict[str, Any]) -> dict[str, Any]:
    record = load(version)
    ctx = {
        "proposer": record.get("proposer", "unrecorded"),
        "gatePassed": bool(report["gate"]["regression_passed"]),
        "counselApproved": counsel_approved(record, report["digest"]),
    }
    decision = cedar.authorize(who, "PublishRelease", ("Release", version), ctx)
    if not decision.allowed:
        why = " ".join(decision.reasons)
        if not ctx["counselApproved"]:
            why += " Counsel has not approved this impact report."
        if not ctx["gatePassed"]:
            why += " The regression gate did not pass."
        raise ReleaseRefusedError(why)
    out = {
        "version": version,
        "bundle_digest": manifest["digest"],
        "report_digest": report["digest"],
        "published_by": who.name,
        "approvals": [{k: a[k] for k in ("name", "role", "at")} for a in record["approvals"]],
        "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    target = ROOT / "release" / "published" / f"{version}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2) + "\n")
    return out
