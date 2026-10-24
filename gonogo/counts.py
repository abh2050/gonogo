"""Build the record count table in docs/data-sources.md from the ingestion and synthetic metadata.

python -m gonogo.counts          rewrites the table between the count markers
python -m gonogo.counts --check  exits 1 when the table differs from the data
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from gonogo.paths import DOCS, PROCESSED, SCOPE, SYNTHETIC

START, END = "<!-- counts:start -->", "<!-- counts:end -->"


def _meta(path: Any) -> dict[str, Any]:
    return dict(json.loads(path.read_text()))


def table() -> str:
    p = _meta(PROCESSED / "nasa_patents.meta.json")
    fr = _meta(PROCESSED / "federal_register.meta.json")
    t2 = _meta(PROCESSED / "t2_portal.meta.json")
    nt = _meta(PROCESSED / "ntrs.meta.json")
    us = _meta(PROCESSED / "uspto.meta.json")
    sc = _meta(SCOPE / "scope.meta.json")
    sy = _meta(SYNTHETIC / "manifest.json")["counts"]
    rows = [
        ("NASA Patents, JSON file named in the spec", "rows", p["json_rows"]),
        ("NASA Patents, full CSV export", "rows", p["csv_rows"]),
        ("NASA Patents, processed", "patents", p["records"]),
        ("NASA Patents, processed", "with a patent number", p["with_patent_number"]),
        ("NASA Patents, processed", "with an expiration date", p["with_expiration_date"]),
        ("Federal Register", "Intent to Grant notices, 2018 to today", fr["records"]),
        ("Federal Register", "notices with a licensee extracted", fr["with_licensee"]),
        ("Federal Register", "notices with an objection deadline", fr["with_objection_deadline"]),
        ("Federal Register", "notices that state a field of use", fr["field_of_use_status_counts"]["stated"]),
        ("Federal Register", "notices that match any patent", sc["notices_matched_any_patent"]),
        ("T2 portal", "technologies at the three centers", t2["technologies"]),
        ("T2 portal", "technologies with patent numbers", t2["with_patent_numbers"]),
        ("T2 portal", "technologies with a stated TRL", t2["with_trl"]),
        ("Scope", "patents in scope", sc["patents_in_scope"]),
        ("Scope", "patents in scope from the NASA dataset", sc["patents_in_scope_by_source"].get("nasa_patents", 0)),
        ("Scope", "patents in scope from the T2 portal", sc["patents_in_scope_by_source"].get("t2_portal", 0)),
        (
            "Scope",
            "patents in scope that USPTO shows in force",
            sc["patents_in_scope_by_uspto_state"].get("in_force", 0),
        ),
        (
            "Scope",
            "patents in scope that USPTO shows lapsed for unpaid fees",
            sc["patents_in_scope_by_uspto_state"].get("lapsed", 0),
        ),
        ("Scope", "patents in scope with no USPTO record", sc["patents_in_scope_by_uspto_state"].get("not_found", 0)),
        ("Scope", "notices in scope", sc["notices_in_scope"]),
        ("USPTO", "candidate patents checked at the three centers", us["candidates"]),
        ("USPTO", "candidates with a USPTO record", us["found"]),
        ("USPTO", "candidates in force", us["legal_state_counts"].get("in_force", 0)),
        ("USPTO", "candidates lapsed for unpaid maintenance fees", us["legal_state_counts"].get("lapsed", 0)),
        (
            "USPTO",
            "candidates the NASA dataset calls in force but USPTO shows lapsed",
            us["nasa_in_force_but_uspto_lapsed"],
        ),
        (
            "USPTO",
            "candidates the NASA dataset lists as applications that USPTO has granted",
            us["nasa_application_now_granted"],
        ),
        ("USPTO", "candidates reinstated after a lapse", us["reinstated_after_lapse"]),
        ("USPTO", "candidates with a recorded co-assignee besides NASA", us["with_co_assignee"]),
        ("NTRS", "in-scope patents with at least one related report", nt["patents_with_reports"]),
        ("NTRS", "unique reports", nt["unique_reports"]),
        ("NTRS", "patent-report links with a downloaded PDF", nt["pdfs_downloaded"]),
        ("Synthetic", "executed agreements (PDF and text)", sy["agreements"]),
        ("Synthetic", "agreements seeded from real notices", sy["agreements_seeded_from_real_notices"]),
        ("Synthetic", "proposed grants for rule cases", sy["proposed_grants"]),
        ("Synthetic", "ownership records", sy["ownership_records"]),
        (
            "Synthetic",
            "ownership records that list real USPTO co-assignees",
            sy["ownership_records_with_real_uspto_co_assignees"],
        ),
        ("Synthetic", "consent records", sy["consents"]),
        ("Synthetic", "export classifications", sy["export_classifications"]),
        ("Synthetic", "filing dates", sy["filing_dates"]),
        ("Synthetic", "clearance requests", sy["requests"]),
        ("Synthetic", "injected cases with expected verdicts", sy["injected_cases"]),
    ]
    lines = ["| Source | Measure | Count |", "|---|---|---:|"]
    lines += [f"| {s} | {m} | {c:,} |" for s, m, c in rows]
    return "\n".join(lines)


def render(doc: str) -> str:
    head, rest = doc.split(START, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{START}\n{table()}\n{END}{tail}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = DOCS / "data-sources.md"
    doc = path.read_text()
    new = render(doc)
    if args.check:
        sys.exit(0 if new == doc else 1)
    path.write_text(new)


if __name__ == "__main__":
    main()
