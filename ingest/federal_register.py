"""Federal Register NASA "Intent to Grant" license notices, 2018 to today.

Each notice announces a PROPOSED grant and opens an objection window. Nothing in this
module creates an executed license. Every extracted value keeps the character span of
the text it came from, measured against the cleaned notice text stored in the record.
"""

from __future__ import annotations

import html
import re
from collections import Counter
from datetime import date, timedelta
from typing import Any

from ingest import normalize
from ingest.common import Fetcher, write_jsonl, write_meta

SOURCE = "federal_register"
SEARCH_URL = "https://www.federalregister.gov/api/v1/documents.json"
SEARCH_FIELDS = [
    "document_number",
    "title",
    "type",
    "abstract",
    "action",
    "dates",
    "publication_date",
    "html_url",
    "pdf_url",
    "raw_text_url",
    "agencies",
]
START_DATE = "2018-01-01"

NUMBER_WORDS = {
    "five": 5,
    "ten": 10,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty-five": 45,
    "sixty": 60,
}
MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}

Span = dict[str, Any]


def search_params(page: int, today: str) -> list[tuple[str, str]]:
    params = [
        ("conditions[agencies][]", "national-aeronautics-and-space-administration"),
        ("conditions[type][]", "NOTICE"),
        ("conditions[term]", '"Intent to Grant"'),
        ("conditions[publication_date][gte]", START_DATE),
        ("conditions[publication_date][lte]", today),
        ("per_page", "100"),
        ("page", str(page)),
        ("order", "oldest"),
    ]
    params += [("fields[]", f) for f in SEARCH_FIELDS]
    return params


def clean_text(raw: str) -> str:
    """Strip the HTML wrapper and join wrapped lines into single spaced text."""
    m = re.search(r"<pre>(.*)</pre>", raw, re.S)
    body = m.group(1) if m else raw
    body = re.sub(r"<[^>]+>", "", body)
    body = html.unescape(body).replace("``", '"').replace("''", '"')
    body = re.sub(r"\s*\[\[Page \d+\]\]\s*", " ", body)
    # Rejoin identifiers split across lines, such as "17/\n119,632" and "LEW-\n20196-1".
    body = re.sub(r"([/\-]) *\n\s*", r"\1", body)
    body = re.sub(r"(\bco-) (exclusive)", r"\1\2", body)
    return re.sub(r"\s+", " ", body).strip()


def _span(text: str, start: int, end: int, kind: str, value: Any) -> Span:
    return {"type": kind, "value": value, "start": start, "end": end, "text": text[start:end]}


def section(text: str, name: str) -> tuple[int, int] | None:
    m = re.search(rf"\b{name}:\s*(.+?)(?=\s(?:[A-Z][A-Z ]{{3,}}:)\s|$)", text)
    return (m.start(1), m.end(1)) if m else None


PATENT_RE = re.compile(r"\b(?:RE\s?)?\d{1,2},\d{3},\d{3}(?:\s?B\d)?\b")
SERIAL_RE = re.compile(r"\b(\d{2})/\s?(\d{3}),\s?(\d{3})\b")
CASE_PREFIXES = "|".join(sorted(normalize.CENTER_PREFIX, key=len, reverse=True))
CASE_RE = re.compile(rf"\b(?:{CASE_PREFIXES})[-\s]*\d{{4,6}}(?:-[0-9A-Z]+)*")
EXCLUSIVITY_RE = re.compile(
    r"(?:intent to grant|intends to grant) (?:an? )?"
    r"(partially[- ]exclusive|co-?exclusive|non-?exclusive|exclusive)",
    re.I,
)
EXCLUSIVITY_OPTIONS_RE = re.compile(
    r"(?:intent to grant|intends to grant) an? exclusive,\s*co-?exclusive,?\s*or\s+partially[- ]exclusive",
    re.I,
)
TERRITORY_RE = re.compile(
    r"(?i:license)\s+(?:to practice [^,]+?\s+)?(?:in|within|throughout)\s+"
    r"(the United States(?: of America)?(?: and [A-Z][a-zA-Z ]+?)?|[Ww]orldwide|[A-Z][a-zA-Z ,]+?)"
    r"(?=\s+(?:to|for|on)\s)",
)
WORLDWIDE_RE = re.compile(r"\bworldwide\b", re.I)
LEGAL_SUFFIX = r"(?:Inc|LLC|L\.L\.C|Ltd|LP|L\.P|Corp|Co|PLLC|LLP|PBC|GmbH|S\.A|B\.V|Limited)\.?"
# The name may contain commas ("Biodex Medical Systems, a Mirion Medical Company") but never the word
# "to", so the match always starts at the last "to" before "having its principal place of business".
LICENSEE_RE = re.compile(
    r"\bto\s+([A-Z0-9\"](?:(?!\bto\s)[^;]){1,160}?)\s*,?\s+(?:each\s+)?"
    r"(?:having|a\s+(?:company|corporation|business)\b|located|with\s+(?:its|a)\s+principal|"
    r"which\s+has|headquartered|doing business)",
)
ADDRESS_RE = re.compile(r"principal (?:place of business|office) (?:is )?(?:in|at)\s+([A-Z][\w .,'\-]+?)(?=\.|;| The )")
FIELD_RE = re.compile(
    r"(?:[Ff]ields? of use (?:may|will|would|shall) (?:be limited to|mean|include):?"
    r"|exclusivity for the following fields? of use:)\s+(.+?)(?:\.(?=\s+(?:NASA|The|This|[A-Z][a-z]+ [a-z]))|\.?$)"
)
FIELD_UNSTATED_RE = re.compile(r"[Ff]ields? of use may be limited\.")
JOINT_RE = re.compile(r"jointly[- ]owned|undivided interest|co-?owned", re.I)
CORRECTION_RE = re.compile(r"contained an? (?:incorrect|error)|amended version|\bcorrection\b", re.I)
DAYS_RE = re.compile(
    r"within\s+(?:(" + "|".join(NUMBER_WORDS) + r")\s*)?(?:\((\d+)\)|(\d+))?\s*(?:calendar\s+)?days",
    re.I,
)
ON_OR_BEFORE_RE = re.compile(
    r"(?:on or before|by|no later than)\s+(" + "|".join(m.title() for m in MONTHS) + r")\s+(\d{1,2}),\s+(\d{4})"
)


