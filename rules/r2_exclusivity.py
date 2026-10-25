"""R2. Does an existing grant conflict with the request?

An exclusive request conflicts with any overlapping executed grant. Any other request conflicts with an
overlapping exclusive grant. Overlap is tested on field, territory, and term, and the field and territory
tests run in both directions along the hierarchy: the grant covers the request, or the request covers the
grant. A conflict returns FAIL. An overlap with another party's proposed grant needs a lawyer, so it returns
REVIEW. No overlap returns PASS.
"""

from __future__ import annotations

from typing import Any

from rules.context import Context, local, text, value
from rules.model import Finding, Status, exclusivity_slug

RULE = "R2"
NAME = "Overlapping grants"
VERSION = "1.0.0"
GRANT_CLAUSES = {"grant", "field", "territory", "term"}


def describe(r: dict[str, Any]) -> str:
    who = text(r, "name") or text(r, "written") or "an unnamed licensee"
    return (
        f"{local(text(r, 'grant'))} ({local(text(r, 'exclusivity')).replace('-', ' ')}; {local(text(r, 'field'))}; "
        f"{local(text(r, 'territory'))}; {value(r, 'from')} to {value(r, 'to')}; {who})"
    )


def evaluate(ctx: Context) -> Finding:
    requested = exclusivity_slug(ctx.request.exclusivity)
    mine = set(ctx.licensee_set)
    f = Finding(RULE, NAME, Status.PASS, "", VERSION)

    executed = ctx.executed_overlap()
    conflicts = [r for r in executed if requested == "exclusive" or local(text(r, "exclusivity")) == "exclusive"]
    harmless = [r for r in executed if r not in conflicts]
    f.details = {
        "overlapping_executed": [local(text(r, "grant")) for r in executed],
        "conflicting": [local(text(r, "grant")) for r in conflicts],
    }

    review: dict[str, dict[str, Any]] = {}
    for r in ctx.select("r2_proposed_overlap"):
        if text(r, "licensee") in mine:
            continue  # the requester's own notice is R4's business
        if not (value(r, "fieldOverlap") and value(r, "territoryOverlap")):
            continue
        entry = review.setdefault(str(r["grant"]), {"row": r, "options": set(), "assignments": set()})
        if "exclusivity" in r:
            entry["options"].add(local(text(r, "exclusivity")))
        if "assignment" in r:
            entry["assignments"].add(str(r["assignment"]))
    flagged = {
        g: e for g, e in review.items() if requested == "exclusive" or not e["options"] or "exclusive" in e["options"]
    }

    for r in conflicts:
        ctx.note_fact(str(r["grant"]), "Executed grant", describe(r))
    for g, e in flagged.items():
        who = text(e["row"], "name") or "an unnamed party"
        ctx.note_fact(g, "Proposed grant", f"{local(g)} proposed to {who}")
        for a in e["assignments"]:
            ctx.note_fact(a, "Field of use assignment", f"{local(g)} limited to {local(text(e['row'], 'field'))}")

    if conflicts:
        f.status = Status.FAIL
        first = conflicts[0]
        extra = f" and {len(conflicts) - 1} more" if len(conflicts) > 1 else ""
        f.summary = (
            f"A {local(text(first, 'exclusivity')).replace('-', ' ')} grant overlaps the request: "
            f"{describe(first)}{extra}."
        )
    elif flagged:
        f.status = Status.REVIEW
        f.summary = (
            f"{len(flagged)} proposed grant(s) held by other parties may overlap the request. A notice of intent "
            "does not prove that a license exists, so counsel should decide."
        )
        for g, e in flagged.items():
            if "field" not in e["row"]:
                f.notes.append(f"{local(g)}: the notice states no field of use, so GoNoGo cannot rule out an overlap.")
            elif e["assignments"]:
                f.notes.append(f"{local(g)}: the field of use comes from an approved assignment, not from the notice.")
            f.details.setdefault("proposed", []).append(local(g))
    else:
        f.summary = "No executed grant conflicts with the request, and no other party's proposed grant overlaps it."
    if harmless:
        f.notes.append(
            f"{len(harmless)} overlapping grant(s) do not conflict with a {requested.replace('-', ' ')} request."
        )

    iris = (
        [str(r["grant"]) for r in conflicts]
        + list(flagged)
        + [a for e in flagged.values() for a in sorted(e["assignments"])]
    )
    f.facts = ctx.collect(iris)
    f.clauses = ctx.clauses_for(iris, GRANT_CLAUSES)
    return f
