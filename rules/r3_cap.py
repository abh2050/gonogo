"""R3. Would a co-exclusive request exceed the cap that existing agreements state?

The rule counts the other licensees that already hold overlapping co-exclusive grants. It returns FAIL when the
request would take the total above the smallest stated cap, PASS when it stays within the cap, and UNKNOWN
when no cap is recorded. Other exclusivity types make the rule not applicable.
"""

from __future__ import annotations

from rules.context import Context, local, text, value
from rules.model import Finding, Status, exclusivity_slug
from rules.r2_exclusivity import describe

RULE = "R3"
NAME = "Co-exclusive cap"
VERSION = "1.0.0"


def evaluate(ctx: Context) -> Finding:
    f = Finding(RULE, NAME, Status.NOT_APPLICABLE, "", VERSION)
    if exclusivity_slug(ctx.request.exclusivity) != "co-exclusive":
        f.summary = "The request is not co-exclusive, so no cap applies."
        return f

    mine = set(ctx.licensee_set)
    co = [r for r in ctx.executed_overlap() if local(text(r, "exclusivity")) == "co-exclusive"]
    others = [r for r in co if text(r, "licensee") not in mine]
    holders = {text(r, "licensee") or text(r, "written") for r in others}
    caps = [int(value(r, "cap")) for r in co if "cap" in r]
    f.details = {"holders": len(holders), "caps": sorted(set(caps))}
    for r in co:
        ctx.note_fact(str(r["grant"]), "Executed grant", describe(r))
    iris = [str(r["grant"]) for r in co]

    if not co:
        f.status = Status.UNKNOWN
        f.summary = "No existing co-exclusive agreement overlaps the request, so no agreement states a cap."
        f.missing.append("co-exclusive cap")
    elif not caps:
        f.status = Status.UNKNOWN
        f.summary = (
            f"{len(holders)} licensee(s) hold overlapping co-exclusive grants, but none of the agreements states a cap."
        )
        f.missing.append("co-exclusive cap")
    else:
        cap = min(caps)
        f.details["cap"] = cap
        if len(holders) + 1 > cap:
            f.status = Status.FAIL
            f.summary = (
                f"{len(holders)} other licensee(s) already hold overlapping co-exclusive grants and the cap is "
                f"{cap}. One more would exceed it."
            )
        else:
            f.status = Status.PASS
            f.summary = (
                f"{len(holders)} other licensee(s) hold overlapping co-exclusive grants and the cap is {cap}, "
                "so the request stays within it."
            )
    f.facts = ctx.collect(iris)
    f.clauses = ctx.clauses_for(iris, {"cap", "grant"})
    return f
