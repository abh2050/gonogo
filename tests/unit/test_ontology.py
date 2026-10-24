"""Structure checks on the ontology, the schemes, and the materialization step."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef
from rdflib.namespace import SKOS

from gonogo.paths import DOCS, ONTOLOGY, PROCESSED, ROOT, SYNTHETIC
from kg import build, materialize
from kg.ns import FIELD, GNG, GRAPH_APPROVED, GRAPH_RELEASE, TERRITORY

ONT = Graph().parse(ONTOLOGY / "gonogo.ttl")
SCHEMES = {p.stem: Graph().parse(p) for p in sorted((ONTOLOGY / "schemes").glob("*.ttl"))}
DEFINITION = SKOS.definition


def own_terms(kind: URIRef) -> list[URIRef]:
    return sorted(s for s in ONT.subjects(RDF.type, kind) if str(s).startswith(str(GNG)))


ALL_TERMS = [t for k in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty) for t in own_terms(k)]


@pytest.mark.parametrize("term", ALL_TERMS, ids=lambda t: str(t).split("#")[1])
def test_every_term_has_a_label_and_a_definition(term: URIRef) -> None:
    assert (term, RDFS.label, None) in ONT, f"{term} has no label"
    assert (term, DEFINITION, None) in ONT, f"{term} has no definition"


def test_the_ontology_declares_what_the_spec_requires() -> None:
    classes = {str(c).split("#")[1] for c in own_terms(OWL.Class)}
    required = {
        "Patent",
        "PatentLegalStatus",
        "NASACenter",
        "Licensee",
        "OwnershipRecord",
        "CoOwner",
        "ConsentRecord",
        "ExportClassification",
        "LicenseNotice",
        "ProposedGrant",
        "ExecutedGrant",
        "Clause",
        "Action",
        "Decision",
        "Grant",
    }
    assert required <= classes, required - classes


def test_proposed_and_executed_grants_are_separate_disjoint_classes() -> None:
    assert (GNG.ExecutedGrant, OWL.disjointWith, GNG.ProposedGrant) in ONT
    assert (GNG.ProposedGrant, RDFS.subClassOf, GNG.Grant) in ONT
    assert (GNG.ExecutedGrant, RDFS.subClassOf, GNG.Grant) in ONT


def test_every_rule_annotation_names_a_real_rule() -> None:
    for _, _, rule in ONT.triples((None, GNG.readByRule, None)):
        assert re.fullmatch(r"R[1-7]", str(rule)), rule


def test_every_modeling_decision_annotation_points_at_a_documented_decision() -> None:
    doc = (DOCS / "modeling-decisions.md").read_text()
    documented = set(re.findall(r"^### (MD\d+)\.", doc, flags=re.M))
    used = {str(o) for _, _, o in ONT.triples((None, GNG.modelingDecision, None))}
    assert used, "the ontology should point at the decisions it implements"
    assert used <= documented, used - documented
    assert len(documented) >= 12


def normalized(label: str) -> str:
    return label.replace(",", "").lower()


def test_field_scheme_is_a_two_level_tree_that_reuses_the_t2_categories() -> None:
    g = SCHEMES["fields"]
    scheme = URIRef("https://w3id.org/gonogo/scheme/field-of-use")
    tops = list(g.objects(scheme, SKOS.hasTopConcept))
    t2 = json.loads((PROCESSED / "t2_portal.meta.json").read_text())["categories"]
    assert {normalized(str(g.value(t, SKOS.prefLabel))) for t in tops} == {normalized(c) for c in t2}
    notations = [str(g.value(c, SKOS.notation)) for c in g.subjects(RDF.type, SKOS.Concept)]
    assert len(notations) == len(set(notations))
    for top in tops:
        kids = list(g.subjects(SKOS.broader, top))
        assert len(kids) >= 2, top
        for kid in kids:
            assert not list(g.subjects(SKOS.broader, kid)), "the field scheme has exactly two levels"
            assert (kid, SKOS.broader, top) in g and (top, SKOS.narrower, kid) in g


def test_territory_scheme_uses_iso_3166_codes_under_regions() -> None:
    g = SCHEMES["territories"]
    countries = list(g.subject_objects(GNG.iso3166Alpha2))
    assert len(countries) == 17
    # Every country that a synthetic licensee sits in must exist in the scheme, or rule R5 could not compare it.
    licensee_countries = {
        json.loads(line)["country"] for line in (SYNTHETIC / "licensees.jsonl").read_text().splitlines()
    }
    assert licensee_countries <= {str(code) for _, code in countries}
    for country, code in countries:
        assert re.fullmatch(r"[A-Z]{2}", str(code))
        assert str(country).endswith("/" + str(code))
        assert list(g.objects(country, SKOS.broader)), f"{country} sits under no region"
    regions = [c for c in g.subjects(RDF.type, SKOS.Concept) if (c, GNG.iso3166Alpha2, None) not in g]
    assert len(regions) == 5  # the world and four commercial regions


def test_exclusivity_scheme_is_flat_and_complete() -> None:
    g = SCHEMES["exclusivity"]
    concepts = {str(c).rsplit("/", 1)[1] for c in g.subjects(RDF.type, SKOS.Concept)}
    assert concepts == {"exclusive", "partially-exclusive", "co-exclusive", "non-exclusive"}
    assert not list(g.subject_objects(SKOS.broader))


def mini_release() -> dict[str, Graph]:
    builder = build.Builder()
    builder.build_release()
    return {GRAPH_RELEASE: builder.release}


def test_materialization_types_concepts_from_their_scheme() -> None:
    graphs = mini_release()
    materialize.apply(graphs)
    g = graphs[GRAPH_RELEASE]
    assert (FIELD["lasers"], RDF.type, GNG.FieldOfUse) in g
    assert (TERRITORY["DE"], RDF.type, GNG.Territory) in g
    assert (FIELD["lasers"], RDF.type, GNG.Territory) not in g


def test_materialization_closes_the_hierarchy_and_derives_coverage() -> None:
    graphs = mini_release()
    graphs[GRAPH_APPROVED] = Graph().parse(
        data="""@prefix gng: <https://w3id.org/gonogo/ontology#> .
                @prefix field: <https://w3id.org/gonogo/field/> .
                @prefix territory: <https://w3id.org/gonogo/territory/> .
                <urn:g> a gng:ExecutedGrant ; gng:fieldOfUse field:optics ; gng:territory territory:NORTH-AMERICA .""",
        format="turtle",
    )
    materialize.apply(graphs)
    release, approved = graphs[GRAPH_RELEASE], graphs[GRAPH_APPROVED]
    assert (TERRITORY["US"], SKOS.broaderTransitive, TERRITORY["WORLD"]) in release
    covers = {str(o).rsplit("/", 1)[1] for o in approved.objects(URIRef("urn:g"), GNG.coversField)}
    assert covers == {"optics", "lasers", "lenses-and-mirrors"}
    reach = {str(o).rsplit("/", 1)[1] for o in approved.objects(URIRef("urn:g"), GNG.coversTerritory)}
    assert reach == {"NORTH-AMERICA", "US", "CA", "MX"}
    assert (URIRef("urn:g"), RDF.type, GNG.Grant) in approved


def test_materialization_keeps_only_readable_triples() -> None:
    graphs = mini_release()
    before = {name: len(g) for name, g in graphs.items()}
    inferred = materialize.materialize(graphs)
    assert {name: len(g) for name, g in graphs.items()} == before, "the inputs must stay unchanged"
    for _, p, o in inferred[GRAPH_RELEASE]:
        assert not str(o).startswith("http://www.w3.org/2002/07/owl#Thing")
        assert p != OWL.sameAs


def test_a_hierarchy_edit_changes_what_a_grant_covers() -> None:
    """The reason fields are SKOS: moving one concept changes which requests a grant reaches."""

    def covers(edit: bool) -> set[str]:
        graphs = mini_release()
        if edit:
            release = graphs[GRAPH_RELEASE]
            release.remove((FIELD["lasers"], SKOS.broader, FIELD["optics"]))
            release.remove((FIELD["optics"], SKOS.narrower, FIELD["lasers"]))
            release.add((FIELD["lasers"], SKOS.broader, FIELD["manufacturing"]))
            release.add((FIELD["manufacturing"], SKOS.narrower, FIELD["lasers"]))
        graphs[GRAPH_APPROVED] = Graph().parse(
            data="""@prefix gng: <https://w3id.org/gonogo/ontology#> .
                    @prefix field: <https://w3id.org/gonogo/field/> .
                    <urn:g> a gng:ExecutedGrant ; gng:fieldOfUse field:optics .""",
            format="turtle",
        )
        materialize.apply(graphs)
        return {str(o).rsplit("/", 1)[1] for o in graphs[GRAPH_APPROVED].objects(URIRef("urn:g"), GNG.coversField)}

    assert "lasers" in covers(edit=False)
    assert "lasers" not in covers(edit=True)


def test_competency_questions_document_lists_all_fifteen() -> None:
    doc = (ONTOLOGY / "competency_questions.md").read_text()
    for rq in sorted((ROOT / "tests" / "cq").glob("[0-9][0-9]_*.rq")):
        assert rq.name in doc, f"{rq.name} is missing from ontology/competency_questions.md"
    assert len(re.findall(r"^## CQ\d\d\.", doc, flags=re.M)) == 15


def test_literal_helper_imports() -> None:
    assert Literal("x") and Path(__file__).exists()
