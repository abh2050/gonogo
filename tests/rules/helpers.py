"""Shared helpers for the rule tests."""

from __future__ import annotations

import json
from typing import Any

from gonogo.paths import SYNTHETIC

AS_OF = "2026-11-01"
CUTOFF = "2026-11-01T00:00:00Z"


def jsonl(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (SYNTHETIC / name).read_text().splitlines() if line.strip()]


def injected_cases() -> list[dict[str, Any]]:
    return list(json.loads((SYNTHETIC / "injected_conflicts.json").read_text())["cases"])


def requests_by_id() -> dict[str, dict[str, Any]]:
    return {r["request_id"]: r for r in jsonl("requests.jsonl")}


from rules.book import to_request  # noqa: E402,F401  (the helper moved to rules.book)
