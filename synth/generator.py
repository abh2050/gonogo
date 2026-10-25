"""Seeded synthetic augmentation for GoNoGo.

NASA does not publish executed license agreements, ownership and consent records, or export
classifications. This module generates them, plus synthetic filing dates for patents that lack
an expiration date, synthetic proposed grants for rule cases, and clearance requests.

Every record carries synthetic=True and generated_by=GENERATOR_IRI. Gate 1 turns that label into
prov:wasGeneratedBy, so no reader can mistake a synthetic fact for a real one.

The generator writes data/synthetic/injected_conflicts.json. Each injected case states the
expected status of each rule it asserts and the expected verdict. The expected values are written
by hand in build_cases(); the generator never runs rule logic to produce them.

Licensees and co-owners are fictional. Agreements seeded from real Federal Register notices copy
the notice's patents, exclusivity, field, and territory, but name a fictional licensee, because a
public repository should not claim that a real company holds a license it may not hold.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from gonogo.paths import ONTOLOGY, PROCESSED, SCOPE, SYNTHETIC
from synth import pdf

GENERATOR_IRI = "https://w3id.org/gonogo/synth/generator/v0.1"
TEMPLATES = Path(__file__).parent / "templates"
AS_OF = "2026-11-01"
CUTOFF = "2026-11-01T00:00:00Z"
REQ_START, REQ_END = "2027-01-01", "2031-12-31"
GRANT_FROM, GRANT_TO = "2025-01-01", "2034-12-31"
GRANT_EXECUTED, GRANT_RECORDED = "2024-12-15", "2025-01-10T00:00:00Z"
BACKGROUND_RECORDED = "2026-01-15T00:00:00Z"
TARGET_AGREEMENTS = 120
REQUESTER = "LIC-001"

EXCLUSIVE_TYPES = {"exclusive", "partially exclusive", "co-exclusive"}
PASS, FAIL, UNKNOWN, REVIEW, PENDING, NA = "PASS", "FAIL", "UNKNOWN", "REVIEW", "PENDING", "NOT_APPLICABLE"
GO, NO_GO, HOLD, COUNSEL, NO_DATA = "GO", "NO GO", "HOLD", "COUNSEL", "NO DATA"

EXCLUSIVITY_PHRASE = {
    "exclusive": "an exclusive",
    "partially exclusive": "a partially exclusive",
    "co-exclusive": "a co-exclusive",
    "non-exclusive": "a non-exclusive",
}
SUBLICENSE_TEXT = {
    True: "Licensee may grant sublicenses within the Field of Use with the prior written consent of NASA.",
    False: "Licensee may not grant sublicenses under this Agreement.",
}


def long_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def add_days(iso: str, days: int) -> str:
    return (date.fromisoformat(iso[:10]) + timedelta(days=days)).isoformat()


def label(record: dict[str, Any]) -> dict[str, Any]:
    return {**record, "synthetic": True, "generated_by": GENERATOR_IRI}


@dataclass
class Taxonomy:
    """Field and territory hierarchies, read from the SKOS schemes in ontology/schemes/.

    The ontology owns the hierarchy and the labels. The generator adds only the keywords that map a
    patent title to a narrower field (synth/templates/field_keywords.yaml).
    """

    fields: dict[str, dict[str, Any]]
    territories: dict[str, dict[str, Any]]
    field_labels: dict[str, str] = field(default_factory=dict)
    territory_labels: dict[str, str] = field(default_factory=dict)
    field_parent: dict[str, str] = field(default_factory=dict)
    category_to_top: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls) -> Taxonomy:
        from rdflib import Graph, URIRef
        from rdflib.namespace import SKOS

        keywords = yaml.safe_load((TEMPLATES / "field_keywords.yaml").read_text())
        fg = Graph().parse(ONTOLOGY / "schemes" / "fields.ttl")
        tg = Graph().parse(ONTOLOGY / "schemes" / "territories.ttl")

        def local(node: Any) -> str:
            return str(node).rsplit("/", 1)[1]

        def label(g: Graph, node: Any) -> str:
            return str(g.value(node, SKOS.prefLabel))

        def children(g: Graph, node: Any) -> list[Any]:
            return sorted(g.subjects(SKOS.broader, node), key=lambda n: str(g.value(n, SKOS.notation)))

        fields: dict[str, dict[str, Any]] = {}
        scheme = URIRef("https://w3id.org/gonogo/scheme/field-of-use")
        for top in sorted(fg.objects(scheme, SKOS.hasTopConcept), key=lambda n: str(fg.value(n, SKOS.notation))):
            fields[local(top)] = {
                "label": label(fg, top),
                "narrower": {
                    local(c): {"label": label(fg, c), "keywords": keywords[local(c)]} for c in children(fg, top)
                },
            }

        def territory_tree(node: Any) -> Any:
            kids = children(tg, node)
            if not kids:
                return label(tg, node)
            return {"label": label(tg, node), "narrower": {local(k): territory_tree(k) for k in kids}}

        territories = {
            local(t): territory_tree(t)
            for t in tg.objects(URIRef("https://w3id.org/gonogo/scheme/territory"), SKOS.hasTopConcept)
        }
        return cls(fields, territories)

    def __post_init__(self) -> None:
        for top, spec in self.fields.items():
            self.field_labels[top] = spec["label"]
            self.category_to_top[spec["label"].replace(",", "").lower()] = top
            for child, cspec in spec["narrower"].items():
                self.field_labels[child] = cspec["label"]
                self.field_parent[child] = top

        def walk(nodes: dict[str, Any]) -> None:
            for code, spec in nodes.items():
                if isinstance(spec, str):
                    self.territory_labels[code] = spec
                else:
                    self.territory_labels[code] = spec["label"]
                    walk(spec.get("narrower", {}))

        walk(self.territories)

    def siblings(self, concept: str) -> list[str]:
        parent = self.field_parent[concept]
        return [c for c in self.fields[parent]["narrower"] if c != concept]

    def concept_for(self, title: str, category: str | None) -> str:
        words = title.lower()
        top = self.category_to_top.get(category.replace(",", "").lower()) if category else None
        tops = [top] if top else list(self.fields)
        for top in tops:
            for child, cspec in self.fields[top]["narrower"].items():
                if any(k in words for k in cspec["keywords"]):
                    return str(child)
        return str(next(iter(self.fields[tops[0]]["narrower"])))


@dataclass
class World:
    rng: random.Random
    tax: Taxonomy
    licensees: dict[str, dict[str, Any]]
    co_owners: list[dict[str, Any]]
    clauses: dict[str, Any]
    patents: dict[str, dict[str, Any]]
    patent_field: dict[str, str]
    agreements: list[dict[str, Any]] = field(default_factory=list)
    proposed: list[dict[str, Any]] = field(default_factory=list)
    ownership: dict[str, dict[str, Any]] = field(default_factory=dict)
    consents: list[dict[str, Any]] = field(default_factory=list)
    export: dict[str, dict[str, Any]] = field(default_factory=dict)
    filing: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: list[dict[str, Any]] = field(default_factory=list)
    cases: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    used: set[str] = field(default_factory=set)

    # ---- fact builders -------------------------------------------------------------------

    def clean(self, key: str) -> None:
        """Give a patent complete evidence and an unrestricted export tag.

        When USPTO records a real co-assignee, the ownership record lists it and every co-owner gets a
        consent record, so the synthetic facts never contradict a real assignment.
        """
        real = self.patents[key].get("_co_assignees", [])
        self.set_ownership(key, "complete", real)
        for co in real:
            self.add_consent(key, co)
        self.set_export(key, "unrestricted", [])

    def set_ownership(
        self, key: str, completeness: str, co_owner_ids: list[str], recorded_at: str = BACKGROUND_RECORDED
    ) -> None:
        self.ownership[key] = label(
            {
                "record_id": f"OWN-{key}",
                "patent_key": key,
                "completeness": completeness,
                "co_owners": co_owner_ids,
                "recorded_at": recorded_at,
                "valid_from": "2000-01-01",
            }
        )

    def add_consent(self, key: str, co_owner_id: str) -> None:
        self.consents.append(
            label(
                {
                    "consent_id": f"CON-{key}-" + re.sub(r"[^A-Z0-9]+", "-", co_owner_id.upper()).strip("-"),
                    "patent_key": key,
                    "co_owner_id": co_owner_id,
                    "scope": "any license in any field and territory",
                    "recorded_at": BACKGROUND_RECORDED,
                }
            )
        )

    def set_export(self, key: str, classification: str, permitted: list[str]) -> None:
        self.export[key] = label(
            {
                "record_id": f"EXP-{key}",
                "patent_key": key,
                "classification": classification,
                "permitted_countries": permitted,
                "recorded_at": BACKGROUND_RECORDED,
            }
        )

    def set_filing(self, key: str, filing_date: str) -> None:
        self.filing[key] = label(
            {
                "record_id": f"FIL-{key}",
                "patent_key": key,
                "filing_date": filing_date,
                "recorded_at": BACKGROUND_RECORDED,
            }
        )

    def agreement(
        self,
        keys: list[str],
        licensee: str,
        exclusivity: str,
        field_concept: str,
        territory: str,
        valid_from: str = GRANT_FROM,
        valid_to: str = GRANT_TO,
        cap: int | None = None,
        executed_on: str = GRANT_EXECUTED,
        recorded_at: str = GRANT_RECORDED,
        supersedes: str | None = None,
        injection: str | None = None,
        seed_notice: str | None = None,
        field_text: str | None = None,
        sublicense: bool | None = None,
    ) -> dict[str, Any]:
        agr_id = f"AGR-{len(self.agreements) + 1:04d}"
        lic = self.licensees[licensee]
        written = self.rng.choice([lic["name"], *lic["variants"]])
        royalty = round(self.rng.uniform(1.5, 6.0), 1)
        minimum = self.rng.choice([5000, 10000, 15000, 25000, 50000])
        sub = self.rng.random() < 0.5 if sublicense is None else sublicense
        rec: dict[str, Any] = {
            "agreement_id": agr_id,
            "record_type": "ExecutedGrant",
            "patent_keys": keys,
            "patent_numbers": [self.patents[k]["patent_number"] or None for k in keys],
            "licensee_id": licensee,
            "licensee_as_written": written,
            "exclusivity": exclusivity,
            "field_concept": field_concept,
            "field_text": field_text or self.tax.field_labels[field_concept].lower(),
            "territory": territory,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "executed_on": executed_on,
            "recorded_at": recorded_at,
            "superseded_at": None,
            "supersedes": supersedes,
            "co_exclusive_cap": cap,
            "sublicense_allowed": sub,
            "confidential": {"royalty_pct": royalty, "minimum_annual_usd": minimum},
            "seed_notice": seed_notice,
            "has_injection": injection is not None,
            "center": self.patents[keys[0]]["center"],
        }
        rec.update(self._render_text(rec, injection))
        self.agreements.append(label(rec))
        return self.agreements[-1]

    def _render_text(self, rec: dict[str, Any], injection: str | None) -> dict[str, Any]:
        t = self.clauses
        nums = []
        for k in rec["patent_keys"]:
            p = self.patents[k]
            if p["patent_number"]:
                nums.append(
                    f"U.S. Patent No. {int(p['patent_number']):,} (NASA Case No. {p['case_number'] or 'not stated'})"
                )
            else:
                nums.append(f"NASA Case No. {p['case_number']}")
        values = {
            "agreement_id": rec["agreement_id"],
            "executed_on_long": long_date(rec["executed_on"]),
            "licensee_as_written": rec["licensee_as_written"],
            "licensee_address": self.licensees[rec["licensee_id"]]["address"],
            "exclusivity_phrase": EXCLUSIVITY_PHRASE[rec["exclusivity"]],
            "patent_list": "; ".join(nums),
            "field_text": rec["field_text"],
            "territory_text": self.tax.territory_labels[rec["territory"]]
            + (f" (ISO 3166 code {rec['territory']})" if len(rec["territory"]) == 2 else ""),
            "valid_from_long": long_date(rec["valid_from"]),
            "valid_to_long": long_date(rec["valid_to"]),
            "royalty_pct": rec["confidential"]["royalty_pct"],
            "minimum_annual_usd": f"{rec['confidential']['minimum_annual_usd']:,}",
            "sublicense_text": SUBLICENSE_TEXT[rec["sublicense_allowed"]],
            "co_exclusive_cap": rec["co_exclusive_cap"],
            "supersedes": rec["supersedes"],
            "injection_text": injection,
            "center": rec["center"],
        }
        order = ["grant", "field", "territory", "term", "royalty", "sublicense"]
        if rec["co_exclusive_cap"] is not None:
            order.append("cap")
        order.append("export")
        if rec["supersedes"]:
            order.append("correction")
        if injection:
            order.append("injection")
        order.append("signature")

        parts = [
            ("title", t["title"].format(**values)),
            ("notice", t["notice"].strip()),
            ("preamble", " ".join(t["preamble"].format(**values).split())),
        ]
        parts += [
            (name, f"Article {i}. " + " ".join(t["clauses"][name].format(**values).split()))
            for i, name in enumerate(order, start=1)
        ]
        text, clauses, pos = "", [], 0
        for name, body in parts:
            if text:
                text += "\n\n"
                pos += 2
            clauses.append(
                {
                    "clause_id": f"{rec['agreement_id']}#{name}",
                    "kind": name,
                    "start": pos,
                    "end": pos + len(body),
                    "text": body,
                }
            )
            text += body
            pos += len(body)
        fact_clause = {
            "patents": "grant",
            "exclusivity": "grant",
            "field": "field",
            "territory": "territory",
            "term": "term",
            "royalty": "royalty",
            "sublicense": "sublicense",
        }
        if rec["co_exclusive_cap"] is not None:
            fact_clause["co_exclusive_cap"] = "cap"
        if rec["supersedes"]:
            fact_clause["supersedes"] = "correction"
        return {
            "text": text,
            "clauses": clauses,
            "fact_clauses": {k: f"{rec['agreement_id']}#{v}" for k, v in fact_clause.items()},
        }

    def proposed_grant(
        self,
        key: str,
        licensee: str,
        exclusivity: str,
        field_concept: str,
        territory: str,
        publication_date: str,
        deadline: str,
    ) -> dict[str, Any]:
        pid = f"SPG-{len(self.proposed) + 1:03d}"
        lic = self.licensees[licensee]
        p = self.patents[key]
        text = (
            f"SYNTHETIC NOTICE. NASA hereby gives notice of its intent to grant {EXCLUSIVITY_PHRASE[exclusivity]} "
            f"patent license in {self.tax.territory_labels[territory]} to practice the invention described and "
            f"claimed in NASA Case No. {p['case_number']} to {lic['name']}, having its principal place of business "
            f"at {lic['address']}. The fields of use may be limited to "
            f"{self.tax.field_labels[field_concept].lower()}. NASA must receive written objections no later than "
            f"{long_date(deadline)}."
        )
        rec = label(
            {
                "notice_id": pid,
                "record_type": "ProposedGrant",
                "patent_keys": [key],
                "licensee_id": licensee,
                "exclusivity": exclusivity,
                "field_concept": field_concept,
                "territory": territory,
                "publication_date": publication_date,
                "objection_deadline": deadline,
                "recorded_at": f"{publication_date}T00:00:00Z",
                "text": text,
            }
        )
        self.proposed.append(rec)
        return rec

    def request(
        self,
        key: str,
        exclusivity: str,
        field_concept: str,
        territory: str = "US",
        licensee: str = REQUESTER,
        start: str = REQ_START,
        end: str = REQ_END,
    ) -> dict[str, Any]:
        rid = f"REQ-{len(self.requests) + 1:04d}"
        p = self.patents[key]
        lic = self.licensees[licensee]
        ident = f"US Patent {int(p['patent_number']):,}" if p["patent_number"] else f"NASA case {p['case_number']}"
        art = "an" if exclusivity[0] in "aeiou" else "a"
        text = (
            f"{lic['name']} wants {art} {exclusivity} license to {ident} for "
            f"{self.tax.field_labels[field_concept].lower()} in {self.tax.territory_labels[territory]} "
            f"from {long_date(start)} to {long_date(end)}."
        )
        rec = label(
            {
                "request_id": rid,
                "patent_key": key,
                "licensee_id": licensee,
                "licensee_country": lic["country"],
                "exclusivity": exclusivity,
                "field_concept": field_concept,
                "territory": territory,
                "start": start,
                "end": end,
                "text": text,
            }
        )
        self.requests.append(rec)
        return rec

    def case(
        self,
        case_type: str,
        description: str,
        req: dict[str, Any],
        expected: dict[str, str],
        verdict: str,
        cutoff: str = CUTOFF,
        **extra: Any,
    ) -> None:
        self.cases.append(
            {
                "case_id": f"INJ-{len(self.cases) + 1:03d}",
                "type": case_type,
                "description": description,
                "request_id": req["request_id"],
                "patent_key": req["patent_key"],
                "as_of": AS_OF,
                "recording_cutoff": cutoff,
                "expected_statuses": expected,
                "expected_verdict": verdict,
                **extra,
            }
        )


def expect(exclusivity: str, **overrides: str) -> dict[str, str]:
    """Rule statuses for a request on a clean patent with no grants and no notices."""
    excl = exclusivity in EXCLUSIVE_TYPES
    base = {
        "R1": PASS,
        "R2": PASS,
        "R3": UNKNOWN if exclusivity == "co-exclusive" else NA,
        "R4": REVIEW if excl else NA,
        "R5": PASS,
        "R6": PASS,
        "R7": REVIEW if excl else NA,
    }
    base.update(overrides)
    return base


def build_cases(w: World, pools: dict[str, list[str]]) -> None:
    """Write every injected case. Expected statuses and verdicts are stated by hand here."""

    def take(pool: str, min_expiration: str = "") -> str:
        key = next(k for k in pools[pool] if (w.patents[k]["_expiration"] or "") >= min_expiration)
        pools[pool].remove(key)
        w.used.add(key)
        return key

    def clean(pool: str = "clean", min_expiration: str = "") -> tuple[str, str]:
        key = take(pool, min_expiration)
        w.clean(key)
        return key, w.patent_field[key]

    nx = "non-exclusive"

    # Baselines.
    k, f = clean()
    r = w.request(k, nx, f)
    w.case(
        "baseline_go",
        "Non-exclusive request on a patent with complete evidence and no grants.",
        r,
        expect(nx),
        GO,
    )
    k, f = clean()
    r = w.request(k, "exclusive", f)
    w.case(
        "exclusive_never_go",
        "Exclusive request with complete evidence and no notice. R4 and R7 need counsel.",
        r,
        expect("exclusive"),
        COUNSEL,
    )

    # R2 exclusive conflicts.
    k, f = clean()
    a = w.agreement([k], "LIC-006", "exclusive", f, "US")
    r = w.request(k, nx, f)
    w.case(
        "r2_exclusive_overlap",
        "An active exclusive grant covers the same field, territory, and term.",
        r,
        expect(nx, R2=FAIL),
        NO_GO,
        conflicting_agreements=[a["agreement_id"]],
    )
    k, f = clean()
    a = w.agreement([k], "LIC-006", "exclusive", w.tax.field_parent[f], "US")
    r = w.request(k, nx, f)
    w.case(
        "r2_field_hierarchy_broad_grant",
        "An exclusive grant on the broader field covers the narrower request.",
        r,
        expect(nx, R2=FAIL),
        NO_GO,
        conflicting_agreements=[a["agreement_id"]],
    )
    k, f = clean()
    a = w.agreement([k], "LIC-006", "exclusive", f, "US")
    r = w.request(k, nx, w.tax.field_parent[f])
    w.case(
        "r2_field_hierarchy_broad_request",
        "A broad request overlaps an exclusive grant on a narrower field.",
        r,
        expect(nx, R2=FAIL),
        NO_GO,
        conflicting_agreements=[a["agreement_id"]],
    )
    k, f = clean()
    a = w.agreement([k], "LIC-006", "exclusive", f, "US")
    r = w.request(k, nx, w.tax.siblings(f)[0])
    w.case(
        "r2_field_sibling_no_conflict",
        "An exclusive grant on a sibling field does not conflict.",
        r,
        expect(nx),
        GO,
        related_agreements=[a["agreement_id"]],
    )
    k, f = clean()
    a = w.agreement([k], "LIC-006", "exclusive", f, "NORTH-AMERICA")
    r = w.request(k, nx, f, territory="US")
    w.case(
        "r2_territory_hierarchy",
        "An exclusive grant for North America covers a United States request.",
        r,
        expect(nx, R2=FAIL),
        NO_GO,
        conflicting_agreements=[a["agreement_id"]],
    )
    k, f = clean()
    a = w.agreement([k], "LIC-006", "exclusive", f, "DE")
    r = w.request(k, nx, f, territory="US")
    w.case(
        "r2_territory_disjoint",
        "An exclusive grant for Germany does not conflict with a United States request.",
        r,
        expect(nx),
        GO,
        related_agreements=[a["agreement_id"]],
    )

    # Temporal cases.
    k, f = clean()
    a = w.agreement([k], "LIC-006", "exclusive", f, "US", valid_from="2020-01-01", valid_to="2027-06-30")
    r = w.request(k, nx, f)
    w.case(
        "temporal_partial_overlap",
        "The grant term ends mid-2027 and overlaps the start of the request.",
        r,
        expect(nx, R2=FAIL),
        NO_GO,
        conflicting_agreements=[a["agreement_id"]],
    )
    k, f = clean()
    a = w.agreement(
        [k],
        "LIC-006",
        "exclusive",
        f,
        "US",
        valid_from="2018-01-01",
        valid_to="2024-12-31",
        executed_on="2017-12-01",
        recorded_at="2018-01-05T00:00:00Z",
    )
    r = w.request(k, nx, f)
    w.case(
        "temporal_expired_grant",
        "An exclusive grant that ended in 2024 does not conflict.",
        r,
        expect(nx),
        GO,
        related_agreements=[a["agreement_id"]],
    )
    k, f = clean(min_expiration="2030-01-02")
    a = w.agreement(
        [k],
        "LIC-006",
        "exclusive",
        f,
        "US",
        valid_from="2032-01-01",
        valid_to="2036-12-31",
        executed_on="2026-03-01",
        recorded_at="2026-03-05T00:00:00Z",
    )
    r = w.request(k, nx, f)
    w.case(
        "temporal_future_grant_no_overlap",
        "A future exclusive grant starts after the requested term ends.",
        r,
        expect(nx),
        GO,
        related_agreements=[a["agreement_id"]],
    )
    r = w.request(k, nx, f, start="2030-01-01", end="2034-12-31")
    w.case(
        "temporal_future_grant_overlap",
        "The same future exclusive grant overlaps a later requested term.",
        r,
        expect(nx, R2=FAIL),
        NO_GO,
        conflicting_agreements=[a["agreement_id"]],
    )

    # Exclusivity combinations from PRD R2.
    k, f = clean()
    a = w.agreement([k], "LIC-006", nx, f, "US")
    r = w.request(k, "exclusive", f)
    w.case(
        "r2_exclusive_request_vs_nonexclusive_grant",
        "An exclusive request conflicts with any overlapping executed grant.",
        r,
        expect("exclusive", R2=FAIL),
        NO_GO,
        conflicting_agreements=[a["agreement_id"]],
    )
    k, f = clean()
    a = w.agreement([k], "LIC-006", nx, f, "US")
    r = w.request(k, nx, f)
    w.case(
        "r2_nonexclusive_vs_nonexclusive",
        "Two non-exclusive licenses in the same field do not conflict.",
        r,
        expect(nx),
        GO,
        related_agreements=[a["agreement_id"]],
    )
    k, f = clean()
    a = w.agreement([k], "LIC-006", "exclusive", f, "US")
    r = w.request(k, "partially exclusive", f)
    w.case(
        "r2_partial_vs_exclusive",
        "A partially exclusive request overlaps an exclusive grant. The spec names this R3; "
        "the adopted PRD rules evaluate it in R2.",
        r,
        expect("partially exclusive", R2=FAIL),
        NO_GO,
        conflicting_agreements=[a["agreement_id"]],
        spec_rule="R3",
    )
    k, f = clean()
    a = w.agreement([k], "LIC-006", nx, f, "US")
    r = w.request(k, "partially exclusive", f)
    w.case(
        "r2_partial_vs_nonexclusive",
        "A partially exclusive request conflicts only with an overlapping exclusive grant.",
        r,
        expect("partially exclusive"),
        COUNSEL,
        related_agreements=[a["agreement_id"]],
    )

    # R2 overlap with another party's proposed grant.
    k, f = clean()
    pg = w.proposed_grant(k, "LIC-010", "exclusive", f, "US", "2026-08-03", "2026-08-18")
    r = w.request(k, nx, f)
    w.case(
        "r2_proposed_grant_other_party",
        "Another party holds an overlapping proposed grant from a notice.",
        r,
        expect(nx, R2=REVIEW),
        COUNSEL,
        related_notices=[pg["notice_id"]],
    )

    # R3 co-exclusive cap.
    k, f = clean()
    a1 = w.agreement([k], "LIC-006", "co-exclusive", f, "US", cap=2)
    a2 = w.agreement([k], "LIC-010", "co-exclusive", f, "US", cap=2)
    pg = w.proposed_grant(k, REQUESTER, "co-exclusive", f, "US", "2026-06-01", "2026-06-16")
    r = w.request(k, "co-exclusive", f)
    w.case(
        "r3_cap_exceeded",
        "Two co-exclusive licensees already hold the field and the cap is two.",
        r,
        expect("co-exclusive", R3=FAIL, R4=PASS),
        NO_GO,
        conflicting_agreements=[a1["agreement_id"], a2["agreement_id"]],
        related_notices=[pg["notice_id"]],
    )
    k, f = clean()
    a = w.agreement([k], "LIC-006", "co-exclusive", f, "US", cap=3)
    pg = w.proposed_grant(k, REQUESTER, "co-exclusive", f, "US", "2026-10-20", "2026-11-04")
    r = w.request(k, "co-exclusive", f)
    w.case(
        "r3_within_cap_window_open",
        "The request stays within the cap, but its own notice window closes after the evaluation date.",
        r,
        expect("co-exclusive", R3=PASS, R4=PENDING),
        HOLD,
        related_agreements=[a["agreement_id"]],
        related_notices=[pg["notice_id"]],
    )
    k, f = clean()
    a = w.agreement([k], "LIC-006", "co-exclusive", f, "US", cap=None)
    pg = w.proposed_grant(k, REQUESTER, "co-exclusive", f, "US", "2026-06-01", "2026-06-16")
    r = w.request(k, "co-exclusive", f)
    w.case(
        "r3_cap_not_recorded",
        "An existing co-exclusive agreement does not state a cap.",
        r,
        expect("co-exclusive", R3=UNKNOWN, R4=PASS),
        COUNSEL,
        related_agreements=[a["agreement_id"]],
        related_notices=[pg["notice_id"]],
    )

    # R4 notice window.
    k, f = clean()
    pg = w.proposed_grant(k, REQUESTER, "exclusive", f, "US", "2026-10-22", "2026-11-06")
    r = w.request(k, "exclusive", f)
    w.case(
        "r4_window_open",
        "The requester's notice window is still open on the evaluation date.",
        r,
        expect("exclusive", R4=PENDING),
        HOLD,
        related_notices=[pg["notice_id"]],
    )
    k, f = clean()
    pg = w.proposed_grant(k, REQUESTER, "exclusive", f, "US", "2026-07-01", "2026-07-16")
    r = w.request(k, "exclusive", f)
    w.case(
        "r4_window_closed",
        "The requester's notice window closed before the evaluation date.",
        r,
        expect("exclusive", R4=PASS),
        COUNSEL,
        related_notices=[pg["notice_id"]],
    )

    # R5 export classification.
    k, f = clean()
    w.set_export(k, "restricted", ["US", "CA"])
    r = w.request(k, nx, f, licensee="LIC-017")
    w.case(
        "r5_restricted_country_outside",
        "The technology is restricted and the licensee is in China.",
        r,
        expect(nx, R5=REVIEW),
        COUNSEL,
    )
    k, f = clean()
    w.set_export(k, "restricted", ["US", "CA"])
    r = w.request(k, nx, f, licensee="LIC-004")
    w.case(
        "r5_restricted_country_permitted",
        "The technology is restricted and the licensee is in Canada.",
        r,
        expect(nx),
        GO,
    )
    k, f = clean()
    del w.export[k]
    # A proposed classification waits in the candidate graph. Until a steward approves it, R5 stays UNKNOWN.
    w.candidates.append(
        label(
            {
                "candidate_id": f"CAND-EXP-{k}",
                "fact_type": "ExportClassification",
                "patent_key": k,
                "classification": "unrestricted",
                "permitted_countries": [],
                "status": "proposed",
                "source": "synthetic export control review",
                "proposed_at": "2026-10-16T00:00:00Z",
            }
        )
    )
    r = w.request(k, nx, f)
    w.case(
        "r5_missing_classification",
        "No export classification exists for the patent.",
        r,
        expect(nx, R5=UNKNOWN),
        NO_DATA,
        after_approval={
            "candidate_id": f"CAND-EXP-{k}",
            "expected_statuses": expect(nx),
            "expected_verdict": GO,
        },
    )

    # R6 co-owner consent.
    k, f = clean()
    w.set_ownership(k, "complete", ["COO-001"])
    # A decoy: a proposed record that leaves out the co-owner. Approving it would hide the missing consent, so
    # the demo shows a steward rejecting it against the recorded assignment.
    w.candidates.append(
        label(
            {
                "candidate_id": f"CAND-OWN-{k}",
                "fact_type": "OwnershipRecord",
                "patent_key": k,
                "completeness": "complete",
                "co_owners": [],
                "status": "proposed",
                "source": "synthetic licensee-supplied ownership summary",
                "proposed_at": "2026-10-17T00:00:00Z",
                "conflicts_with": "the recorded assignment, which lists co-owner COO-001",
            }
        )
    )
    r = w.request(k, nx, f)
    w.case(
        "r6_coowner_without_consent",
        "A co-owner exists and no consent record exists.",
        r,
        expect(nx, R6=REVIEW),
        COUNSEL,
    )
    k, f = clean()
    w.set_ownership(k, "complete", ["COO-002"])
    w.add_consent(k, "COO-002")
    r = w.request(k, nx, f)
    w.case("r6_coowner_with_consent", "A co-owner exists and has consented.", r, expect(nx), GO)
    k, f = clean()
    w.set_ownership(k, "incomplete", [])
    r = w.request(k, nx, f)
    w.case(
        "r6_incomplete_ownership",
        "The ownership record is marked incomplete.",
        r,
        expect(nx, R6=UNKNOWN),
        NO_DATA,
    )
    k, f = clean()
    del w.ownership[k]
    r = w.request(k, nx, f)
    w.case(
        "r6_missing_ownership",
        "No ownership record exists. Absence is not proof of sole ownership.",
        r,
        expect(nx, R6=UNKNOWN),
        NO_DATA,
    )

    # Steward approval story: incomplete ownership, then a candidate fact that completes it.
    k, f = clean()
    w.set_ownership(k, "incomplete", [])
    w.candidates.append(
        label(
            {
                "candidate_id": f"CAND-OWN-{k}",
                "fact_type": "OwnershipRecord",
                "patent_key": k,
                "completeness": "complete",
                "co_owners": [],
                "status": "proposed",
                "source": "synthetic assignment record",
                "proposed_at": "2026-10-15T00:00:00Z",
            }
        )
    )
    r = w.request(k, nx, f)
    w.case(
        "steward_rerun",
        "Ownership is incomplete until a steward approves a complete record with no "
        "co-owners. The rerun after approval must return GO.",
        r,
        expect(nx, R6=UNKNOWN),
        NO_DATA,
        after_approval={
            "candidate_id": f"CAND-OWN-{k}",
            "expected_statuses": expect(nx),
            "expected_verdict": GO,
        },
    )

    # R1 legal status. These cases use real USPTO status wherever it exists.
    k, f = clean("lapsed")
    u = w.patents[k]["_uspto"]
    r = w.request(k, nx, f)
    w.case(
        "r1_lapsed_maintenance_fee",
        f"Real data: the NASA dataset says the patent runs to {w.patents[k]['patent_expiration_date']}, but USPTO "
        f"recorded it expired for unpaid maintenance fees on {u['lapse_events'][-1]['date']}.",
        r,
        {"R1": FAIL},
        NO_GO,
        real_fact_source=u["source_url"],
    )
    k, f = clean("term_ended")
    u = w.patents[k]["_uspto"]
    r = w.request(k, nx, f)
    w.case(
        "r1_term_ended",
        f"Real data: USPTO dates give a term that ended on {u['expiration_computed']}.",
        r,
        {"R1": FAIL},
        NO_GO,
        real_fact_source=u["source_url"],
    )
    if pools["reinstated"]:
        k, f = clean("reinstated")
        u = w.patents[k]["_uspto"]
        r = w.request(k, nx, f)
        w.case(
            "r1_reinstated_after_lapse",
            f"Real data: the patent lapsed on {u['lapse_period'][0]} and USPTO accepted the late fee on "
            f"{u['lapse_period'][1]}, so it is in force. Intervening rights may cover the lapse period.",
            r,
            expect(nx),
            GO,
            real_fact_source=u["source_url"],
        )
    k, f = clean("noexp")
    w.set_filing(k, "2016-05-02")
    r = w.request(k, nx, f)
    w.case(
        "r1_derived_in_force",
        "No USPTO record and no expiration date; a synthetic filing date + 20 years gives 2036-05-02, labeled derived.",
        r,
        expect(nx),
        GO,
        derived_expiration="2036-05-02",
    )
    k, f = clean("noexp")
    w.set_filing(k, "2004-03-15")
    r = w.request(k, nx, f)
    w.case(
        "r1_derived_expired",
        "No USPTO record and no expiration date; a synthetic filing date + 20 years gives 2024-03-15, labeled derived.",
        r,
        {"R1": FAIL},
        NO_GO,
        derived_expiration="2024-03-15",
    )
    k, f = clean("noexp")
    r = w.request(k, nx, f)
    w.case(
        "r1_no_dates",
        "The patent is listed as issued, but no source gives a status, an expiration date, or a filing date.",
        r,
        expect(nx, R1=UNKNOWN),
        NO_DATA,
    )
    if pools["not_granted"]:
        k, f = clean("not_granted")
        u = w.patents[k]["_uspto"]
        r = w.request(k, nx, f)
        w.case(
            "r1_not_issued",
            f"Real data: USPTO status is '{u['status_text'].strip()}', so no patent issued.",
            r,
            {"R1": FAIL},
            NO_GO,
            real_fact_source=u["source_url"],
        )

    # Retroactive correction (bitemporal).
    k, f = clean()
    sib = w.tax.siblings(f)[0]
    original = w.agreement([k], "LIC-006", "exclusive", f, "US", recorded_at="2025-01-10T00:00:00Z")
    corrected = w.agreement(
        [k],
        "LIC-006",
        "exclusive",
        sib,
        "US",
        recorded_at="2026-10-26T00:00:00Z",
        executed_on="2026-05-20",
        supersedes=original["agreement_id"],
    )
    original["superseded_at"] = "2026-10-26T00:00:00Z"
    r = w.request(k, nx, f)
    w.case(
        "retroactive_correction_before",
        "Recorded knowledge before the correction shows an exclusive grant in the requested field.",
        r,
        expect(nx, R2=FAIL),
        NO_GO,
        cutoff="2026-10-25T00:00:00Z",
        conflicting_agreements=[original["agreement_id"]],
    )
    w.case(
        "retroactive_correction_after",
        "After the correction, the grant covers a sibling field from the same "
        "effective date, so the request no longer conflicts.",
        r,
        expect(nx),
        GO,
        related_agreements=[original["agreement_id"], corrected["agreement_id"]],
    )

    # Combiner precedence with several findings at once.
    k, f = clean()
    a = w.agreement([k], "LIC-006", "exclusive", f, "US")
    del w.export[k]
    pg = w.proposed_grant(k, REQUESTER, "exclusive", f, "US", "2026-10-25", "2026-11-09")
    r = w.request(k, "exclusive", f)
    w.case(
        "combiner_fail_dominates",
        "R2 fails, R4 is pending, R5 is unknown, and R7 needs counsel.",
        r,
        expect("exclusive", R2=FAIL, R4=PENDING, R5=UNKNOWN),
        NO_GO,
        conflicting_agreements=[a["agreement_id"]],
        related_notices=[pg["notice_id"]],
    )
    k, f = clean()
    del w.ownership[k]
    w.set_export(k, "restricted", ["US"])
    r = w.request(k, nx, f, licensee="LIC-005")
    w.case(
        "combiner_review_over_unknown",
        "R5 needs counsel and R6 lacks evidence. REVIEW outranks UNKNOWN.",
        r,
        expect(nx, R5=REVIEW, R6=UNKNOWN),
        COUNSEL,
    )

    # PRD demo: exclusive request blocked with secondary findings.
    k, f = clean()
    a = w.agreement([k], "LIC-006", "exclusive", f, "US")
    w.set_export(k, "restricted", ["US"])
    r = w.request(k, "exclusive", f, licensee="LIC-009")
    w.case(
        "demo_blocked_with_secondary",
        "An exclusive request overlaps an executed exclusive grant. R5 and R7 also report findings.",
        r,
        expect("exclusive", R2=FAIL, R5=REVIEW),
        NO_GO,
        conflicting_agreements=[a["agreement_id"]],
    )

    # Prompt injection inside agreement text. Extracted facts must ignore the planted text.
    for i, injection in enumerate(w.clauses["injections"]):
        k, f = clean()
        a = w.agreement([k], "LIC-006", "exclusive", f, "US", injection=injection)
        r = w.request(k, nx, f)
        w.case(
            "prompt_injection",
            f"Agreement text plants instruction {i + 1}. The verdict must not change.",
            r,
            expect(nx, R2=FAIL),
            NO_GO,
            conflicting_agreements=[a["agreement_id"]],
        )


def build_background(w: World, notices: list[dict[str, Any]], free: list[str]) -> None:
    """Fill the rest of the corpus with realistic facts that no injected case depends on."""
    rng = w.rng
    others = [lid for lid in sorted(w.licensees) if lid != REQUESTER]

    # One executed agreement per in-scope real notice, starting after its objection window.
    for n in notices:
        keys = [k for k in n["_scope_keys"] if k not in w.used][:3]
        if not keys:
            continue
        excl = n["exclusivity"]
        if excl in (None, "unspecified"):
            excl = rng.choice(n.get("exclusivity_options") or ["exclusive", "partially exclusive"])
        deadline = n["objection_deadline"] or n["publication_date"]
        start = add_days(deadline, 60)
        cap = rng.choice([2, 3]) if excl == "co-exclusive" else None
        w.agreement(
            keys,
            rng.choice(others),
            excl,
            w.patent_field[keys[0]],
            "US" if (n.get("territory") or "United States").startswith("United States") else "WORLD",
            valid_from=start,
            valid_to=add_days(start, 3650),
            executed_on=add_days(start, -5),
            recorded_at=f"{add_days(start, 10)}T00:00:00Z",
            seed_notice=n["document_number"],
            field_text=n["field_of_use"] or None,
            cap=cap,
        )

    # Random agreements on the remaining free patents until the target count is reached.
    pool = [k for k in free if k not in w.used]
    rng.shuffle(pool)
    while len(w.agreements) < TARGET_AGREEMENTS and pool:
        k = pool.pop()
        excl = rng.choices(["non-exclusive", "exclusive", "partially exclusive", "co-exclusive"], weights=[5, 2, 2, 1])[
            0
        ]
        start = f"{rng.randint(2016, 2026)}-{rng.randint(1, 12):02d}-01"
        concept = w.patent_field[k]
        if rng.random() < 0.3:
            concept = w.tax.field_parent[concept]
        w.agreement(
            [k],
            rng.choice(others),
            excl,
            concept,
            rng.choices(["US", "NORTH-AMERICA", "WORLD", "EUROPE"], weights=[6, 2, 1, 1])[0],
            valid_from=start,
            valid_to=add_days(start, rng.choice([1825, 3650])),
            executed_on=add_days(start, -7),
            recorded_at=f"{add_days(start, 14)}T00:00:00Z",
            cap=rng.choice([2, 3, None]) if excl == "co-exclusive" else None,
        )

    # Ownership, consent, export, and filing facts for every patent that no case controls.
    for k in sorted(w.patents):
        if k in w.used:
            continue
        roll = rng.random()
        real = w.patents[k].get("_co_assignees", [])
        if real:
            # USPTO records a real co-assignee. Consents stay synthetic because no source publishes them.
            w.set_ownership(k, "complete", real)
            for co in real:
                if rng.random() < 0.6:
                    w.add_consent(k, co)
        elif w.patents[k].get("_jointly_owned"):
            co = rng.choice(w.co_owners)["id"]
            w.set_ownership(k, "complete", [co])
            if rng.random() < 0.5:
                w.add_consent(k, co)
        elif roll < 0.65:
            w.set_ownership(k, "complete", [])
        elif roll < 0.80:
            co = rng.choice(w.co_owners)["id"]
            w.set_ownership(k, "complete", [co])
            if rng.random() < 0.6:
                w.add_consent(k, co)
        elif roll < 0.90:
            w.set_ownership(k, "incomplete", [])
        roll = rng.random()
        if roll < 0.60:
            w.set_export(k, "unrestricted", [])
        elif roll < 0.85:
            w.set_export(k, "restricted", rng.choice([["US"], ["US", "CA"], ["US", "CA", "GB", "AU", "JP"]]))
        if not w.patents[k]["_expiration"] and not w.patents[k]["_uspto"].get("filing_date") and rng.random() < 0.5:
            w.set_filing(k, f"{rng.randint(2003, 2020)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}")


def load_world(seed: int) -> tuple[World, list[dict[str, Any]], dict[str, list[str]]]:
    rng = random.Random(seed)
    tax = Taxonomy.load()
    licensees = {r["id"]: r for r in yaml.safe_load((TEMPLATES / "licensees.yaml").read_text())}
    co_owners = yaml.safe_load((TEMPLATES / "co_owners.yaml").read_text())
    clauses = yaml.safe_load((TEMPLATES / "clauses.yaml").read_text())

    with (SCOPE / "patents_in_scope.csv").open() as f:
        rows = list(csv.DictReader(f))
    t2 = {r["tops_id"]: r for r in _read_jsonl(PROCESSED / "t2_portal.jsonl")}
    notices_all = {r["document_number"]: r for r in _read_jsonl(PROCESSED / "federal_register.jsonl")}
    uspto = {r["patent_key"]: r for r in _read_jsonl(PROCESSED / "uspto.jsonl")}
    patents: dict[str, dict[str, Any]] = {}
    patent_field: dict[str, str] = {}
    scope_notice_keys: dict[str, list[str]] = {}
    for r in rows:
        key = r["patent_key"]
        docs = [d for d in r["matched_notices"].split(";") if d]
        u = uspto.get(key, {"found": False})
        patents[key] = {
            **r,
            "_jointly_owned": any(notices_all[d].get("jointly_owned") for d in docs),
            "_uspto": u,
            "_state": u.get("legal_state", "not_found") if u["found"] else "not_found",
            # USPTO dates win over the NASA nominal date when both exist.
            "_expiration": u.get("expiration_computed") or r["patent_expiration_date"] or None,
            "_co_assignees": [f"USPTO:{n}" for n in u.get("co_assignees", [])],
        }
        category = t2[r["tops_id"]]["category"] if r["tops_id"] in t2 else None
        patent_field[key] = tax.concept_for(r["title"], category)
        for d in docs:
            scope_notice_keys.setdefault(d, []).append(key)
    notices = [{**notices_all[d], "_scope_keys": sorted(keys)} for d, keys in sorted(scope_notice_keys.items())]

    def pool(pred: Any, allow_notice: bool = False) -> list[str]:
        keys = sorted(k for k, p in patents.items() if (allow_notice or not p["matched_notices"]) and pred(p))
        rng.shuffle(keys)
        return keys

    pools = {
        # In force according to USPTO, with no recorded co-assignee, through the requested start date.
        "clean": pool(
            lambda p: (
                p["_state"] == "in_force"
                and not p["_co_assignees"]
                and (p["_expiration"] or "") >= "2027-06-01"
                and not p["_uspto"].get("reinstated")
            )
        ),
        # The NASA dataset says in force, but USPTO recorded a maintenance fee lapse.
        "lapsed": pool(lambda p: p["_state"] == "lapsed" and (p["patent_expiration_date"] or "") >= AS_OF),
        "term_ended": pool(lambda p: p["_state"] == "term_ended"),
        "reinstated": pool(lambda p: p["_state"] == "in_force" and p["_uspto"].get("reinstated")),
        "noexp": pool(lambda p: p["_state"] == "not_found" and p["status"] == "Issued" and not p["_expiration"]),
        # Every unissued application in scope matches a notice; the R1 case asserts only R1, so that is harmless.
        "not_granted": pool(lambda p: p["_state"] in ("abandoned", "not_granted"), allow_notice=True),
    }
    world = World(rng, tax, licensees, co_owners, clauses, patents, patent_field)
    return world, notices, pools


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")


def generate(seed: int = 42, out: Path = SYNTHETIC, pdfs: bool = True) -> dict[str, Any]:
    w, notices, pools = load_world(seed)
    build_cases(w, pools)
    free = [k for k in sorted(w.patents) if k not in w.used]
    build_background(w, notices, free)

    out.mkdir(parents=True, exist_ok=True)
    agr_dir = out / "agreements"
    agr_dir.mkdir(exist_ok=True)
    for old in agr_dir.glob("AGR-*"):
        old.unlink()
    for a in w.agreements:
        (agr_dir / f"{a['agreement_id']}.txt").write_text(a["text"])
        a["text_file"] = f"data/synthetic/agreements/{a['agreement_id']}.txt"
        a["pdf_file"] = None
        if pdfs:
            pdf.render(a, agr_dir / f"{a['agreement_id']}.pdf")
            a["pdf_file"] = f"data/synthetic/agreements/{a['agreement_id']}.pdf"

    licensees = [label(v) for _, v in sorted(w.licensees.items())]
    co_owners = [label(c) for c in w.co_owners]
    _write_jsonl(out / "licensees.jsonl", licensees)
    _write_jsonl(out / "co_owners.jsonl", co_owners)
    _write_jsonl(out / "agreements.jsonl", [{k: v for k, v in a.items() if k != "text"} for a in w.agreements])
    _write_jsonl(out / "proposed_grants.jsonl", w.proposed)
    _write_jsonl(out / "ownership.jsonl", [w.ownership[k] for k in sorted(w.ownership)])
    _write_jsonl(out / "consents.jsonl", sorted(w.consents, key=lambda c: c["consent_id"]))
    _write_jsonl(out / "export_classifications.jsonl", [w.export[k] for k in sorted(w.export)])
    _write_jsonl(out / "filing_dates.jsonl", [w.filing[k] for k in sorted(w.filing)])
    _write_jsonl(out / "candidate_facts.jsonl", w.candidates)
    _write_jsonl(out / "requests.jsonl", w.requests)
    (out / "injected_conflicts.json").write_text(
        json.dumps(
            {
                "generated_by": GENERATOR_IRI,
                "seed": seed,
                "as_of": AS_OF,
                "default_recording_cutoff": CUTOFF,
                "precedence": "FAIL > PENDING > REVIEW > UNKNOWN > PASS (GoNoGo spec). NOT_APPLICABLE is ignored.",
                "cases": w.cases,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "manifest.json")
    manifest = {
        "generated_by": GENERATOR_IRI,
        "seed": seed,
        "as_of": AS_OF,
        "counts": {
            "licensees": len(licensees),
            "co_owners": len(co_owners),
            "agreements": len(w.agreements),
            "agreements_seeded_from_real_notices": sum(1 for a in w.agreements if a["seed_notice"]),
            "agreements_by_exclusivity": dict(sorted(Counter(a["exclusivity"] for a in w.agreements).items())),
            "agreement_pdfs": sum(1 for a in w.agreements if a["pdf_file"]),
            "proposed_grants": len(w.proposed),
            "ownership_records": len(w.ownership),
            "ownership_by_kind": dict(
                sorted(
                    Counter(
                        "incomplete"
                        if o["completeness"] == "incomplete"
                        else ("complete_with_co_owners" if o["co_owners"] else "complete_no_co_owners")
                        for o in w.ownership.values()
                    ).items()
                )
            ),
            "patents_without_ownership_record": len(w.patents) - len(w.ownership),
            "ownership_records_with_real_uspto_co_assignees": sum(
                1 for o in w.ownership.values() if any(c.startswith("USPTO:") for c in o["co_owners"])
            ),
            "consents": len(w.consents),
            "export_classifications": len(w.export),
            "export_by_kind": dict(sorted(Counter(e["classification"] for e in w.export.values()).items())),
            "patents_without_export_classification": len(w.patents) - len(w.export),
            "filing_dates": len(w.filing),
            "candidate_facts": len(w.candidates),
            "requests": len(w.requests),
            "injected_cases": len(w.cases),
            "injected_cases_by_verdict": dict(sorted(Counter(c["expected_verdict"] for c in w.cases).items())),
        },
        "sha256": {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
