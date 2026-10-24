"""NASA Patents dataset (data.nasa.gov, dataset id gquh-watm).

The spec URL returns a JSON array that stops at exactly 1,000 rows. The CKAN catalog
entry for the same dataset lists a full CSV export, so this module downloads both,
records whether the JSON is truncated, and uses the CSV as the source of record.
The dataset is a snapshot last modified in May 2025.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from ingest import normalize
from ingest.common import Fetcher, write_jsonl, write_meta

SOURCE = "nasa_patents"
JSON_URL = "https://data.nasa.gov/docs/legacy/NASA_Patents/gquh-watm.json"
CSV_URL = "https://data.nasa.gov/docs/legacy/NASA_Patents/NASA_Patents_rows.csv"
CATALOG_URL = "https://data.nasa.gov/api/3/action/package_search"

CSV_FIELDS = {
    "Center": "center",
    "Status": "status",
    "Case Number": "case_number",
    "Patent Number": "patent_number",
    "Application SN": "application_sn",
    "Title": "title",
    "Patent Expiration Date": "patent_expiration_date",
}


def parse_date(value: str | None) -> str | None:
    """Return YYYY-MM-DD from '2033-06-13T00:00:00.000' or '06/13/2033'."""
    if not value or not value.strip():
        return None
    v = value.strip()
    if "T" in v or (len(v) >= 10 and v[4] == "-"):
        return v[:10]
    parts = v.split(" ")[0].split("/")
    if len(parts) == 3:
        m, d, y = parts
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return None


def to_record(row: dict[str, Any]) -> dict[str, Any]:
    raw_patent = (row.get("patent_number") or "").strip() or None
    raw_serial = (row.get("application_sn") or "").strip() or None
    return {
        "case_number": normalize.case_number(row.get("case_number")) or (row.get("case_number") or "").strip(),
        "case_number_raw": (row.get("case_number") or "").strip(),
        "center": (row.get("center") or "").strip(),
        "status": (row.get("status") or "").strip(),
        "patent_number": normalize.patent_number(raw_patent),
        "patent_number_raw": raw_patent,
        "application_sn": normalize.application_serial(raw_serial),
        "application_sn_raw": raw_serial,
        "title": " ".join((row.get("title") or "").split()),
        "patent_expiration_date": parse_date(row.get("patent_expiration_date")),
    }


def parse_csv(text: str) -> list[dict[str, Any]]:
    rows = csv.DictReader(io.StringIO(text))
    return [to_record({CSV_FIELDS.get(k, k): v for k, v in r.items()}) for r in rows]


def run(refresh: bool = False) -> dict[str, Any]:
    f = Fetcher(SOURCE, refresh=refresh)
    try:
        json_env = f.fetch(JSON_URL)
        csv_env = f.fetch(CSV_URL)
        catalog = f.fetch(CATALOG_URL, params={"q": "gquh-watm"})
    finally:
        f.close()

    json_rows = json_env["body"]
    records = parse_csv(csv_env["body"])
    # Duplicate case numbers exist in the source; keep the first row and count the rest.
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for r in records:
        key = r["case_number"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    unique.sort(key=lambda r: r["case_number"])
    write_jsonl(SOURCE, unique)

    pkg = catalog["body"]["result"]["results"][0] if catalog["body"]["result"]["results"] else {}
    meta = {
        "source": SOURCE,
        "json_url": JSON_URL,
        "json_rows": len(json_rows),
        "json_retrieved_at": json_env["retrieved_at"],
        "json_truncated": len(json_rows) < len(records),
        "csv_url": CSV_URL,
        "csv_rows": len(records),
        "csv_retrieved_at": csv_env["retrieved_at"],
        "catalog_metadata_modified": pkg.get("metadata_modified"),
        "records": len(unique),
        "duplicate_case_numbers_dropped": len(records) - len(unique),
        "with_patent_number": sum(1 for r in unique if r["patent_number"]),
        "with_expiration_date": sum(1 for r in unique if r["patent_expiration_date"]),
        "with_application_sn": sum(1 for r in unique if r["application_sn"]),
        "network_calls": f.network_calls,
    }
    write_meta(SOURCE, meta)
    return meta
