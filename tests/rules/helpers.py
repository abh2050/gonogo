"""Shared helpers for the rule tests."""

from __future__ import annotations

import json
from typing import Any

from gonogo.paths import SYNTHETIC
from rules.model import Request

LICENSEE_BASE = "https://w3id.org/gonogo/id/licensee/"
AS_OF = "2026-11-01"
CUTOFF = "2026-11-01T00:00:00Z"


def jsonl(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (SYNTHETIC / name).read_text().splitlines() if line.strip()]


def injected_cases() -> list[dict[str, Any]]:
    return list(json.loads((SYNTHETIC / "injected_conflicts.json").read_text())["cases"])


def requests_by_id() -> dict[str, dict[str, Any]]:
    return {r["request_id"]: r for r in jsonl("requests.jsonl")}


def to_request(r: dict[str, Any]) -> Request:
    return Request(
        patent_key=r["patent_key"],
        exclusivity=r["exclusivity"],
        field=r["field_concept"],
        territory=r["territory"],
        start=r["start"],
        end=r["end"],
        licensee_name=r["text"].split(" wants")[0],
        licensee_ids=(LICENSEE_BASE + r["licensee_id"],),
        licensee_country=r["licensee_country"],
        text=r["text"],
    )
