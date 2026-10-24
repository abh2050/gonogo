"""Export the data that the UI visualizations read: python -m kg.export_viz

Writes JSON files to ui/public/data/. Every number on screen comes from the ontology files, the processed
data, or the built graph, never from a hand-typed constant.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef
from rdflib.namespace import SKOS
from rdflib.term import Node

from gonogo.paths import ONTOLOGY, PROCESSED, ROOT, SCOPE, SYNTHETIC
from kg import build, materialize
from kg.ns import GENERATOR_RUN, GNG, GRAPH_APPROVED, GRAPH_RELEASE, PROV

OUT = ROOT / "ui" / "public" / "data"

KIND_BY_CLASS = {
    "fact": [
        "BitemporalFact",
        "Grant",
        "ProposedGrant",
        "ExecutedGrant",
        "OwnershipRecord",
        "ConsentRecord",
        "ExportClassification",
        "RestrictedExport",
        "UnrestrictedExport",
        "PatentLegalStatus",
        "FilingRecord",
        "RoyaltyTerm",
    ],
    "thing": ["Patent", "NASACenter"],
    "party": ["Licensee", "CoOwner", "Steward", "ApprovalPolicy", "Generator"],
    "document": ["SourceDocument", "LicenseNotice", "LicenseAgreement", "RegistryRecord", "Clause"],
    "vocabulary": ["FieldOfUse", "Territory", "ExclusivityType", "LegalState"],
    "process": [
        "FactGeneration",
        "BulkLoad",
        "Extraction",
        "SyntheticGeneration",
        "Action",
        "SubmitClearanceRequest",
        "ProposeFacts",
        "ApproveFact",
        "RejectFact",
        "CorrectFact",
        "OverrideVerdict",
        "PublishRelease",
        "ClearanceRequest",
        "Decision",
    ],
}
KIND = {c: k for k, names in KIND_BY_CLASS.items() for c in names}
EXTERNAL = {
    "http://www.w3.org/ns/prov#Entity": "prov:Entity",
    "http://www.w3.org/ns/prov#Activity": "prov:Activity",
    "http://www.w3.org/ns/prov#Agent": "prov:Agent",
    "http://www.w3.org/ns/prov#Person": "prov:Person",
    "http://www.w3.org/ns/prov#SoftwareAgent": "prov:SoftwareAgent",
    "https://schema.org/Organization": "schema:Organization",
    "http://www.w3.org/2004/02/skos/core#Concept": "skos:Concept",
}
NS = str(GNG)


def local(node: Any) -> str:
    return str(node).split("#")[-1].split("/")[-1]


def uris(nodes: Iterable[Node]) -> list[URIRef]:
    """Only the IRIs, sorted, so the exported files are identical on every machine."""
    return sorted((n for n in nodes if isinstance(n, URIRef)), key=str)


def text(g: Graph, node: Node, pred: URIRef) -> str:
    value = g.value(node, pred)
    return str(value) if value is not None else ""


def ontology_json() -> dict[str, Any]:
    g = Graph().parse(ONTOLOGY / "gonogo.ttl")
    nodes: dict[str, dict[str, Any]] = {}
    for c in uris(g.subjects(RDF.type, OWL.Class)):
        if isinstance(c, URIRef) and str(c).startswith(NS):
            name = local(c)
            nodes[name] = {
                "id": name,
                "label": text(g, c, RDFS.label),
                "definition": text(g, c, SKOS.definition),
                "comment": text(g, c, RDFS.comment),
                "kind": KIND[name],
                "external": False,
                "rules": sorted(str(o) for o in g.objects(c, GNG.readByRule)),
                "decisions": sorted(str(o) for o in g.objects(c, GNG.modelingDecision)),
                "datatypeProperties": [],
            }
    edges: list[dict[str, str]] = []
    for c in uris(g.subjects(RDF.type, OWL.Class)):
        if not (isinstance(c, URIRef) and str(c).startswith(NS)):
            continue
        for parent in g.objects(c, RDFS.subClassOf):
            if not isinstance(parent, URIRef):
                continue
            if str(parent).startswith(NS):
                edges.append({"source": local(c), "target": local(parent), "kind": "subclass", "label": "subclass of"})
            elif str(parent) in EXTERNAL:
                name = EXTERNAL[str(parent)]
                nodes.setdefault(
                    name,
                    {
                        "id": name,
                        "label": name,
                        "definition": "",
                        "comment": "",
                        "kind": "external",
                        "external": True,
                        "rules": [],
                        "decisions": [],
                        "datatypeProperties": [],
                    },
                )
                edges.append({"source": local(c), "target": name, "kind": "subclass", "label": "subclass of"})
    for p in uris(g.subjects(RDF.type, OWL.ObjectProperty)):
        if not str(p).startswith(NS):
            continue
        domain, rng = g.value(p, RDFS.domain), g.value(p, RDFS.range)
        if isinstance(domain, URIRef) and isinstance(rng, URIRef) and local(domain) in nodes and local(rng) in nodes:
            chain = g.value(p, OWL.propertyChainAxiom) is not None
            edges.append(
                {
                    "source": local(domain),
                    "target": local(rng),
                    "kind": "chain" if chain else "property",
                    "label": local(p),
                    "definition": text(g, p, SKOS.definition),
                    "rules": ",".join(sorted(str(o) for o in g.objects(p, GNG.readByRule))),
                }
            )
    for p in uris(g.subjects(RDF.type, OWL.DatatypeProperty)):
        domain = g.value(p, RDFS.domain)
        if str(p).startswith(NS) and isinstance(domain, URIRef) and local(domain) in nodes:
            nodes[local(domain)]["datatypeProperties"].append(
                {"name": local(p), "definition": text(g, p, SKOS.definition)}
            )
    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "counts": {
            "classes": sum(1 for n in nodes.values() if not n["external"]),
            "objectProperties": sum(1 for p in g.subjects(RDF.type, OWL.ObjectProperty) if str(p).startswith(NS)),
            "datatypeProperties": sum(1 for p in g.subjects(RDF.type, OWL.DatatypeProperty) if str(p).startswith(NS)),
        },
    }


def scheme_json(path: Path, scheme_iri: str) -> dict[str, Any]:
    g = Graph().parse(path)

    def node(c: URIRef) -> dict[str, Any]:
        kids = sorted(
            (k for k in g.subjects(SKOS.broader, c) if isinstance(k, URIRef)),
            key=lambda k: str(g.value(k, SKOS.notation)),
        )
        out: dict[str, Any] = {
            "id": local(c),
            "label": text(g, c, SKOS.prefLabel),
            "notation": text(g, c, SKOS.notation),
        }
        if (c, GNG.iso3166Alpha2, None) in g:
            out["iso"] = text(g, c, GNG.iso3166Alpha2)
        definition = text(g, c, SKOS.definition)
        if definition:
            out["definition"] = definition
        if kids:
            out["children"] = [node(k) for k in kids]
        return out

    tops = sorted(
        (t for t in g.objects(URIRef(scheme_iri), SKOS.hasTopConcept) if isinstance(t, URIRef)),
        key=lambda k: str(g.value(k, SKOS.notation)),
    )
    return {
        "title": text(g, URIRef(scheme_iri), URIRef("http://purl.org/dc/terms/title")),
        "tops": [node(t) for t in tops],
    }


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def findings_json(graphs: dict[str, Graph]) -> dict[str, Any]:
    uspto_all = jsonl(PROCESSED / "uspto.jsonl")
    found = [r for r in uspto_all if r["found"]]
    nasa_live = [r for r in found if r["nasa_says_in_force"]]
    states = Counter(r["legal_state"] for r in nasa_live)

    lapsed = []
    for r in nasa_live:
        if r["legal_state"] != "lapsed" or not r["lapse_events"] or not r["nasa_expiration_date"]:
            continue
        lapse = r["lapse_events"][-1]["date"]
        years = (date.fromisoformat(r["nasa_expiration_date"]) - date.fromisoformat(lapse)).days / 365.25
        lapsed.append(
            {
                "key": r["patent_key"],
                "lapse": lapse,
                "nasaExpires": r["nasa_expiration_date"],
                "phantomYears": round(years, 2),
            }
        )
    lapsed.sort(key=lambda r: r["lapse"])

    scope = json.loads((SCOPE / "scope.meta.json").read_text())
    centers = set(scope["centers"])
    listed_as_application = sum(
        1 for r in jsonl(PROCESSED / "nasa_patents.jsonl") if r["center"] in centers and r["status"] == "Application"
    )
    fr = json.loads((PROCESSED / "federal_register.meta.json").read_text())
    us = json.loads((PROCESSED / "uspto.meta.json").read_text())
    synthetic = json.loads((SYNTHETIC / "manifest.json").read_text())["counts"]
    approved = graphs[GRAPH_APPROVED]
    generator = URIRef(GENERATOR_RUN)
    by_class: dict[str, dict[str, int]] = {}
    for cls in (
        "ExecutedGrant",
        "ProposedGrant",
        "PatentLegalStatus",
        "OwnershipRecord",
        "ConsentRecord",
        "ExportClassification",
        "FilingRecord",
    ):
        facts = set(approved.subjects(RDF.type, GNG[cls]))
        synthetic_n = sum(1 for f in facts if (f, PROV.wasGeneratedBy, generator) in approved)
        by_class[cls] = {"real": len(facts) - synthetic_n, "synthetic": synthetic_n}

    records = jsonl(PROCESSED / "federal_register.jsonl")
    return {
        "legalStatus": {
            "nasaCallsInForce": len(nasa_live),
            "states": dict(states),
            "phantomYearsMedian": round(statistics.median(r["phantomYears"] for r in lapsed), 1) if lapsed else 0,
            "lapsed": lapsed,
        },
        "applications": {
            "listedAsApplication": listed_as_application,
            "nowGranted": us["nasa_application_now_granted"],
        },
        "noticeMatch": {
            "total": scope["notices_total"],
            "datasetOnly": scope["notices_matched_dataset_only"],
            "withT2": scope["notices_matched_any_patent"],
        },
        "extraction": {
            "total": fr["records"],
            "licensee": fr["with_licensee"],
            "territory": fr["with_territory"],
            "deadline": fr["with_objection_deadline"],
            "specificExclusivity": sum(1 for r in records if r["exclusivity"] not in (None, "unspecified")),
            "fieldStated": fr["field_of_use_status_counts"].get("stated", 0),
        },
        "factsByClass": by_class,
        "scope": {
            "patents": scope["patents_in_scope"],
            "byCenter": scope["patents_in_scope_by_center"],
            "byUsptoState": scope["patents_in_scope_by_uspto_state"],
            "notices": scope["notices_in_scope"],
        },
        "synthetic": {
            "agreements": synthetic["agreements"],
            "injectedCases": synthetic["injected_cases"],
            "verdicts": synthetic["injected_cases_by_verdict"],
        },
        "uspto": {"candidates": us["candidates"], "found": us["found"]},
    }


def bitemporal_json(graphs: dict[str, Graph]) -> dict[str, Any]:
    """The retroactive-correction case from the injected ground truth, read back out of the graph."""
    cases = {c["type"]: c for c in json.loads((SYNTHETIC / "injected_conflicts.json").read_text())["cases"]}
    before, after = cases["retroactive_correction_before"], cases["retroactive_correction_after"]
    approved, release = graphs[GRAPH_APPROVED], graphs[GRAPH_RELEASE]
    facts = []
    for agreement in after["related_agreements"]:
        grant = next(s for s in approved.subjects(RDF.type, GNG.ExecutedGrant) if str(s).endswith("/" + agreement))
        field = approved.value(grant, GNG.fieldOfUse)
        superseded = approved.value(grant, GNG.supersededAt)
        facts.append(
            {
                "id": agreement,
                "field": text(release, field, SKOS.prefLabel) if isinstance(field, URIRef) else "",
                "validFrom": str(approved.value(grant, GNG.validFrom)),
                "validTo": str(approved.value(grant, GNG.validTo)),
                "recordedAt": Literal(approved.value(grant, GNG.recordedAt)).toPython().isoformat(),
                "supersededAt": Literal(superseded).toPython().isoformat() if superseded is not None else None,
                "supersedes": [local(o) for o in approved.objects(grant, GNG.supersedes)],
            }
        )
    request_id = before["request_id"]
    request = next(r for r in jsonl(SYNTHETIC / "requests.jsonl") if r["request_id"] == request_id)
    request_field = release.value(URIRef("https://w3id.org/gonogo/field/" + request["field_concept"]), SKOS.prefLabel)
    return {
        "patent": before["patent_key"],
        "requestText": request["text"],
        "requestField": str(request_field),
        "requestExclusivity": request["exclusivity"],
        "facts": facts,
        "cutoffBefore": before["recording_cutoff"],
        "cutoffAfter": after["recording_cutoff"],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    graphs = build.build_graphs()
    materialize.apply(graphs)
    files = {
        "ontology.json": ontology_json(),
        "fields.json": scheme_json(ONTOLOGY / "schemes" / "fields.ttl", "https://w3id.org/gonogo/scheme/field-of-use"),
        "territories.json": scheme_json(
            ONTOLOGY / "schemes" / "territories.ttl", "https://w3id.org/gonogo/scheme/territory"
        ),
        "findings.json": findings_json(graphs),
        "bitemporal.json": bitemporal_json(graphs),
    }
    for name, payload in files.items():
        (OUT / name).write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
        print(f"wrote ui/public/data/{name}")


if __name__ == "__main__":
    main()
