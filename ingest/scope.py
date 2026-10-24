"""Choose the in-scope patents and notices for the first build.

Pass 1 ranks centers by how many notices match a patent in the NASA Patents dataset and
keeps the top three. Pass 2 runs after the T2 module and adds every T2 patent at those
centers that a notice names but the dataset lacks; the dataset stops at patents issued
around 2014, while most notices since 2018 cite newer patents.

A notice matches a patent when any of its patent numbers, application serials, or NASA
case numbers equals the patent's normalized value. Case numbers also match on the family
root (LAR-18232-1 matches LAR-18232-2), and that weaker match is labeled case_family.
Scope = every matched patent at the three centers, then Issued dataset patents spread
evenly across those centers until TARGET is reached. A dataset patent counts as issued when
the NASA snapshot says Issued or USPTO shows a grant. The fill takes patents that USPTO shows in
force first, then patents the NASA dataset calls in force, then the rest, each group in case number
order. Pass 3 runs after the USPTO module; earlier passes fall back to the NASA expiration date.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from typing import Any

from gonogo.paths import PROCESSED, SCOPE
from ingest import normalize
from ingest.common import read_jsonl, write_meta

TARGET = 300
N_CENTERS = 3
# Fill prefers patents still in force on this date, because a licensing office mostly
# clears requests on live patents. Expired patents still enter scope through notice matches.
IN_FORCE_ON = "2026-11-01"
GRANTED_STATES = {"in_force", "lapsed", "term_ended"}
SCOPE_FIELDS = [
    "patent_key",
    "source",
    "case_number",
    "center",
    "status",
    "patent_number",
    "application_sn",
    "title",
    "patent_expiration_date",
    "tops_id",
    "matched_notices",
    "match_basis",
]
TOPS_CENTER = {
    "LAR": "NASA Langley Research Center",
    "LEW": "NASA Glenn Research Center",
    "KSC": "NASA Kennedy Space Center",
    "GSC": "NASA Goddard Space Flight Center",
    "ARC": "NASA Ames Research Center",
    "DRC": "NASA Armstrong Flight Research Center",
    "MSC": "NASA Johnson Space Center",
    "MFS": "NASA Marshall Space Flight Center",
}


def dataset_patents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**r, "patent_key": r["case_number"], "source": "nasa_patents", "tops_id": None} for r in rows]


def match(patents: list[dict[str, Any]], notices: list[dict[str, Any]]) -> dict[str, list[tuple[str, str]]]:
    """Return {patent_key: [(document_number, basis), ...]}."""
    by_patent: dict[str, list[str]] = defaultdict(list)
    by_serial: dict[str, list[str]] = defaultdict(list)
    by_case: dict[str, list[str]] = defaultdict(list)
    by_root: dict[str, list[str]] = defaultdict(list)
    for p in patents:
        key = p["patent_key"]
        if p.get("patent_number"):
            by_patent[p["patent_number"]].append(key)
        if p.get("application_sn"):
            by_serial[p["application_sn"]].append(key)
        if p.get("case_number"):
            by_case[p["case_number"]].append(key)
            if root := normalize.case_root(p["case_number"]):
                by_root[root].append(key)

    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for n in notices:
        hits: dict[str, str] = {}
        for pn in n["patent_numbers"]:
            for key in by_patent.get(pn, []):
                hits.setdefault(key, "patent_number")
        for sn in n["application_sns"]:
            for key in by_serial.get(sn, []):
                hits.setdefault(key, "application_sn")
        for c in n["case_numbers"]:
            for key in by_case.get(c, []):
                hits.setdefault(key, "case_number")
            for key in by_root.get(normalize.case_root(c) or "", []):
                hits.setdefault(key, "case_family")
        for key, basis in hits.items():
            out[key].append((n["document_number"], basis))
    return out


def rank_centers(patents: list[dict[str, Any]], matches: dict[str, list[tuple[str, str]]]) -> list[str]:
    by_key = {p["patent_key"]: p for p in patents}
    center_notices: dict[str, set[str]] = defaultdict(set)
    for key, hits in matches.items():
        center_notices[by_key[key]["center"]].update(d for d, _ in hits)
    return sorted(center_notices, key=lambda c: (-len(center_notices[c]), c))[:N_CENTERS]


def t2_notice_patents(
    t2: list[dict[str, Any]], notices: list[dict[str, Any]], centers: list[str], known: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build patent records for T2 patents at the chosen centers that a notice names.

    A T2 page lists case numbers and patent numbers without pairing them, so a record
    carries a case number only when the page has exactly one case, and a patent number only
    when the notice names it (or the page has exactly one patent).
    """
    known_pn = {p["patent_number"] for p in known if p.get("patent_number")}
    known_cn = {p["case_number"] for p in known if p.get("case_number")}
    out: dict[str, dict[str, Any]] = {}
    for tech in t2:
        center = TOPS_CENTER.get(tech["tops_id"].split("-", 1)[0])
        if center not in centers:
            continue
        roots = {normalize.case_root(c) for c in tech["case_numbers"]}
        for n in notices:
            named_pn = [pn for pn in n["patent_numbers"] if pn in tech["patent_numbers"] and pn not in known_pn]
            named_cn = [
                c
                for c in n["case_numbers"]
                if (c in tech["case_numbers"] or normalize.case_root(c) in roots) and c not in known_cn
            ]
            single_case = tech["case_numbers"][0] if len(tech["case_numbers"]) == 1 else None
            single_pn = tech["patent_numbers"][0] if len(tech["patent_numbers"]) == 1 else None
            for pn in named_pn:
                key = f"US{pn}"
                out.setdefault(
                    key,
                    {
                        "patent_key": key,
                        "source": "t2_portal",
                        "case_number": single_case,
                        "center": center,
                        "status": "Issued",
                        "patent_number": pn,
                        "application_sn": None,
                        "title": tech["title"],
                        "patent_expiration_date": None,
                        "tops_id": tech["tops_id"],
                    },
                )
            for cn in named_cn:
                if any(r["case_number"] == cn for r in out.values()):
                    continue
                pn = single_pn if single_pn and single_pn not in known_pn and f"US{single_pn}" not in out else None
                out.setdefault(
                    cn,
                    {
                        "patent_key": cn,
                        "source": "t2_portal",
                        "case_number": cn,
                        "center": center,
                        "status": "Issued" if pn else "",
                        "patent_number": pn,
                        "application_sn": None,
                        "title": tech["title"],
                        "patent_expiration_date": None,
                        "tops_id": tech["tops_id"],
                    },
                )
    return [out[k] for k in sorted(out)]


