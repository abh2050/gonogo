"""USPTO Open Data Portal (api.uspto.gov): legal status, term, and assignments for in-scope patents.

The NASA Patents dataset gives a nominal expiration date, but a patent lapses early when its
maintenance fees go unpaid. This module reads the USPTO record for each in-scope patent, so R1
can tell a live patent from a lapsed one.

One call to /api/v1/patent/applications/{application number} returns the current status, filing
and grant dates, patent term adjustment, the event history (including EXP., the expiry for unpaid
maintenance fees), and the recorded assignments. A second call to /continuity returns the parent
applications, because a continuation or divisional takes its term from the earliest parent's filing
date. Patents with only a patent number are first resolved through the search endpoint.

The module reads every candidate patent at the three scope centers, not only the current scope, so
the final scope pass can prefer patents that USPTO shows in force.

The API key comes from USPTO_API_KEY in the environment or the git-ignored .env file. The key is
sent as a header and never written to the cache.
"""

from __future__ import annotations

import csv
from collections import Counter
from datetime import date, timedelta
from typing import Any

from gonogo import env
from gonogo.paths import PROCESSED, SCOPE
from ingest.common import Fetcher, read_jsonl, write_jsonl, write_meta

SOURCE = "uspto"
BASE = "https://api.uspto.gov/api/v1/patent/applications"
URAA_DATE = "1995-06-08"  # Applications filed on or after this date get a 20-year term from filing.
AS_OF = "2026-11-01"
NASA_NAMES = ("NATIONAL AERONAUTICS", "NASA", "ADMINISTRATOR OF THE NATIONAL AERONAUTICS")
EXPIRED_STATUS_WORDS = ("expired", "abandon")
REINSTATED_CODES = {"PMFG"}  # Petition decision: accept late payment of maintenance fee.


def is_nasa(name: str | None) -> bool:
    upper = (name or "").upper()
    return any(n in upper.replace(".", "") for n in NASA_NAMES)


def add_years(iso: str, years: int) -> date:
    d = date.fromisoformat(iso)
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def term_expiration(
    filing: str | None, earliest_parent_filing: str | None, grant: str | None, pta_days: int
) -> tuple[str | None, str]:
    """Return the statutory expiration date and the basis used to compute it.

    The result ignores terminal disclaimers, which can shorten a term; terminal_disclaimer flags them.
    """
    start = earliest_parent_filing or filing
    if not start or not grant:
        return None, "not granted or no filing date"
    if start >= URAA_DATE:
        return (add_years(start, 20) + timedelta(days=pta_days)).isoformat(), "earliest filing + 20 years + PTA"
    later = max(add_years(start, 20), add_years(grant, 17))
    return later.isoformat(), "pre-1995 filing: later of filing + 20 years and grant + 17 years"


