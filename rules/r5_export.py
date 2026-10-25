"""R5. May the licensee's country receive this technology?

The rule returns PASS when the technology is unrestricted or the licensee's country is permitted, REVIEW when
the technology is restricted and the country is not permitted, and UNKNOWN when no classification exists or
the licensee's country is not known.
"""

from __future__ import annotations

from rules.context import Context, text, value
from rules.model import Finding, Status

RULE = "R5"
NAME = "Export control"
VERSION = "1.0.0"


def evaluate(ctx: Context) -> Finding:
    f = Finding(RULE, NAME, Status.UNKNOWN, "", VERSION)
    rows = ctx.select("r5_export")
    if not rows:
        f.summary = "No export classification is on record for this patent."
        f.missing.append("export classification")
        return f

    latest = str(rows[0]["export"])
    mine = [r for r in rows if str(r["export"]) == latest]
    kind = str(mine[0]["kind"])
    permitted = sorted({str(r["code"]) for r in mine if "code" in r})
    ctx.note_fact(latest, "Export classification", f"{kind.capitalize()} export classification")
    f.details = {"classification": kind, "permitted": permitted, "licensee_country": ctx.request.licensee_country}
    f.facts = ctx.collect([latest])
    _ = value, text

    if kind == "unrestricted":
        f.status = Status.PASS
        f.summary = "The technology carries no export restriction."
    elif ctx.request.licensee_country is None:
        f.summary = (
            f"The technology is export-restricted to {', '.join(permitted)}, and the licensee's country is not known."
        )
        f.missing.append("licensee country")
    elif ctx.request.licensee_country in permitted:
        f.status = Status.PASS
        f.summary = (
            f"The technology is export-restricted, and the licensee's country "
            f"({ctx.request.licensee_country}) is permitted."
        )
    else:
        f.status = Status.REVIEW
        f.summary = (
            f"The technology is export-restricted to {', '.join(permitted)}, and the licensee's country "
            f"({ctx.request.licensee_country}) is not on the list. Counsel must decide whether the export is lawful."
        )
    return f
