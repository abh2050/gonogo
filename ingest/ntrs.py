"""NASA Technical Reports Server (ntrs.nasa.gov/api).

For each in-scope patent the module searches NTRS with the patent title, keeps up to
HITS_PER_PATENT reports whose titles share at least MIN_SHARED_TERMS content words with the
patent title, lists each report's files through GET /citations/{id}/downloads, and
downloads PDFs up to MAX_PDFS in total. The corpus feeds the retrieval tool in Gate 4.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from typing import Any

from gonogo.paths import SCOPE
from ingest.common import Fetcher, write_jsonl, write_meta

SOURCE = "ntrs"
BASE = "https://ntrs.nasa.gov"
SEARCH_URL = BASE + "/api/citations/search"
DOWNLOADS_URL = BASE + "/api/citations/{id}/downloads"
HITS_PER_PATENT = 3
MIN_SHARED_TERMS = 2
MAX_PDFS = 300

STOPWORDS = set(
    "a an and the of for in on to with by from using use method methods system systems apparatus device "
    "devices process processes based via its at as or nasa improved".split()
)


def terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOPWORDS}


def search_body(title: str) -> dict[str, Any]:
    # Order by first position in the title, then alphabetically, so the query text never depends on set order.
    lowered = title.lower()
    q = " ".join(sorted(terms(title), key=lambda w: (lowered.find(w), w)))
    return {"q": q, "page": {"size": 10, "from": 0}}


def relevant_hits(title: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    want = terms(title)
    hits = []
    for r in results:
        shared = want & terms(r.get("title", ""))
        if len(shared) >= MIN_SHARED_TERMS:
            hits.append({**r, "_shared_terms": sorted(shared)})
    return hits[:HITS_PER_PATENT]


def pdf_link(files: list[dict[str, Any]]) -> str | None:
    for item in files:
        links = item.get("links", {})
        if links.get("pdf"):
            return str(links["pdf"])
        if item.get("mimetype") == "application/pdf" and links.get("original"):
            return str(links["original"])
    return None


def run(refresh: bool = False, max_pdfs: int = MAX_PDFS) -> dict[str, Any]:
    with (SCOPE / "patents_in_scope.csv").open() as fh:
        in_scope = list(csv.DictReader(fh))

    f = Fetcher(SOURCE, refresh=refresh)
    records: list[dict[str, Any]] = []
    pdfs = 0
    try:
        for p in in_scope:
            env = f.fetch(SEARCH_URL, method="POST", json_body=search_body(p["title"]))
            for rank, hit in enumerate(relevant_hits(p["title"], env["body"].get("results", [])), start=1):
                rec: dict[str, Any] = {
                    "patent_key": p["patent_key"],
                    "ntrs_id": str(hit["id"]),
                    "rank": rank,
                    "score": round(float(hit.get("_meta", {}).get("score", 0.0)), 3),
                    "shared_terms": hit["_shared_terms"],
                    "title": hit.get("title"),
                    "abstract": hit.get("abstract"),
                    "sti_type": hit.get("stiType"),
                    "distribution": hit.get("distribution"),
                    "center": (hit.get("center") or {}).get("name"),
                    "url": f"{BASE}/citations/{hit['id']}",
                    "retrieved_at": env["retrieved_at"],
                    "pdf_file": None,
                }
                if hit.get("downloadsAvailable") and pdfs < max_pdfs:
                    files_env = f.fetch(DOWNLOADS_URL.format(id=hit["id"]), allow_status=(404,))
                    files = files_env["body"] if isinstance(files_env.get("body"), list) else []
                    if link := pdf_link(files):
                        pdf_env = f.fetch(BASE + link, binary=True, allow_status=(403, 404))
                        if pdf_env["status"] == 200:
                            rec["pdf_file"] = f"data/raw/{SOURCE}/{pdf_env['body_file']}"
                            pdfs += 1
                records.append(rec)
    finally:
        f.close()

    write_jsonl(SOURCE, records)
    covered = {r["patent_key"] for r in records}
    meta = {
        "source": SOURCE,
        "search_url": SEARCH_URL,
        "downloads_url": DOWNLOADS_URL,
        "patents_searched": len(in_scope),
        "patents_with_reports": len(covered),
        "report_links": len(records),
        "unique_reports": len({r["ntrs_id"] for r in records}),
        "pdfs_downloaded": sum(1 for r in records if r["pdf_file"]),
        "pdf_cap": max_pdfs,
        "sti_types": dict(sorted(Counter(str(r["sti_type"]) for r in records).items())),
        "network_calls": f.network_calls,
    }
    write_meta(SOURCE, meta)
    return meta
