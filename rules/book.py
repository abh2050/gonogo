"""The request book: the clearance questions that a steward's approval could change.

Before an approval takes effect, GoNoGo reruns the questions on the same patent and checks whether any verdict
would move to GO. The book holds the 43 synthetic requests (committed under api/snapshot/ for the demo) and any
question that the steward's session has asked.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gonogo.paths import SNAPSHOT, SYNTHETIC
from rules.model import Request

LICENSEE_BASE = "https://w3id.org/gonogo/id/licensee/"


def book_path() -> Path:
    committed = SNAPSHOT / "requests.jsonl"
    return committed if committed.exists() else SYNTHETIC / "requests.jsonl"


def load_book() -> list[dict[str, Any]]:
    return [json.loads(line) for line in book_path().read_text().splitlines() if line.strip()]


def to_request(row: dict[str, Any]) -> Request:
    """A request-book row as a Request. The licensee is the one named at the start of the text."""
    return Request(
        patent_key=row["patent_key"],
        exclusivity=row["exclusivity"],
        field=row["field_concept"],
        territory=row["territory"],
        start=row["start"],
        end=row["end"],
        licensee_name=row["text"].split(" wants")[0],
        licensee_ids=(LICENSEE_BASE + row["licensee_id"],),
        licensee_country=row["licensee_country"],
        text=row["text"],
    )


def requests_for_patents(patent_keys: set[str]) -> list[Request]:
    return [to_request(r) for r in load_book() if r["patent_key"] in patent_keys]
