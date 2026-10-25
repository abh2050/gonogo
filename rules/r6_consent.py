"""R6. Has every co-owner consented?

A complete ownership record that lists no co-owners is an explicit negative fact, and it returns PASS. A
complete record whose co-owners have all consented returns PASS. A listed co-owner without a consent record
returns REVIEW, even when the record is incomplete, because a known gap is more useful than an unknown one.
A missing or incomplete record returns UNKNOWN. The rule never reads "no record" as "no co-owners".
"""

from __future__ import annotations

from rules.context import Context, local, text, value
from rules.model import Finding, Status

RULE = "R6"
NAME = "Co-owner consent"
VERSION = "1.0.0"


def evaluate(ctx: Context) -> Finding:
    f = Finding(RULE, NAME, Status.UNKNOWN, "", VERSION)
    rows = ctx.select("r6_ownership")
    if not rows:
        f.summary = (
            "No ownership record exists for this patent. A missing record does not show that NASA owns it alone."
        )
        f.missing.append("ownership record")
        return f

    record = str(rows[0]["record"])
    mine = [r for r in rows if str(r["record"]) == record]
    complete = bool(value(mine[0], "complete"))
    owners = {str(r["coOwner"]): text(r, "name") or local(text(r, "coOwner")) for r in mine if "coOwner" in r}
    consents = ctx.select("r6_consent")
    consented = {str(r["coOwner"]): str(r["consent"]) for r in consents}
    lacking = {o: n for o, n in owners.items() if o not in consented}

    ctx.note_fact(
        record,
        "Ownership record",
        f"Ownership record: {'complete' if complete else 'incomplete'}, {len(owners)} co-owner(s) listed",
    )
    iris = [record]
    for o in owners:
        if o in consented:
            ctx.note_fact(consented[o], "Consent record", f"Consent from {owners[o]}")
            iris.append(consented[o])
    f.details = {
        "complete": complete,
        "co_owners": sorted(owners.values()),
        "without_consent": sorted(lacking.values()),
    }

    if lacking:
        f.status = Status.REVIEW
        f.summary = f"{', '.join(sorted(lacking.values()))} co-own the patent and no consent is on record."
        if not complete:
            f.notes.append("The ownership record is also incomplete, so more co-owners may exist.")
    elif not complete:
        f.summary = "The ownership record does not claim to list every co-owner, so GoNoGo cannot rule out others."
        f.missing.append("complete ownership record")
    elif owners:
        f.status = Status.PASS
        f.summary = f"Every listed co-owner ({', '.join(sorted(owners.values()))}) has consented."
    else:
        f.status = Status.PASS
        f.summary = "A complete ownership record lists no co-owners."
    f.facts = ctx.collect(iris)
    return f
