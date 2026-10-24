"""NASA Technology Transfer portal (technology.nasa.gov).

The spec endpoint /api/1.0/patent/search/{q} returns 404, so this module records that
result and falls back to the portal's own search endpoint /api/api/patent/{q}. A search on
a center prefix such as "LEW" lists every TOPS technology record for that center. The
search rows carry title, abstract, category, and center but not case or patent numbers,
so the module also reads each technology's portal detail page for those fields.
"""

from __future__ import annotations

import csv
import html
import re
from collections import Counter
from typing import Any

from gonogo.paths import SCOPE
from ingest import normalize
from ingest.common import Fetcher, write_jsonl, write_meta

SOURCE = "t2_portal"
BASE = "https://technology.nasa.gov"
SPEC_SEARCH = BASE + "/api/1.0/patent/search/{q}"
FALLBACK_SEARCH = BASE + "/api/api/patent/{q}"
DETAIL_PAGE = BASE + "/patent/{tops_id}"

# T2 reference numbers use the legacy center prefixes.
CENTER_TOPS_PREFIX = {
    "NASA Langley Research Center": ["LAR"],
    "NASA Glenn Research Center": ["LEW"],
    "NASA Kennedy Space Center": ["KSC"],
    "NASA Goddard Space Flight Center": ["GSC"],
    "NASA Ames Research Center": ["ARC"],
    "NASA Armstrong Flight Research Center": ["DRC"],
    "NASA Johnson Space Center": ["MSC"],
    "NASA Marshall Space Flight Center": ["MFS"],
}

SPAN_RE = r'<span class="{cls}">(.*?)</span>'
TRL_RE = re.compile(r"\bTRL\s*(?:of\s*)?(\d)\b|Technology Readiness Level\D{0,20}(\d)", re.I)


def strip_tags(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


def parse_search_row(row: list[Any]) -> dict[str, Any]:
    return {
        "tops_id": row[0],
        "title": strip_tags(str(row[2])),
        "abstract": strip_tags(str(row[3])),
        "category": strip_tags(str(row[5])) or None,
        "center_code": row[9] or None,
        "image_url": row[10] or None,
    }


def parse_detail(page: str) -> dict[str, Any]:
    def spans(cls: str) -> list[str]:
        return [strip_tags(m) for m in re.findall(SPAN_RE.format(cls=cls), page, re.S)]

    case_numbers: list[str] = []
    for value in spans("case_number"):
        for token in re.split(r"[,;\s]+", value):
            if cn := normalize.case_number(token):
                case_numbers.append(cn)
    patent_numbers: list[str] = []
    for value in spans("patent_number"):
        for token in re.findall(r"\d{1,2},\d{3},\d{3}|\d{7,8}", value):
            if pn := normalize.patent_number(token):
                patent_numbers.append(pn)
    trl = None
    if m := TRL_RE.search(strip_tags(page)):
        trl = int(m.group(1) or m.group(2))
    categories = spans("category")
    return {
        "detail_category": categories[0] if categories else None,
        "case_numbers": sorted(set(case_numbers)),
        "patent_numbers": sorted(set(patent_numbers)),
        "trl": trl,
    }


def run(refresh: bool = False) -> dict[str, Any]:
    from ingest.scope import centers as scope_centers

    with (SCOPE / "patents_in_scope.csv").open() as fh:
        in_scope = list(csv.DictReader(fh))
    centers = scope_centers()
    prefixes = sorted({pre for c in centers for pre in CENTER_TOPS_PREFIX.get(c, [])})

    f = Fetcher(SOURCE, refresh=refresh)
    try:
        spec_env = f.fetch(SPEC_SEARCH.format(q=prefixes[0]), allow_status=(404,))
        spec_ok = spec_env["status"] == 200 and isinstance(spec_env.get("body"), dict)

        tech: dict[str, dict[str, Any]] = {}
        for pre in prefixes:
            env = f.fetch(FALLBACK_SEARCH.format(q=pre))
            for row in env["body"]["results"]:
                rec = parse_search_row(row)
                if rec["tops_id"].startswith(f"{pre}-TOPS-"):
                    rec["retrieved_at"] = env["retrieved_at"]
                    tech[rec["tops_id"]] = rec

        for tops_id in sorted(tech):
            env = f.fetch(DETAIL_PAGE.format(tops_id=tops_id), allow_status=(404,))
            detail = (
                parse_detail(env["body"])
                if env["status"] == 200
                else {
                    "detail_category": None,
                    "case_numbers": [],
                    "patent_numbers": [],
                    "trl": None,
                }
            )
            tech[tops_id].update(detail)
            tech[tops_id]["detail_url"] = DETAIL_PAGE.format(tops_id=tops_id)
            tech[tops_id]["detail_status"] = env["status"]
    finally:
        f.close()

    records = []
    for tops_id in sorted(tech):
        r = tech[tops_id]
        r["category"] = r["category"] or r.pop("detail_category", None)
        r.pop("detail_category", None)
        records.append(r)
    write_jsonl(SOURCE, records)

    by_case = {cn: r["tops_id"] for r in records for cn in r["case_numbers"]}
    by_root = {normalize.case_root(cn): r["tops_id"] for r in records for cn in r["case_numbers"]}
    by_patent = {pn: r["tops_id"] for r in records for pn in r["patent_numbers"]}
    joined: Counter[str] = Counter()
    for p in in_scope:
        if p["case_number"] in by_case:
            joined["case_number"] += 1
        elif p["patent_number"] and p["patent_number"] in by_patent:
            joined["patent_number"] += 1
        elif normalize.case_root(p["case_number"]) in by_root:
            joined["case_family"] += 1
        else:
            joined["none"] += 1

    meta = {
        "source": SOURCE,
        "spec_endpoint": SPEC_SEARCH,
        "spec_endpoint_status": spec_env["status"],
        "spec_endpoint_worked": spec_ok,
        "endpoint_used": FALLBACK_SEARCH + " plus " + DETAIL_PAGE,
        "center_prefixes": prefixes,
        "technologies": len(records),
        "with_category": sum(1 for r in records if r["category"]),
        "with_abstract": sum(1 for r in records if r["abstract"]),
        "with_case_numbers": sum(1 for r in records if r["case_numbers"]),
        "with_patent_numbers": sum(1 for r in records if r["patent_numbers"]),
        "with_trl": sum(1 for r in records if r["trl"] is not None),
        "categories": dict(sorted(Counter(r["category"] for r in records).items(), key=lambda kv: str(kv[0]))),
        "in_scope_patents_joined": dict(sorted(joined.items())),
        "network_calls": f.network_calls,
    }
    write_meta(SOURCE, meta)
    return meta
