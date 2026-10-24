"""Extractor checks against real notices. Expected values were read from the notice text by hand."""

import json
from pathlib import Path
from typing import Any

import pytest

from ingest.federal_register import clean_text, extract

FIXTURES = Path(__file__).parent.parent / "fixtures" / "fr_notices.jsonl"
NOTICES = {json.loads(line)["document_number"]: json.loads(line) for line in FIXTURES.read_text().splitlines()}

EXPECTED: dict[str, dict[str, Any]] = {
    "2021-10423": {
        "exclusivity": "partially exclusive",
        "territory": "United States",
        "licensee": "SMART Tire Company, Inc.",
        "licensee_address": "Los Angeles, CA",
        "application_sns": ["17119632"],
        "case_numbers": ["LEW-20196-1"],
        "objection_deadline": "2021-06-02",
        "objection_deadline_basis": "publication date + 15 days",
        "field_of_use_status": "stated",
    },
    "2022-04856": {
        "exclusivity": "unspecified",
        "territory": "United States",
        "licensee": "SEA.O.G, LLC",
        "patent_numbers": ["11078984"],
        "objection_deadline": "2022-03-23",
        "objection_deadline_basis": "stated date",
        "field_of_use_status": "limited_unspecified",
        "field_of_use": None,
    },
    "2018-24323": {
        "exclusivity": "partially exclusive",
        "licensee": "Sally R",
        "objection_deadline": "2018-11-23",
    },
    "2022-26825": {
        "licensee": "Biodex Medical Systems, a Mirion Medical Company",
        "patent_numbers": ["11406867"],
        "jointly_owned": True,
    },
    "2020-01884": {
        "exclusivity": "exclusive",
        "licensee": "Oerlikon Metco (US) Inc.",
        "licensee_address": "Westbury, New York",
        "field_of_use": "power generation and aerospace",
        "objection_deadline": "2020-02-18",
    },
    "2018-09790": {"is_correction": True},
    "2024-17960": {
        "licensee": "Kinnor Foundation, Inc. and its subsidiary Kinnor Technologies, LLC",
        "patent_numbers": ["10406346", "11298526"],
        "objection_deadline": "2024-08-28",
    },
    "2022-21034": {"exclusivity": "unspecified", "territory": "United States", "licensee": "Hanwha Cimarron"},
}


@pytest.mark.parametrize("doc", sorted(EXPECTED))
def test_extract_matches_hand_labels(doc: str) -> None:
    n = NOTICES[doc]
    got = extract(n["text"], n["publication_date"])
    for key, value in EXPECTED[doc].items():
        assert got[key] == value, f"{doc} {key}"


@pytest.mark.parametrize("doc", sorted(EXPECTED))
def test_every_span_points_at_its_text(doc: str) -> None:
    n = NOTICES[doc]
    for span in extract(n["text"], n["publication_date"])["spans"]:
        assert n["text"][span["start"] : span["end"]] == span["text"]


def test_clean_text_rejoins_wrapped_identifiers() -> None:
    raw = "<pre>Serial Number 17/\n119,632 entitled, ``Tube,'' LEW-\n20196-1, to [[Page 2]] X</pre>"
    assert clean_text(raw) == 'Serial Number 17/119,632 entitled, "Tube," LEW-20196-1, to X'
