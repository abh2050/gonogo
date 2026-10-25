"""R7. Does 35 U.S.C. 209 need counsel's judgment?

Every exclusive, partially exclusive, or co-exclusive license must satisfy the statutory conditions in
35 U.S.C. 209, including the requirement that the licensee substantially manufacture products in the United
States. GoNoGo never decides those conditions. The rule returns REVIEW for each such request, so an exclusive
request can never reach GO. A non-exclusive request makes the rule not applicable.
"""

from __future__ import annotations

from rules.context import Context
from rules.model import Finding, Status

RULE = "R7"
NAME = "Statutory review"
VERSION = "1.0.0"


def evaluate(ctx: Context) -> Finding:
    f = Finding(RULE, NAME, Status.NOT_APPLICABLE, "", VERSION)
    if not ctx.request.is_exclusive_family:
        f.summary = "A non-exclusive license does not trigger the exclusive-license conditions in 35 U.S.C. 209."
        return f
    f.status = Status.REVIEW
    f.summary = (
        "Counsel must check the 35 U.S.C. 209 conditions for an exclusive-family license, including the "
        "requirement that the licensee substantially manufacture products in the United States."
    )
    f.details = {
        "statute": "35 U.S.C. 209",
        "checklist": [
            "The licensee's plan to manufacture substantially in the United States",
            "The public interest and the licensee's ability to commercialize the invention",
            "The scope of the field and territory, kept no broader than reasonably needed",
        ],
    }
    return f