def summarize(wrapper: dict[str, Any], continuity: dict[str, Any] | None) -> dict[str, Any]:
    meta = wrapper.get("applicationMetaData", {})
    pta = wrapper.get("patentTermAdjustmentData") or {}
    events = wrapper.get("eventDataBag", []) or []
    parents = []
    for bag in (continuity or {}).get("patentFileWrapperDataBag", []) or []:
        for p in bag.get("parentContinuityBag", []) or []:
            parents.append(
                {
                    "application": p.get("parentApplicationNumberText"),
                    "filing_date": p.get("parentApplicationFilingDate"),
                    "relationship": p.get("claimParentageTypeCodeDescriptionText") or p.get("claimParentageTypeCode"),
                }
            )
    # Provisional parents do not start the 20-year term.
    term_parents = [
        p["filing_date"] for p in parents if p["filing_date"] and "provisional" not in str(p["relationship"]).lower()
    ]
    earliest = min(term_parents) if term_parents else None
    filing = meta.get("filingDate")
    grant = meta.get("grantDate")
    pta_days = int(pta.get("adjustmentTotalQuantity") or 0)
    expiration, basis = term_expiration(
        filing, earliest if earliest and earliest < (filing or "9") else None, grant, pta_days
    )
    status = meta.get("applicationStatusDescriptionText") or ""
    ordered = sorted(events, key=lambda e: e.get("eventDate") or "")
    exp_events = [e for e in ordered if e.get("eventCode") == "EXP."]
    last_exp = exp_events[-1]["eventDate"] if exp_events else None
    reinstatements = [
        e
        for e in ordered
        if e.get("eventCode") in REINSTATED_CODES and last_exp and (e.get("eventDate") or "") >= last_exp
    ]
    fee_payments = [
        {"code": e.get("eventCode"), "date": e.get("eventDate"), "text": e.get("eventDescriptionText")}
        for e in ordered
        if str(e.get("eventCode", "")).startswith(("M155", "M255", "M355"))
    ]
    terminal = [e for e in events if "terminal disclaimer" in (e.get("eventDescriptionText") or "").lower()]

    assignees = []
    for a in wrapper.get("assignmentBag", []) or []:
        for who in a.get("assigneeBag", []) or []:
            assignees.append(
                {
                    "name": who.get("assigneeNameText"),
                    "recorded_date": a.get("assignmentRecordedDate"),
                    "conveyance": a.get("conveyanceText"),
                    "reel_frame": a.get("reelAndFrameNumber"),
                    "nasa": is_nasa(who.get("assigneeNameText")),
                }
            )

    # A lapse stands unless a later petition decision accepted the late fee and reinstated the patent.
    lapsed = (bool(exp_events) and not reinstatements) or (
        not exp_events and any(w in status.lower() for w in EXPIRED_STATUS_WORDS)
    )
    if not grant:
        legal_state = "abandoned" if "abandon" in status.lower() else "not_granted"
    elif lapsed:
        legal_state = "lapsed"
    elif expiration and expiration < AS_OF:
        legal_state = "term_ended"
    else:
        legal_state = "in_force"
    return {
        "application_number": wrapper.get("applicationNumberText"),
        "patent_number": meta.get("patentNumber"),
        "title": meta.get("inventionTitle"),
        "status_text": status,
        "status_date": meta.get("applicationStatusDate"),
        "filing_date": filing,
        "grant_date": grant,
        "earliest_parent_filing_date": earliest,
        "parents": parents,
        "pta_days": pta_days,
        "expiration_computed": expiration,
        "expiration_basis": basis,
        "terminal_disclaimer": bool(terminal),
        "lapse_events": [
            {"code": e.get("eventCode"), "date": e.get("eventDate"), "text": e.get("eventDescriptionText")}
            for e in exp_events
        ],
        "reinstated": bool(reinstatements),
        # Third parties may hold intervening rights for acts during this window (35 U.S.C. 41(c)).
        "lapse_period": [last_exp, reinstatements[0]["eventDate"]] if reinstatements else None,
        "fee_payments": fee_payments,
        "legal_state": legal_state,
        "assignees": assignees,
        "co_assignees": sorted({a["name"] for a in assignees if a["name"] and not a["nasa"]}),
        "last_ingestion": wrapper.get("lastIngestionDateTime"),
    }


def candidates() -> list[dict[str, Any]]:
    """Every NASA dataset patent at the scope centers, plus the T2 patents already in scope."""
    from ingest.scope import centers

    chosen = set(centers())
    out: dict[str, dict[str, Any]] = {}
    for p in read_jsonl(PROCESSED / "nasa_patents.jsonl"):
        if p["center"] in chosen:
            out[p["case_number"]] = {
                "patent_key": p["case_number"],
                "application_sn": p["application_sn"] or "",
                "patent_number": p["patent_number"] or "",
                "status": p["status"],
                "patent_expiration_date": p["patent_expiration_date"] or "",
            }
    with (SCOPE / "patents_in_scope.csv").open() as fh:
        for row in csv.DictReader(fh):
            out.setdefault(row["patent_key"], row)
    return [out[k] for k in sorted(out)]


