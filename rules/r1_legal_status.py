"""R1. Is the patent in force on the requested start date?

The rule prefers the USPTO record. It returns FAIL when the USPTO shows the patent lapsed, ended, or never
issued, or when any source shows an expiration before the start date. It returns PASS when the USPTO shows
the patent in force through the start date. A date that GoNoGo computed from a filing date is labeled
derived, and it may produce PASS.

When the only evidence is the NASA Patents snapshot, a stated expiration in the future cannot produce PASS.
The snapshot is about ten years old and cannot show a lapse for unpaid maintenance fees, and the data
showed that 69 percent of the patents it calls in force had lapsed. The rule returns UNKNOWN instead.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from rules.common import add_years, day
from rules.context import Context, local, text, value
from rules.model import Finding, Status

RULE = "R1"
NAME = "Patent in force"
VERSION = "1.1.0"
USPTO = "/registry/uspto/"
NASA = "/registry/nasa-patents"


def _label(row: dict[str, Any], who: str) -> str:
    return f"{who} legal status, recorded {str(value(row, 'recorded'))[:10]}"


def evaluate(ctx: Context) -> Finding:
    start = day(ctx.request.start)
    rows = ctx.select("r1_status")
    uspto = next((r for r in rows if USPTO in (text(r, "source") or "")), None)
    nasa = next((r for r in rows if NASA in (text(r, "source") or "")), None)
    f = Finding(RULE, NAME, Status.UNKNOWN, "", VERSION)
    used: list[str] = []

    for r, who in ((uspto, "USPTO"), (nasa, "NASA snapshot")):
        if r is not None:
            iri = str(r["status"])
            ctx.note_fact(iri, f"{who} legal status", _label(r, who))
            used.append(iri)

    if uspto is not None:
        state = local(text(uspto, "stateIri"))
        status_text = (text(uspto, "stateText") or "").strip()
        exp: date | None = value(uspto, "expiration")
        lapse: date | None = value(uspto, "lapse")
        f.details = {
            "source": "USPTO",
            "state": state,
            "expiration": str(exp) if exp else None,
            "expiration_derived": bool(value(uspto, "derived")),
            "basis": text(uspto, "basis"),
        }
        if state in ("abandoned", "not-granted"):
            f.status = Status.FAIL
            f.summary = f"The USPTO shows that no patent issued: {status_text or state}."
        elif state == "lapsed" and (lapse is None or lapse <= start):
            f.status = Status.FAIL
            when = f" on {lapse}" if lapse else ""
            f.summary = f"The USPTO recorded the patent as expired for unpaid maintenance fees{when}."
            nasa_exp = value(nasa, "expiration") if nasa is not None else None
            if nasa_exp:
                f.notes.append(
                    f"The NASA Patents snapshot still lists an expiration date of {nasa_exp}. "
                    "The USPTO record is newer and the snapshot cannot show a lapse."
                )
        elif state in ("in-force", "term-ended", "lapsed"):
            if exp is None:
                f.status = Status.UNKNOWN
                f.summary = (
                    "The USPTO shows the patent granted but supplies no dates from which to compute an expiration."
                )
                f.missing.append("expiration date")
            elif exp < start:
                f.status = Status.FAIL
                f.summary = f"The patent's term ended on {exp}, before the requested start of {start}."
            else:
                f.status = Status.PASS
                f.summary = (
                    f"The USPTO shows the patent in force. Its term runs to {exp}, "
                    f"after the requested start of {start}."
                )
                if value(uspto, "derived"):
                    f.notes.append(f"The expiration date is derived: {text(uspto, 'basis')}.")
                if value(uspto, "disclaimer"):
                    f.notes.append(
                        "A terminal disclaimer is on record, so the term may end sooner than the derived date."
                    )
                if value(uspto, "reinstated"):
                    f.notes.append(
                        f"The patent lapsed on {lapse} and was reinstated on {value(uspto, 'reinstated')}. "
                        "Third parties may hold intervening rights for acts in that window."
                    )
                if day(ctx.request.end) > exp:
                    f.notes.append(f"The patent expires on {exp}, before the requested term ends on {ctx.request.end}.")
        else:
            f.summary = f"The USPTO legal state {state!r} is not one the rule understands."
            f.missing.append("a recognized legal state")
        f.facts = ctx.collect(used)
        return f

    if nasa is not None:
        state = local(text(nasa, "stateIri"))
        exp = value(nasa, "expiration")
        f.details = {
            "source": "NASA snapshot",
            "state": state or "issued",
            "expiration": str(exp) if exp else None,
            "expiration_derived": False,
        }
        if state == "application":
            f.summary = (
                "Only the NASA Patents snapshot lists this patent, as an application. The snapshot is about "
                "ten years old and the USPTO has no record, so GoNoGo cannot tell whether a patent issued."
            )
            f.missing.append("USPTO legal status")
            f.facts = ctx.collect(used)
            return f
        if exp is not None and exp < start:
            f.status = Status.FAIL
            f.summary = (
                f"The NASA Patents snapshot lists an expiration date of {exp}, before the requested start of {start}."
            )
            f.facts = ctx.collect(used)
            return f
        if exp is not None:
            f.summary = (
                f"Only the NASA Patents snapshot covers this patent. It lists an expiration date of {exp}, but the "
                "snapshot cannot show a lapse for unpaid maintenance fees and the USPTO has no record."
            )
            f.missing.append("USPTO legal status")
            f.facts = ctx.collect(used)
            return f

    filing = ctx.select("r1_filing")
    if filing:
        fr = filing[0]
        iri = str(fr["filing"])
        filed: date = value(fr, "filingDate")
        derived = add_years(filed, 20)
        ctx.note_fact(iri, "Filing record", f"Filing date {filed}")
        used.append(iri)
        f.details = {
            "source": "filing date",
            "expiration": str(derived),
            "expiration_derived": True,
            "basis": "filing date + 20 years",
        }
        f.notes.append(
            f"The expiration date is derived: filing date {filed} plus 20 years. The derivation ignores term "
            "adjustments and lapses for unpaid maintenance fees."
        )
        if derived < start:
            f.status = Status.FAIL
            f.summary = f"The derived expiration of {derived} is before the requested start of {start}."
        else:
            f.status = Status.PASS
            f.summary = f"The derived expiration of {derived} is after the requested start of {start}."
        f.facts = ctx.collect(used)
        return f

    f.summary = "No registry supplies a legal state, an expiration date, or a filing date for this patent."
    f.missing += ["legal status", "expiration date", "filing date"]
    f.facts = ctx.collect(used)
    return f
