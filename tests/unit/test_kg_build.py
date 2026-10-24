"""Checks on the built knowledge graph: counts, provenance, confidentiality, and ground truth."""

from __future__ import annotations

import json
from typing import Any

from rdflib import RDF, Graph, Literal, URIRef

from gonogo.paths import PROCESSED, SYNTHETIC
from kg import validate
from kg.ns import (
    GENERATOR_RUN,
    GNG,
    GRAPH_APPROVED,
    GRAPH_CANDIDATE,
    GRAPH_RELEASE,
    GRAPH_ROYALTY,
    PROV,
)
from kg.templates import render

FACT_CLASSES = [
    GNG.Grant,
    GNG.OwnershipRecord,
    GNG.ConsentRecord,
    GNG.ExportClassification,
    GNG.PatentLegalStatus,
    GNG.FilingRecord,
    GNG.RoyaltyTerm,
]
SYNTHETIC_ACTIVITY = URIRef(GENERATOR_RUN)


def count(g: Graph, cls: URIRef) -> int:
    return len(set(g.subjects(RDF.type, cls)))


def jsonl(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (SYNTHETIC / name).read_text().splitlines() if line]


def test_the_graph_matches_the_source_counts(kg_graphs: dict[str, Graph]) -> None:
    approved = kg_graphs[GRAPH_APPROVED]
    manifest = json.loads((SYNTHETIC / "manifest.json").read_text())["counts"]
    scope = json.loads((PROCESSED.parent / "scope" / "scope.meta.json").read_text())
    assert count(approved, GNG.Patent) == scope["patents_in_scope"] == 300
    assert count(approved, GNG.ExecutedGrant) == manifest["agreements"]
    assert count(approved, GNG.LicenseAgreement) == manifest["agreements"]
    assert count(approved, GNG.ProposedGrant) == scope["notices_in_scope"] + manifest["proposed_grants"]
    assert count(approved, GNG.OwnershipRecord) + count(kg_graphs[GRAPH_CANDIDATE], GNG.OwnershipRecord) == (
        manifest["ownership_records"] + manifest["candidate_facts"]
    )
    assert count(approved, GNG.ConsentRecord) == manifest["consents"]
    assert count(approved, GNG.ExportClassification) == manifest["export_classifications"]
    assert count(approved, GNG.FilingRecord) == manifest["filing_dates"]
    assert count(kg_graphs[GRAPH_ROYALTY], GNG.RoyaltyTerm) == manifest["agreements"]


def test_every_fact_has_one_origin_and_an_approver_unless_it_is_a_candidate(kg_graphs: dict[str, Graph]) -> None:
    for name in (GRAPH_APPROVED, GRAPH_ROYALTY):
        g = kg_graphs[name]
        facts = set(g.subjects(RDF.type, GNG.BitemporalFact))
        assert facts
        for fact in facts:
            assert len(list(g.objects(fact, PROV.wasGeneratedBy))) == 1, fact
            assert list(g.objects(fact, GNG.approvedBy)), fact
    candidate = kg_graphs[GRAPH_CANDIDATE]
    for fact in candidate.subjects(RDF.type, GNG.BitemporalFact):
        assert not list(candidate.objects(fact, GNG.approvedBy))


def test_synthetic_facts_carry_the_generator_label_and_real_facts_do_not(kg_graphs: dict[str, Graph]) -> None:
    approved = kg_graphs[GRAPH_APPROVED]
    synthetic_classes = [
        GNG.ExecutedGrant,
        GNG.OwnershipRecord,
        GNG.ConsentRecord,
        GNG.ExportClassification,
        GNG.FilingRecord,
    ]
    for cls in synthetic_classes:
        for fact in approved.subjects(RDF.type, cls):
            assert (fact, PROV.wasGeneratedBy, SYNTHETIC_ACTIVITY) in approved, fact
    real = [f for f in approved.subjects(RDF.type, GNG.PatentLegalStatus)]
    assert real
    for fact in real:
        assert (fact, PROV.wasGeneratedBy, SYNTHETIC_ACTIVITY) not in approved
    # Fictional parties are labeled too, so nobody mistakes them for real organizations.
    for cls in (GNG.CoOwner,):
        for party in approved.subjects(RDF.type, cls):
            is_real_uspto = "/coowner/uspto/" in str(party)
            assert ((party, PROV.wasGeneratedBy, SYNTHETIC_ACTIVITY) in approved) != is_real_uspto, party


def test_real_facts_were_recorded_before_the_synthetic_retroactive_correction(kg_graphs: dict[str, Graph]) -> None:
    """The retroactive-correction cases pick a cutoff after every real fact and before the correction."""
    approved = kg_graphs[GRAPH_APPROVED]
    latest = ""
    for fact in approved.subjects(RDF.type, GNG.BitemporalFact):
        if (fact, PROV.wasGeneratedBy, SYNTHETIC_ACTIVITY) in approved:
            continue
        for t in approved.objects(fact, GNG.recordedAt):
            latest = max(latest, Literal(t).toPython().isoformat())
    assert latest < "2026-10-25", latest


