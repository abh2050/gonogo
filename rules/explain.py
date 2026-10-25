"""A deterministic explanation of a verdict, built from the findings alone, plus a diff between two decisions.

No language model writes this text. Gate 3 adds an optional model-written narrative that a citation checker
must pass, and the card falls back to this text when the check fails.
"""

from __future__ import annotations

from typing import Any

VERDICT_TEXT = {
    "GO": "Every applicable rule passed with complete evidence.",
    "NO GO": "A rule found a conflict.",
    "HOLD": "A Federal Register objection window is still open.",
    "COUNSEL": "At least one rule needs legal judgment.",
    "NO DATA": "A fact that a rule needs is missing, and GoNoGo does not treat a gap as proof.",
}


def explain(record: Any, policy: dict[str, Any]) -> list[str]:
    """One sentence for the verdict, then one for each rule that mattered, in precedence order."""
    findings = {f["rule"]: f for f in record.findings}
    lines = [f"{record.verdict}. {VERDICT_TEXT[record.verdict]}"]
    order = [e["status"] for e in policy["precedence"]]
    seen: set[str] = set()
    for status in order:
        for rule, f in findings.items():
            if f["status"] == status:
                lines.append(f"{rule} {f['name']} returned {status}: {f['summary']}")
                seen.add(rule)
    for rule, f in findings.items():
        if rule not in seen and f["status"] == "PASS":
            lines.append(f"{rule} {f['name']} passed: {f['summary']}")
        elif rule not in seen and f["status"] == "NOT_APPLICABLE":
            lines.append(f"{rule} {f['name']} does not apply: {f['summary']}")
    return lines


def diff(before: Any, after: Any) -> dict[str, Any]:
    """What changed between two decisions on the same request, and why."""
    changes: list[dict[str, Any]] = []
    for rule in (f["rule"] for f in after.findings):
        a, b = before.finding(rule), after.finding(rule)
        old_facts = {x["iri"]: x for x in a["facts"]}
        new_facts = {x["iri"]: x for x in b["facts"]}
        added = [new_facts[i] for i in new_facts if i not in old_facts]
        removed = [old_facts[i] for i in old_facts if i not in new_facts]
        if a["status"] == b["status"] and not added and not removed and a["summary"] == b["summary"]:
            continue
        if added:
            reason = "New evidence: " + "; ".join(
                f"{x['label']}" + (f", approved by {x['approved_by']}" if x.get("approved_by") else "") for x in added
            )
        elif removed:
            reason = "Evidence no longer counts: " + "; ".join(x["label"] for x in removed)
        else:
            reason = "The same evidence now leads to a different conclusion."
        changes.append(
            {
                "rule": rule,
                "name": b["name"],
                "from": a["status"],
                "to": b["status"],
                "reason": reason,
                "summary_before": a["summary"],
                "summary_after": b["summary"],
                "added_facts": [x["iri"] for x in added],
                "removed_facts": [x["iri"] for x in removed],
            }
        )
    return {
        "request": after.request,
        "verdict_before": before.verdict,
        "verdict_after": after.verdict,
        "verdict_changed": before.verdict != after.verdict,
        "changes": changes,
    }
