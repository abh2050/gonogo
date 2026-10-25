"""Types shared by the rules, the combiner, and the decision record."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    REVIEW = "REVIEW"
    PENDING = "PENDING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


EXCLUSIVE_TYPES = ("exclusive", "partially-exclusive", "co-exclusive")
EXCLUSIVITY_TYPES = (*EXCLUSIVE_TYPES, "non-exclusive")


def exclusivity_slug(value: str) -> str:
    slug = re.sub(r"[^a-z]+", "-", value.lower()).strip("-")
    if slug not in EXCLUSIVITY_TYPES:
        raise ValueError(f"Unknown exclusivity type: {value!r}")
    return slug


@dataclass(frozen=True)
class Request:
    """A structured clearance request. Every value is a concept id or an ISO date, never free text."""

    patent_key: str
    exclusivity: str
    field: str | None
    territory: str | None
    start: str
    end: str
    licensee_name: str | None = None
    licensee_ids: tuple[str, ...] = ()
    licensee_country: str | None = None
    text: str | None = None

    def canonical(self) -> dict[str, Any]:
        return {
            "patent_key": self.patent_key,
            "exclusivity": exclusivity_slug(self.exclusivity),
            "field": self.field,
            "territory": self.territory,
            "start": self.start,
            "end": self.end,
            "licensee_name": self.licensee_name,
            "licensee_ids": sorted(self.licensee_ids),
            "licensee_country": self.licensee_country,
        }

    @property
    def is_exclusive_family(self) -> bool:
        return exclusivity_slug(self.exclusivity) in EXCLUSIVE_TYPES


@dataclass
class FactRef:
    """A fact that a rule read, with where it came from and who approved it."""

    iri: str
    kind: str
    label: str
    recorded_at: str | None = None
    approved_by: str | None = None
    origin: str = "real"  # "real" or "synthetic"
    sources: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ClauseRef:
    """The exact words that a fact was read from."""

    iri: str
    fact: str
    kind: str
    text: str
    start: int
    end: int
    document: str
    document_title: str | None = None
    document_url: str | None = None


@dataclass
class Finding:
    rule: str
    name: str
    status: Status
    summary: str
    rule_version: str
    facts: list[FactRef] = field(default_factory=list)
    clauses: list[ClauseRef] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def fact_iris(self) -> list[str]:
        return sorted({f.iri for f in self.facts})

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = str(self.status)
        return d