def test_royalty_terms_and_agreement_text_stay_out_of_the_approved_graph(kg_graphs: dict[str, Graph]) -> None:
    approved = kg_graphs[GRAPH_APPROVED]
    royalty = kg_graphs[GRAPH_ROYALTY]
    assert not list(approved.subject_objects(GNG.royaltyPercent))
    assert not list(approved.subject_objects(GNG.minimumAnnualRoyaltyUSD))
    assert not list(approved.subjects(RDF.type, GNG.RoyaltyTerm))
    for o in approved.objects(None, None):
        if isinstance(o, Literal) and "running royalty" in str(o):
            raise AssertionError("royalty wording leaked into the approved graph")
    for agreement in approved.subjects(RDF.type, GNG.LicenseAgreement):
        assert not list(approved.objects(agreement, GNG.fullText))
        assert list(royalty.objects(agreement, GNG.fullText))
    for clause in approved.subjects(RDF.type, GNG.Clause):
        assert str(approved.value(clause, GNG.clauseKind)) != "royalty"


def test_every_undeclared_term_is_caught(kg_graphs: dict[str, Graph]) -> None:
    """A typo such as gng:validFrmo would silently create a new property. Every gng: term must be declared."""
    from kg.build import RELEASE_FILES

    declared = Graph()
    declared.parse(RELEASE_FILES[0])
    known = {s for s in declared.subjects() if isinstance(s, URIRef)}
    namespace = str(GNG)
    undeclared: set[str] = set()
    for name in (GRAPH_APPROVED, GRAPH_CANDIDATE, GRAPH_ROYALTY):
        for _, p, o in kg_graphs[name]:
            if str(p).startswith(namespace) and p not in known:
                undeclared.add(str(p))
            if p == RDF.type and isinstance(o, URIRef) and str(o).startswith(namespace) and o not in known:
                undeclared.add(str(o))
    assert not undeclared, sorted(undeclared)


def test_the_built_graph_conforms_to_the_shapes(kg_graphs: dict[str, Graph]) -> None:
    for report in validate.validate_all(kg_graphs):
        assert report["conforms"], report["text"][:3000]


OVERLAP = """
SELECT DISTINCT ?grant
{{FROM}}
WHERE {
  ?grant a gng:ExecutedGrant ; gng:aboutPatent {{patent}} ; gng:validFrom ?vf ; gng:validTo ?vt .
  {{ASOF ?grant}}
  FILTER(?vf <= {{end}} && ?vt >= {{start}})
  { ?grant gng:coversField {{field}} } UNION { ?grant gng:fieldOfUse/skos:broaderTransitive {{field}} }
  { ?grant gng:coversTerritory {{territory}} } UNION { ?grant gng:territory/skos:broaderTransitive {{territory}} }
}
"""


def test_the_injected_conflicts_can_be_found_by_querying_the_graph(kg_graphs: dict[str, Graph]) -> None:
    """Ground truth from the generator must be discoverable through the ontology's own hierarchy."""
    cases = json.loads((SYNTHETIC / "injected_conflicts.json").read_text())["cases"]
    requests = {r["request_id"]: r for r in jsonl("requests.jsonl")}
    merged = Graph()
    for name in (GRAPH_APPROVED, GRAPH_RELEASE):
        for triple in kg_graphs[name]:
            merged.add(triple)
    checked = 0
    for case in cases:
        wanted = case.get("conflicting_agreements", [])
        if not wanted or case["expected_statuses"].get("R2") != "FAIL":
            continue
        req = requests[case["request_id"]]
        params = {
            "patent": {"iri": "https://w3id.org/gonogo/id/patent/" + req["patent_key"]},
            "field": {"iri": "https://w3id.org/gonogo/field/" + req["field_concept"]},
            "territory": {"iri": "https://w3id.org/gonogo/territory/" + req["territory"]},
            "start": {"date": req["start"]},
            "end": {"date": req["end"]},
            "cutoff": {"datetime": case["recording_cutoff"]},
        }
        query = (
            render(OVERLAP, params, [GRAPH_APPROVED, GRAPH_RELEASE])
            .replace("FROM <" + GRAPH_APPROVED + ">\n", "")
            .replace("FROM <" + GRAPH_RELEASE + ">\n", "")
        )
        found = {str(r["grant"]).rsplit("/", 1)[1] for r in merged.query(query)}
        assert set(wanted) <= found, (case["case_id"], case["type"], wanted, found)
        checked += 1
    expected = sum(1 for c in cases if c.get("conflicting_agreements") and c["expected_statuses"].get("R2") == "FAIL")
    assert checked == expected >= 10


def test_a_correction_changes_the_answer_only_after_its_recording_time(kg_graphs: dict[str, Graph]) -> None:
    cases = {c["type"]: c for c in json.loads((SYNTHETIC / "injected_conflicts.json").read_text())["cases"]}
    before, after = cases["retroactive_correction_before"], cases["retroactive_correction_after"]
    original = before["conflicting_agreements"][0]
    g = kg_graphs[GRAPH_APPROVED]
    grant = next(s for s in g.subjects(GNG.supersededAt, None) if str(s).endswith(original))
    superseded_at = Literal(g.value(grant, GNG.supersededAt)).toPython().isoformat()
    assert (
        before["recording_cutoff"].replace("Z", "+00:00")
        < superseded_at
        <= after["recording_cutoff"].replace("Z", "+00:00")
    )