def select(
    patents: list[dict[str, Any]],
    matches: dict[str, list[tuple[str, str]]],
    centers: list[str],
    target: int = TARGET,
    uspto_state: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    chosen = [p for p in patents if p["center"] in centers and p["patent_key"] in matches]
    chosen_keys = {p["patent_key"] for p in chosen}
    per_center: dict[str, list[dict[str, Any]]] = defaultdict(list)

    states = uspto_state or {}

    def fill_order(p: dict[str, Any]) -> tuple[bool, bool, str]:
        uspto_in_force = states.get(p["patent_key"]) == "in_force"
        nasa_in_force = (p.get("patent_expiration_date") or "") >= IN_FORCE_ON
        return (not uspto_in_force, not nasa_in_force, p["patent_key"])

    for p in sorted(patents, key=fill_order):
        if (
            p["center"] in centers
            and p["source"] == "nasa_patents"
            # The NASA snapshot lists many applications that USPTO has since granted.
            and (p["status"] == "Issued" or states.get(p["patent_key"]) in GRANTED_STATES)
            and p["patent_key"] not in chosen_keys
        ):
            per_center[p["center"]].append(p)
    i = 0
    while len(chosen) < target and any(per_center.values()):
        c = centers[i % len(centers)]
        if per_center[c]:
            chosen.append(per_center[c].pop(0))
        i += 1
    return sorted(chosen, key=lambda p: p["patent_key"])


def run() -> dict[str, Any]:
    dataset = dataset_patents(read_jsonl(PROCESSED / "nasa_patents.jsonl"))
    notices = read_jsonl(PROCESSED / "federal_register.jsonl")
    dataset_matches = match(dataset, notices)
    centers = rank_centers(dataset, dataset_matches)

    t2_path = PROCESSED / "t2_portal.jsonl"
    t2_added: list[dict[str, Any]] = []
    if t2_path.exists():
        t2_added = t2_notice_patents(read_jsonl(t2_path), notices, centers, dataset)
    patents = dataset + t2_added
    matches = match(patents, notices)
    uspto_path = PROCESSED / "uspto.jsonl"
    uspto_state = (
        {r["patent_key"]: r.get("legal_state", "not_found") for r in read_jsonl(uspto_path)}
        if uspto_path.exists()
        else None
    )
    chosen = select(patents, matches, centers, uspto_state=uspto_state)
    chosen_keys = {p["patent_key"] for p in chosen}

    SCOPE.mkdir(parents=True, exist_ok=True)
    with (SCOPE / "patents_in_scope.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SCOPE_FIELDS, lineterminator="\n")
        w.writeheader()
        for p in chosen:
            hits = sorted(matches.get(p["patent_key"], []))
            w.writerow(
                {
                    **{k: p.get(k) or "" for k in SCOPE_FIELDS[:10]},
                    "matched_notices": ";".join(d for d, _ in hits),
                    "match_basis": ";".join(sorted({b for _, b in hits})),
                }
            )
    in_scope_docs = sorted({d for key in chosen_keys for d, _ in matches.get(key, [])})
    (SCOPE / "notices_in_scope.txt").write_text("\n".join(in_scope_docs) + "\n")

    matched_docs = {d for hits in matches.values() for d, _ in hits}
    dataset_docs = {d for hits in dataset_matches.values() for d, _ in hits}
    by_key = {p["patent_key"]: p for p in patents}
    meta = {
        "pass": 3 if uspto_state is not None else 2 if t2_path.exists() else 1,
        "centers": centers,
        "patents_in_scope": len(chosen),
        "patents_in_scope_by_center": dict(sorted(Counter(p["center"] for p in chosen).items())),
        "patents_in_scope_by_source": dict(sorted(Counter(p["source"] for p in chosen).items())),
        "patents_in_scope_by_status": dict(sorted(Counter(p["status"] or "unknown" for p in chosen).items())),
        "patents_in_scope_with_expiration": sum(1 for p in chosen if p.get("patent_expiration_date")),
        "patents_in_scope_in_force_on": [
            IN_FORCE_ON,
            sum(1 for p in chosen if (p.get("patent_expiration_date") or "") >= IN_FORCE_ON),
        ],
        "patents_in_scope_by_uspto_state": dict(
            sorted(Counter((uspto_state or {}).get(p["patent_key"], "not_checked") for p in chosen).items())
        ),
        "patents_with_notice_in_scope": sum(1 for p in chosen if p["patent_key"] in matches),
        "t2_patents_added": len(t2_added),
        "notices_total": len(notices),
        "notices_matched_dataset_only": len(dataset_docs),
        "notice_match_rate_dataset_only": round(len(dataset_docs) / len(notices), 3),
        "notices_matched_any_patent": len(matched_docs),
        "notice_match_rate": round(len(matched_docs) / len(notices), 3),
        "notices_in_scope": len(in_scope_docs),
        "match_basis_counts": dict(sorted(Counter(b for h in matches.values() for _, b in h).items())),
        "matched_notices_by_center": dict(sorted(Counter(by_key[k]["center"] for k in matches).items())),
        "dataset_max_patent_number": max(
            int(p["patent_number"]) for p in dataset if (p.get("patent_number") or "").isdigit()
        ),
        "unmatched_notices": sorted(n["document_number"] for n in notices if n["document_number"] not in matched_docs),
    }
    write_meta("scope", meta, root=SCOPE)
    return meta


def centers() -> list[str]:
    return list(json.loads((SCOPE / "scope.meta.json").read_text())["centers"])
