"""R4. Has the objection window closed on the requester's own notice of intent?

A request for exclusive, partially exclusive, or co-exclusive rights needs a published notice, and NASA
cannot grant the license until the objection window closes. The rule returns PENDING while a matching
window is open, PASS after every matching window has closed, and REVIEW when no notice names the requester.
A non-exclusive request makes the rule not applicable.
"""

from __future__ import annotations

from datetime import date

from rules.context import Context, local, text, value
from rules.model import Finding, Status

RULE = "R4"
NAME = "Notice window"
VERSION = "1.0.0"


def evaluate(ctx: Context) -> Finding:
    f = Finding(RULE, NAME, Status.NOT_APPLICABLE, "", VERSION)
    if not ctx.request.is_exclusive_family:
        f.summary = "A non-exclusive license needs no notice of intent."
        return f

    today = date.fromisoformat(ctx.as_of)
    mine = ctx.licensee_set
    rows = ctx.select("r4_notices", mine={"iris": mine}) if mine else []
    for r in rows:
        ctx.note_fact(
            str(r["grant"]), "Proposed grant", f"Notice {local(text(r, 'notice'))}, published {value(r, 'published')}"
        )
    iris = [str(r["grant"]) for r in rows]
    f.details = {"notices": [local(text(r, "notice")) for r in rows], "evaluated_on": str(today)}

    if not rows:
        f.status = Status.REVIEW
        f.summary = "No published notice of intent names the requester for this patent."
        f.missing.append("notice of intent")
        if not mine:
            f.notes.append("The requester's name did not resolve to a licensee in the graph, so no notice could match.")
    else:
        open_windows = [r for r in rows if "deadline" in r and value(r, "deadline") >= today]
        undated = [r for r in rows if "deadline" not in r]
        if open_windows:
            r = min(open_windows, key=lambda x: value(x, "deadline"))
            f.status = Status.PENDING
            f.summary = (
                f"The objection window on notice {local(text(r, 'notice'))} stays open until "
                f"{value(r, 'deadline')}. NASA cannot grant the license before it closes."
            )
            f.details["deadline"] = str(value(r, "deadline"))
        elif len(undated) == len(rows):
            f.status = Status.UNKNOWN
            f.summary = "The notice states no objection deadline, so GoNoGo cannot tell whether the window has closed."
            f.missing.append("objection deadline")
        else:
            latest = max((r for r in rows if "deadline" in r), key=lambda x: value(x, "deadline"))
            f.status = Status.PASS
            f.summary = (
                f"The objection window on notice {local(text(latest, 'notice'))} closed on {value(latest, 'deadline')}."
            )
            f.details["deadline"] = str(value(latest, "deadline"))
            if "basis" in latest:
                f.notes.append(f"The deadline is {text(latest, 'basis')}.")
    f.facts = ctx.collect(iris)
    f.clauses = ctx.clauses_for(iris, {"objection_deadline", "notice", "licensee", "exclusivity"})
    return f
