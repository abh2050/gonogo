"""A deterministic licensee resolver.

It normalizes legal suffixes, scores token and character similarity, and checks addresses when both exist. It
returns one of three outcomes for a pair of names:

  match      the names are identical after normalization (punctuation, legal forms, and spaces removed),
             and no address conflicts
  ambiguous  the names are close enough that a person should decide; the pair goes to the steward queue
  none       the names differ

A steward's approval is the only thing that writes an owl:sameAs link. A resolver outcome of "match" lets a
request find an existing licensee; it never merges two nodes in the graph.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from er.normalize import compact
from er.similarity import address_relation, name_score
from kg.ns import GRAPH_APPROVED, GRAPH_RELEASE
from kg.store import Reader

METHOD = "gonogo-er/1.0"
AMBIGUOUS_FROM = 0.74  # chosen on the development pairs only


@dataclass(frozen=True)
class Outcome:
    status: str  # "match", "ambiguous", or "none"
    score: float
    basis: str
    address: str = "unknown"


def compare(a: str, b: str, address_a: str | None = None, address_b: str | None = None) -> Outcome:
    relation = address_relation(address_a, address_b)
    score = name_score(a, b)
    # Equal after removing legal forms, punctuation, and spaces: "North Wind" and "Northwind" are one name.
    same_name = compact(a) != "" and compact(a) == compact(b)
    if same_name and relation == "conflict":
        return Outcome("ambiguous", score, "same name, but the addresses disagree", relation)
    if same_name:
        return Outcome("match", score, "same name after normalization", relation)
    if relation == "conflict":
        return Outcome("none", score, "different names at different places", relation)
    if score >= AMBIGUOUS_FROM:
        return Outcome("ambiguous", score, f"similar names (score {score})", relation)
    return Outcome("none", score, f"different names (score {score})", relation)


@dataclass
class Party:
    iri: str
    name: str
    variants: list[str] = field(default_factory=list)
    address: str | None = None
    country: str | None = None
    origin: str = "real"

    def names(self) -> list[str]:
        return [self.name, *self.variants]


@dataclass
class Candidate:
    party: Party
    outcome: Outcome


def index_parties(store: Reader) -> list[Party]:
    """Every licensee node in the approved graph, with its alternate spellings."""
    rows = store.select(
        f"""PREFIX gng: <https://w3id.org/gonogo/ontology#> PREFIX schema: <https://schema.org/>
        PREFIX prov: <http://www.w3.org/ns/prov#>
        SELECT ?party ?name ?variant ?address ?country ?synthetic FROM <{GRAPH_APPROVED}> FROM <{GRAPH_RELEASE}>
        WHERE {{ ?party a gng:Licensee ; schema:legalName ?name .
          OPTIONAL {{ ?party gng:nameVariant ?variant }} OPTIONAL {{ ?party gng:registeredAddress ?address }}
          OPTIONAL {{ ?party gng:countryCode ?country }}
          OPTIONAL {{ ?party prov:wasGeneratedBy ?synthetic }} }}"""
    )
    parties: dict[str, Party] = {}
    for r in rows:
        p = parties.setdefault(str(r["party"]), Party(str(r["party"]), str(r["name"])))
        if "variant" in r and str(r["variant"]) not in p.variants:
            p.variants.append(str(r["variant"]))
        p.address = str(r["address"]) if "address" in r else p.address
        p.country = str(r["country"]) if "country" in r else p.country
        if "synthetic" in r:
            p.origin = "synthetic"
    return sorted(parties.values(), key=lambda p: p.iri)


_RANK = {"match": 2, "ambiguous": 1, "none": 0}


def best_outcome(name: str, address: str | None, party: Party) -> Outcome:
    best = Outcome("none", 0.0, "no comparison")
    for other in party.names():
        o = compare(name, other, address, party.address)
        if (_RANK[o.status], o.score) > (_RANK[best.status], best.score):
            best = o
    return best


def resolve(name: str, parties: list[Party], address: str | None = None) -> tuple[str, list[Candidate]]:
    """Resolve a typed name against the licensees in the graph. Returns the status and the ranked candidates."""
    ranked = sorted(
        (Candidate(p, best_outcome(name, address, p)) for p in parties),
        key=lambda c: (-_RANK[c.outcome.status], -c.outcome.score, c.party.iri),
    )
    ranked = [c for c in ranked if c.outcome.status != "none"][:5]
    matches = [c for c in ranked if c.outcome.status == "match"]
    if len(matches) == 1:
        return "match", ranked
    if len(matches) > 1:
        return "ambiguous", ranked  # two nodes carry the same normalized name: a steward should link them
    return ("ambiguous" if ranked else "none"), ranked


def pair_id(a: str, b: str) -> str:
    first, second = sorted((a, b))
    return "link-" + hashlib.sha256(f"{first}|{second}".encode()).hexdigest()[:10]


def propose_links(parties: list[Party], linked: set[frozenset[str]] | None = None) -> list[dict[str, Any]]:
    """Every pair of licensee nodes that might be one organization, for the steward queue."""
    linked = linked or set()
    out: list[dict[str, Any]] = []
    for i, a in enumerate(parties):
        for b in parties[i + 1 :]:
            if frozenset((a.iri, b.iri)) in linked:
                continue
            outcome = best_pair(a, b)
            if outcome.status == "none":
                continue
            out.append(
                {
                    "id": pair_id(a.iri, b.iri),
                    "a": {"iri": a.iri, "name": a.name, "address": a.address, "origin": a.origin},
                    "b": {"iri": b.iri, "name": b.name, "address": b.address, "origin": b.origin},
                    "score": outcome.score,
                    "status": outcome.status,
                    "basis": outcome.basis,
                    "method": METHOD,
                }
            )
    return sorted(out, key=lambda p: (-p["score"], p["id"]))


def best_pair(a: Party, b: Party) -> Outcome:
    best = Outcome("none", 0.0, "no comparison")
    for x in a.names():
        for y in b.names():
            o = compare(x, y, a.address, b.address)
            if (_RANK[o.status], o.score) > (_RANK[best.status], best.score):
                best = o
    return best