def run(refresh: bool = False) -> dict[str, Any]:
    key = env.get("USPTO_API_KEY")
    if not key:
        raise RuntimeError("Set USPTO_API_KEY in .env (data.uspto.gov > My ODP) before running the USPTO module.")
    in_scope = candidates()

    f = Fetcher(SOURCE, refresh=refresh, headers={"X-API-KEY": key})
    records: list[dict[str, Any]] = []
    try:
        for p in in_scope:
            rec: dict[str, Any] = {"patent_key": p["patent_key"], "found": False}
            wrapper = None
            if p["application_sn"]:
                env_a = f.fetch(f"{BASE}/{p['application_sn']}", allow_status=(404,))
                if env_a["status"] == 200 and env_a["body"].get("patentFileWrapperDataBag"):
                    wrapper, rec["lookup"] = env_a, "application_sn"
            if wrapper is None and p["patent_number"]:
                env_s = f.fetch(
                    f"{BASE}/search",
                    params={
                        "q": f"applicationMetaData.patentNumber:{p['patent_number']}",
                        "fields": "applicationNumberText,applicationMetaData.patentNumber",
                    },
                    allow_status=(404,),
                )
                bag = env_s["body"].get("patentFileWrapperDataBag", []) if env_s["status"] == 200 else []
                if bag:
                    env_a = f.fetch(f"{BASE}/{bag[0]['applicationNumberText']}", allow_status=(404,))
                    if env_a["status"] == 200 and env_a["body"].get("patentFileWrapperDataBag"):
                        wrapper, rec["lookup"] = env_a, "patent_number_search"
            if wrapper is not None:
                app = wrapper["body"]["patentFileWrapperDataBag"][0]["applicationNumberText"]
                env_c = f.fetch(f"{BASE}/{app}/continuity", allow_status=(404,))
                cont = env_c["body"] if env_c["status"] == 200 else None
                rec.update(summarize(wrapper["body"]["patentFileWrapperDataBag"][0], cont))
                rec.update({"found": True, "retrieved_at": wrapper["retrieved_at"], "source_url": f"{BASE}/{app}"})
            nasa_exp = p["patent_expiration_date"] or None
            rec["nasa_expiration_date"] = nasa_exp
            rec["nasa_says_in_force"] = bool(nasa_exp and nasa_exp >= AS_OF)
            records.append(rec)
    finally:
        f.close()

    write_jsonl(SOURCE, records)
    found = [r for r in records if r["found"]]
    meta = {
        "source": SOURCE,
        "endpoint": BASE + "/{application number} and /continuity; /search for patent numbers",
        "as_of": AS_OF,
        "candidates": len(records),
        "found": len(found),
        "not_found": len(records) - len(found),
        "legal_state_counts": dict(sorted(Counter(r["legal_state"] for r in found).items())),
        "nasa_in_force_but_uspto_lapsed": sum(
            1 for r in found if r["nasa_says_in_force"] and r["legal_state"] == "lapsed"
        ),
        "nasa_in_force_and_uspto_in_force": sum(
            1 for r in found if r["nasa_says_in_force"] and r["legal_state"] == "in_force"
        ),
        "nasa_application_now_granted": sum(
            1 for r, p in zip(records, in_scope, strict=True) if p["status"] == "Application" and r.get("grant_date")
        ),
        "with_terminal_disclaimer": sum(1 for r in found if r["terminal_disclaimer"]),
        "with_co_assignee": sum(1 for r in found if r["co_assignees"]),
        "reinstated_after_lapse": sum(1 for r in found if r["reinstated"]),
        "lookup_counts": dict(sorted(Counter(r.get("lookup", "none") for r in records).items())),
        "network_calls": f.network_calls,
    }
    write_meta(SOURCE, meta)
    return meta