def extract(text: str, publication_date: str) -> dict[str, Any]:
    """Return extracted fields and their spans for one cleaned notice text."""
    spans: list[Span] = []
    # The grant terms sit in SUMMARY in older notices and in SUPPLEMENTARY INFORMATION in later ones.
    # Searching from SUMMARY to the end skips the title, which always says "Exclusive License".
    summary = section(text, "SUMMARY")
    s0 = summary[0] if summary else 0
    s1 = len(text)
    summary_text = text[s0:s1]

    for hit in PATENT_RE.finditer(text):
        spans.append(_span(text, hit.start(), hit.end(), "patent_number", normalize.patent_number(hit.group(0))))
    for hit in SERIAL_RE.finditer(text):
        spans.append(_span(text, hit.start(), hit.end(), "application_sn", "".join(hit.groups())))
    for hit in CASE_RE.finditer(text):
        spans.append(_span(text, hit.start(), hit.end(), "case_number", normalize.case_number(hit.group(0))))

    exclusivity, exclusivity_options = None, None
    if m := EXCLUSIVITY_OPTIONS_RE.search(summary_text):
        exclusivity = "unspecified"
        exclusivity_options = ["exclusive", "co-exclusive", "partially exclusive"]
        spans.append(_span(text, s0 + m.start(), s0 + m.end(), "exclusivity", exclusivity))
    elif m := EXCLUSIVITY_RE.search(summary_text):
        exclusivity = (
            m.group(1)
            .lower()
            .replace("-exclusive", " exclusive")
            .replace("co exclusive", "co-exclusive")
            .replace("coexclusive", "co-exclusive")
            .replace("non exclusive", "non-exclusive")
            .replace("nonexclusive", "non-exclusive")
        )
        spans.append(_span(text, s0 + m.start(1), s0 + m.end(1), "exclusivity", exclusivity))

    territory = None
    if m := TERRITORY_RE.search(summary_text):
        raw = m.group(1).strip().rstrip(",")
        territory = "worldwide" if raw.lower() == "worldwide" else raw.removeprefix("the ")
        spans.append(
            _span(text, s0 + m.start(1), s0 + m.start(1) + len(m.group(1).rstrip(", ")), "territory", territory)
        )
    elif m := WORLDWIDE_RE.search(summary_text):
        territory = "worldwide"
        spans.append(_span(text, s0 + m.start(), s0 + m.end(), "territory", territory))

    licensee = None
    for hit in LICENSEE_RE.finditer(summary_text):
        cand = hit.group(1).strip().rstrip(",")
        if cand.lower().startswith(("the ", "practice")) or len(cand) < 3:
            continue
        licensee = cand
        spans.append(_span(text, s0 + hit.start(1), s0 + hit.start(1) + len(cand), "licensee", licensee))
        break

    address = None
    if m := ADDRESS_RE.search(summary_text):
        address = m.group(1).strip().rstrip(",")
        spans.append(_span(text, s0 + m.start(1), s0 + m.start(1) + len(address), "licensee_address", address))

    field_of_use = None
    field_of_use_status = "limited_unspecified" if FIELD_UNSTATED_RE.search(summary_text) else "not_mentioned"
    if m := FIELD_RE.search(summary_text):
        field_of_use_status = "stated"
        field_of_use = m.group(1).strip()
        spans.append(_span(text, s0 + m.start(1), s0 + m.start(1) + len(field_of_use), "field_of_use", field_of_use))

    deadline, deadline_basis = None, None
    pub = date.fromisoformat(publication_date)
    if m := ON_OR_BEFORE_RE.search(text):
        mon, day, year = m.groups()
        deadline = date(int(year), MONTHS[mon.lower()], int(day)).isoformat()
        deadline_basis = "stated date"
        spans.append(_span(text, m.start(), m.end(), "objection_deadline", deadline))
    elif m := DAYS_RE.search(text):
        word, paren, digits = m.groups()
        days = int(paren or digits) if (paren or digits) else NUMBER_WORDS[word.lower()]
        deadline = (pub + timedelta(days=days)).isoformat()
        deadline_basis = f"publication date + {days} days"
        spans.append(_span(text, m.start(), m.end(), "objection_deadline", deadline))

    def uniq(kind: str) -> list[str]:
        return sorted({s["value"] for s in spans if s["type"] == kind and s["value"]})

    return {
        "patent_numbers": uniq("patent_number"),
        "application_sns": uniq("application_sn"),
        "case_numbers": uniq("case_number"),
        "exclusivity": exclusivity,
        "exclusivity_options": exclusivity_options,
        "territory": territory,
        "licensee": licensee,
        "licensee_address": address,
        "field_of_use": field_of_use,
        "field_of_use_status": field_of_use_status,
        "jointly_owned": bool(JOINT_RE.search(summary_text)),
        "is_correction": bool(CORRECTION_RE.search(summary_text[:600])),
        "objection_deadline": deadline,
        "objection_deadline_basis": deadline_basis,
        "spans": sorted(spans, key=lambda s: (s["start"], s["type"])),
    }


