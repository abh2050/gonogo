"""Build a tiny world for a rule test: a few facts about one patent, over the real ontology and schemes."""

from __future__ import annotations

import re

from rdflib import Graph

from kg import build, materialize
from kg.ns import GRAPH_APPROVED, GRAPH_RELEASE
from kg.store import Store
from rules.engine import evaluate
from rules.model import Request

PREFIXES = """
@prefix id:        <https://w3id.org/gonogo/id/> .
@prefix gng:       <https://w3id.org/gonogo/ontology#> .
@prefix field:     <https://w3id.org/gonogo/field/> .
@prefix territory: <https://w3id.org/gonogo/territory/> .
@prefix excl:      <https://w3id.org/gonogo/exclusivity/> .
@prefix state:     <https://w3id.org/gonogo/legal-state/> .
@prefix policy:    <https://w3id.org/gonogo/policy/> .
@prefix center:    <https://w3id.org/gonogo/center/> .
@prefix prov:      <http://www.w3.org/ns/prov#> .
@prefix dct:       <http://purl.org/dc/terms/> .
@prefix schema:    <https://schema.org/> .
@prefix owl:       <http://www.w3.org/2002/07/owl#> .
@prefix xsd:       <http://www.w3.org/2001/XMLSchema#> .
"""

PATENT = "TST-10001-1"
RECORDED = "2026-10-24T18:00:00Z"
GEN = "<https://w3id.org/gonogo/synth/generator/v0.1>"
BASE = f"""
id:patent/{PATENT} a gng:Patent ; gng:caseNumber "{PATENT}" ; dct:title "Test patent" ; gng:center center:LaRC .
id:run/bulk a gng:BulkLoad ; prov:startedAtTime "{RECORDED}"^^xsd:dateTime .
id:licensee/L1 a gng:Licensee ; schema:legalName "Requester Inc." ; gng:countryCode "US" .
id:licensee/L2 a gng:Licensee ; schema:legalName "Other Party LLC" ; gng:countryCode "CA" .
{GEN} a gng:SyntheticGeneration ; gng:generatorSeed 42 ; prov:startedAtTime "{RECORDED}"^^xsd:dateTime ;
    prov:wasAssociatedWith <https://w3id.org/gonogo/synth/generator> .
<https://w3id.org/gonogo/synth/generator> a gng:Generator .
"""


def facts(
    n: int,
    kind: str,
    body: str,
    *,
    patent: str = PATENT,
    recorded: str = RECORDED,
    valid_from: str = "2020-01-01",
    synthetic: bool = False,
    extra: str = "",
) -> str:
    """A fact node with the common provenance, plus the properties in `body`."""
    run = GEN if synthetic else "id:run/bulk"
    policy = "policy:synthetic-load-v1" if synthetic else "policy:bulk-load-v1"
    props = " ; ".join(p for p in (body.strip().rstrip(";").strip(), extra.strip().rstrip(";").strip()) if p)
    head = (
        f'id:fact/{n} a gng:{kind} ; gng:aboutPatent id:patent/{patent} ; gng:recordedAt "{recorded}"^^xsd:dateTime ; '
        f'gng:validFrom "{valid_from}"^^xsd:date ; prov:wasGeneratedBy {run} ; gng:approvedBy {policy}'
    )
    return f"{head} ; {props} ." if props else f"{head} ."


def store_with(*snippets: str) -> Store:
    release = build.Builder()
    release.build_release()
    body = BASE + "\n".join(snippets)
    # Turtle prefixed names cannot contain "/", so id:patent/X is written out as a full IRI.
    body = re.sub(r"\bid:([A-Za-z0-9_\-]+(?:/[A-Za-z0-9_.\-]+)*)", r"<https://w3id.org/gonogo/id/\1>", body)
    approved = Graph().parse(data=PREFIXES + body, format="turtle")
    graphs = {GRAPH_RELEASE: release.release, GRAPH_APPROVED: approved}
    materialize.apply(graphs)
    return Store(graphs)


def request(**kw: object) -> Request:
    base: dict[str, object] = dict(
        patent_key=PATENT,
        exclusivity="non-exclusive",
        field="lasers",
        territory="US",
        start="2027-01-01",
        end="2031-12-31",
        licensee_name="Requester Inc.",
        licensee_ids=("https://w3id.org/gonogo/id/licensee/L1",),
        licensee_country="US",
    )
    base.update(kw)
    return Request(**base)  # type: ignore[arg-type]


def decide(
    store: Store, req: Request | None = None, *, cutoff: str = "2026-11-01T00:00:00Z", as_of: str = "2026-11-01"
):  # type: ignore[no-untyped-def]
    return evaluate(store, req or request(), cutoff=cutoff, as_of=as_of)


def executed(
    n: int,
    exclusivity: str,
    field: str = "lasers",
    territory: str = "US",
    start: str = "2025-01-01",
    end: str = "2034-12-31",
    licensee: str = "L2",
    cap: int | None = None,
    recorded: str = RECORDED,
) -> str:
    cap_ttl = f"gng:coExclusiveCap {cap} ;" if cap else ""
    body = (
        f"gng:licensee id:licensee/{licensee} ; gng:exclusivityType excl:{exclusivity} ; "
        f"gng:fieldOfUse field:{field} ; gng:territory territory:{territory} ; "
        f'gng:validTo "{end}"^^xsd:date ; {cap_ttl} gng:licenseeNameAsWritten "x" ;'
    )
    return facts(n, "ExecutedGrant", body, valid_from=start, recorded=recorded, synthetic=True)
