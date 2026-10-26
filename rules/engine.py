"""Run every rule on a request, combine the statuses, and write the decision record.

The engine never skips a rule. A verdict of NO GO still shows the open windows and the missing evidence
that the other rules found, because the card shows every finding beneath the verdict.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import yaml

from gonogo.paths import ROOT
from kg.store import Reader, Store
from rules import r1_legal_status, r2_exclusivity, r3_cap, r4_notice, r5_export, r6_consent, r7_statutory
from rules.context import Context
from rules.decision import DecisionRecord, decision_id, findings_to_dicts, signature
from rules.explain import explain
from rules.model import Finding, Request
from rules.policy import combine, load_policy, policy_version

RULES: list[Any] = [r1_legal_status, r2_exclusivity, r3_cap, r4_notice, r5_export, r6_consent, r7_statutory]


def release_config() -> dict[str, Any]:
    with open(ROOT / "config" / "release.yaml") as f:
        cfg: dict[str, Any] = yaml.safe_load(f)
    return cfg


def rule_versions() -> dict[str, str]:
    return {m.RULE: m.VERSION for m in RULES}


def evaluate(
    store: Reader,
    request: Request,
    *,
    cutoff: str,
    as_of: str,
    user: str = "anonymous",
    role: str = "licensing_manager",
    parse: dict[str, Any] | None = None,
    resolve: Callable[[Reader, Request], Request] | None = None,
    events_applied: int = 0,
    release: str | None = None,
) -> DecisionRecord:
    """Evaluate a request as the system knew it at `cutoff`, on the evaluation date `as_of` (YYYY-MM-DD)."""
    if resolve is not None:
        request = resolve(store, request)
    ctx = Context(store, request, cutoff, as_of)
    ctx.validate()
    findings: list[Finding] = [rule.evaluate(ctx) for rule in RULES]
    verdict = combine([f.status for f in findings])
    release = release or str(release_config()["ontology_release"])
    dicts = findings_to_dicts(findings)
    canonical = request.canonical()
    record = DecisionRecord(
        id=decision_id(canonical, cutoff, as_of, release, policy_version()),
        request=canonical,
        user=user,
        role=role,
        release_version=release,
        rule_versions=rule_versions(),
        combiner_policy_version=policy_version(),
        evaluation_time=f"{as_of}T00:00:00Z",
        recording_cutoff=cutoff,
        findings=dicts,
        facts_read=sorted({fact["iri"] for f in dicts for fact in f["facts"]}),
        verdict=verdict,
        signature=signature(dicts),
        parse=parse,
        events_applied=events_applied,
    )
    record.explanation = explain(record, load_policy())
    return record


def evaluate_now(store: Store, request: Request, **kw: Any) -> DecisionRecord:
    """Evaluate on the demo clock: the cutoff is the time of the latest event, and the evaluation date is fixed."""
    from kg.actions import DEMO_NOW, now_for

    return evaluate(
        store,
        request,
        cutoff=now_for(store),
        as_of=DEMO_NOW.strftime("%Y-%m-%d"),
        events_applied=len(store.events),
        **kw,
    )


def rerun(store: Reader, record: DecisionRecord) -> DecisionRecord:
    """Evaluate a stored decision again from its stored context. The result must match the original."""
    request = Request(
        patent_key=record.request["patent_key"],
        exclusivity=record.request["exclusivity"],
        field=record.request["field"],
        territory=record.request["territory"],
        start=record.request["start"],
        end=record.request["end"],
        licensee_name=record.request.get("licensee_name"),
        licensee_ids=tuple(record.request.get("licensee_ids", [])),
        licensee_country=record.request.get("licensee_country"),
    )
    again = evaluate(
        store,
        request,
        cutoff=record.recording_cutoff,
        as_of=record.evaluation_time[:10],
        user=record.user,
        role=record.role,
        parse=record.parse,
        events_applied=record.events_applied,
        release=record.release_version,
    )
    return replace(again, override=record.override)