def run(refresh: bool = False, today: str | None = None) -> dict[str, Any]:
    today = today or date.today().isoformat()
    f = Fetcher(SOURCE, refresh=refresh)
    docs: list[dict[str, Any]] = []
    try:
        page, total_pages = 1, 1
        search_count = 0
        while page <= total_pages:
            env = f.fetch(SEARCH_URL, params=search_params(page, today))
            body = env["body"]
            search_count = body.get("count", 0)
            total_pages = body.get("total_pages", 1)
            docs.extend(body.get("results", []))
            page += 1

        records = []
        for d in sorted(docs, key=lambda d: d["document_number"]):
            text_env = f.fetch(d["raw_text_url"])
            text = clean_text(text_env["body"])
            fields = extract(text, d["publication_date"])
            records.append(
                {
                    "id": f"fr-{d['document_number']}",
                    "record_type": "ProposedGrant",
                    "document_number": d["document_number"],
                    "title": d["title"],
                    "action": d.get("action"),
                    "publication_date": d["publication_date"],
                    "html_url": d["html_url"],
                    "pdf_url": d.get("pdf_url"),
                    "raw_text_url": d["raw_text_url"],
                    "retrieved_at": text_env["retrieved_at"],
                    "text": text,
                    **fields,
                }
            )
    finally:
        f.close()

    write_jsonl(SOURCE, records)
    meta = {
        "source": SOURCE,
        "search_url": SEARCH_URL,
        "date_range": [START_DATE, today],
        "search_count": search_count,
        "records": len(records),
        "with_patent_or_serial_or_case": sum(
            1 for r in records if r["patent_numbers"] or r["application_sns"] or r["case_numbers"]
        ),
        "with_licensee": sum(1 for r in records if r["licensee"]),
        "with_exclusivity": sum(1 for r in records if r["exclusivity"]),
        "with_territory": sum(1 for r in records if r["territory"]),
        "with_field_of_use": sum(1 for r in records if r["field_of_use"]),
        "field_of_use_status_counts": dict(sorted(Counter(r["field_of_use_status"] for r in records).items())),
        "jointly_owned": sum(1 for r in records if r["jointly_owned"]),
        "corrections": sum(1 for r in records if r["is_correction"]),
        "exclusivity_counts": dict(sorted(Counter(str(r["exclusivity"]) for r in records).items())),
        "with_objection_deadline": sum(1 for r in records if r["objection_deadline"]),
        "network_calls": f.network_calls,
    }
    write_meta(SOURCE, meta)
    return meta
