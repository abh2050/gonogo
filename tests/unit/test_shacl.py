"""The SHACL shapes must accept good data and reject each kind of bad data.

A shape set that never fails proves nothing. These tests start from a small valid graph, break it one way
at a time, and check that the shapes report a violation on the right node.
"""

from __future__ import annotations

import pytest
from rdflib import Graph, URIRef

from kg import build, materialize, validate
from kg.ns import GRAPH_APPROVED, GRAPH_RELEASE

PREFIXES = """
@prefix ex:        <https://example.org/t/> .
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
@prefix skos:      <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd:       <http://www.w3.org/2001/XMLSchema#> .
"""

GOOD = (
    PREFIXES
    + """
ex:gen a gng:Generator .
ex:run a gng:SyntheticGeneration ; gng:generatorSeed 1 ;
    prov:startedAtTime "2026-01-01T00:00:00Z"^^xsd:dateTime ; prov:wasAssociatedWith ex:gen .
ex:patent a gng:Patent ; gng:caseNumber "TST-10001-1" ; dct:title "A patent" ; gng:center center:LaRC .
ex:coA a gng:CoOwner ; schema:legalName "Co-owner A" .
ex:coB a gng:CoOwner ; schema:legalName "Co-owner B" .
ex:lic a gng:Licensee ; schema:legalName "Licensee Inc." .
ex:doc a gng:LicenseAgreement ; dct:identifier "A1" ; gng:storedAt "a1.pdf" ; gng:fullText "ABCDEFGHIJ" .
ex:clause a gng:Clause ; gng:inDocument ex:doc ; gng:clauseKind "grant" ;
    gng:spanStart "2"^^xsd:nonNegativeInteger ; gng:spanEnd "5"^^xsd:nonNegativeInteger ; gng:spanText "CDE" .
ex:grant a gng:ExecutedGrant ;
    gng:aboutPatent ex:patent ; gng:licensee ex:lic ; gng:licenseeNameAsWritten "Licensee Inc." ;
    gng:fieldOfUse field:optics ; gng:territory territory:US ; gng:exclusivityType excl:exclusive ;
    gng:validFrom "2025-01-01"^^xsd:date ; gng:validTo "2030-12-31"^^xsd:date ;
    gng:executedOn "2024-12-01"^^xsd:date ; gng:executedUnder ex:doc ; gng:sourceClause ex:clause ;
    gng:recordedAt "2025-01-05T00:00:00Z"^^xsd:dateTime ;
    prov:wasGeneratedBy ex:run ; gng:approvedBy policy:synthetic-load-v1 .
ex:own a gng:OwnershipRecord ; gng:aboutPatent ex:patent ; gng:coOwnerListIsComplete true ; gng:coOwner ex:coA ;
    gng:validFrom "2000-01-01"^^xsd:date ; gng:recordedAt "2026-01-15T00:00:00Z"^^xsd:dateTime ;
    prov:wasGeneratedBy ex:run ; gng:approvedBy policy:synthetic-load-v1 .
ex:consent a gng:ConsentRecord ; gng:aboutPatent ex:patent ; gng:consentBy ex:coA ;
    gng:validFrom "2026-01-15"^^xsd:date ; gng:recordedAt "2026-01-15T00:00:00Z"^^xsd:dateTime ;
    prov:wasGeneratedBy ex:run ; gng:approvedBy policy:synthetic-load-v1 .
ex:status a gng:PatentLegalStatus ; gng:aboutPatent ex:patent ; gng:legalState state:in-force ;
    gng:expirationDate "2036-05-02"^^xsd:date ; gng:expirationBasis "filing + 20 years" ; gng:expirationIsDerived true ;
    gng:validFrom "2011-12-13"^^xsd:date ; gng:recordedAt "2026-10-24T18:00:00Z"^^xsd:dateTime ;
    prov:wasGeneratedBy ex:run ; gng:approvedBy policy:synthetic-load-v1 .
ex:notice a gng:LicenseNotice ; dct:identifier "N1" ; gng:fullText "Notice text." .
ex:nclause a gng:Clause ; gng:inDocument ex:notice ; gng:clauseKind "notice" ;
    gng:spanStart "0"^^xsd:nonNegativeInteger ; gng:spanEnd "6"^^xsd:nonNegativeInteger ; gng:spanText "Notice" .
ex:proposed a gng:ProposedGrant ; gng:aboutPatent ex:patent ; gng:licensee ex:lic ; gng:exclusivityType excl:exclusive ;
    gng:announcedIn ex:notice ; gng:sourceClause ex:nclause ; gng:publishedOn "2026-10-20"^^xsd:date ;
    gng:fieldOfUseStatus "not_mentioned" ; gng:objectionDeadline "2026-11-04"^^xsd:date ;
    gng:objectionDeadlineBasis "stated date" ;
    gng:validFrom "2026-10-20"^^xsd:date ; gng:recordedAt "2026-10-24T18:00:00Z"^^xsd:dateTime ;
    prov:wasGeneratedBy ex:run ; gng:approvedBy policy:synthetic-load-v1 .
"""
)


def check(ttl: str, shapes: str = "gonogo-shapes.ttl", release_edit: str = "") -> dict[str, object]:
    release = build.Builder()
    release.build_release()
    if release_edit:
        release.release.parse(data=PREFIXES + release_edit, format="turtle")
    data = Graph().parse(data=ttl, format="turtle")
    graphs = {GRAPH_RELEASE: release.release, GRAPH_APPROVED: data}
    materialize.apply(graphs)
    union = Graph()
    for g in graphs.values():
        for t in g:
            union.add(t)
    return validate.run(union, shapes, "test")


def violates(report: dict[str, object], node: str | None = None) -> bool:
    if report["conforms"]:
        return False
    return node is None or node in str(report["text"])


def test_the_good_graph_conforms() -> None:
    report = check(GOOD)
    assert report["conforms"], report["text"]


@pytest.mark.parametrize(
    ("name", "edit", "node"),
    [
        ("clause text differs from its span", ('gng:spanText "CDE"', 'gng:spanText "XYZ"'), "clause"),
        (
            "executed grant without a field of use",
            ("    gng:fieldOfUse field:optics ; gng:territory", "    gng:territory"),
            "grant",
        ),
        (
            "valid to before valid from",
            ('gng:validTo "2030-12-31"^^xsd:date', 'gng:validTo "2020-12-31"^^xsd:date'),
            "grant",
        ),
        ("consent names an unlisted co-owner", ("gng:consentBy ex:coA", "gng:consentBy ex:coB"), "consent"),
        (
            "fact without provenance",
            (
                "    prov:wasGeneratedBy ex:run ; gng:approvedBy policy:synthetic-load-v1 .\nex:own",
                "    gng:approvedBy policy:synthetic-load-v1 .\nex:own",
            ),
            "grant",
        ),
        ("expiration date without a basis", ('gng:expirationBasis "filing + 20 years" ;', ""), "status"),
        ("deadline without a basis", ('gng:objectionDeadlineBasis "stated date" ;', ""), "proposed"),
        ("ownership record without the completeness flag", ("gng:coOwnerListIsComplete true ;", ""), "own"),
        (
            "lapsed state without a lapse date",
            ("gng:legalState state:in-force", "gng:legalState state:lapsed"),
            "status",
        ),
        (
            "recorded after it was superseded",
            (
                'gng:recordedAt "2025-01-05T00:00:00Z"^^xsd:dateTime ;',
                'gng:recordedAt "2025-01-05T00:00:00Z"^^xsd:dateTime ; '
                'gng:supersededAt "2024-01-01T00:00:00Z"^^xsd:dateTime ;',
            ),
            "grant",
        ),
        (
            "patent number that is not a number",
            ('gng:caseNumber "TST-10001-1" ;', 'gng:caseNumber "TST-10001-1" ; gng:patentNumber "nine" ;'),
            "patent",
        ),
    ],
)
def test_each_kind_of_bad_data_is_rejected(name: str, edit: tuple[str, str], node: str) -> None:
    old, new = edit
    assert old in GOOD, f"fixture drifted for: {name}"
    report = check(GOOD.replace(old, new, 1))
    assert violates(report, f"https://example.org/t/{node}"), f"{name}: {report['text'][:600]}"


def test_a_fact_without_an_approver_fails_the_approval_shapes() -> None:
    bad = GOOD.replace("; gng:approvedBy policy:synthetic-load-v1 .\nex:own", ".\nex:own", 1)
    assert check(GOOD, "approved-shapes.ttl")["conforms"]
    report = check(bad, "approved-shapes.ttl")
    assert violates(report, "https://example.org/t/grant"), report["text"][:600]


def test_a_cycle_in_the_field_hierarchy_is_rejected() -> None:
    # Make Optics a child of Lasers while Lasers is already a child of Optics.
    report = check(GOOD, release_edit="field:optics skos:broader field:lasers .\n")
    assert not report["conforms"]
    assert "own ancestor" in str(report["text"]) or "broader" in str(report["text"])


def test_the_candidate_graph_is_exempt_from_approval_shapes() -> None:
    """A candidate fact has no approver yet, so only the structure shapes apply to it."""
    candidate = GOOD.replace("; gng:approvedBy policy:synthetic-load-v1 .\nex:own", ".\nex:own", 1)
    assert check(candidate, "gonogo-shapes.ttl")["conforms"]
    assert URIRef("https://example.org/t/grant")


def test_a_territory_used_as_a_field_of_use_fails_the_consistency_check() -> None:
    """The range axiom types the territory as a field of use, so SHACL cannot see the mistake.

    The disjointness axiom does, and the pipeline's consistency check turns it into a build failure.
    """
    bad = GOOD.replace("gng:fieldOfUse field:optics", "gng:fieldOfUse territory:US", 1)
    with pytest.raises(materialize.InconsistentGraphError, match="disjointness"):
        check(bad)


def test_a_proposed_grant_cannot_also_be_executed() -> None:
    bad = GOOD.replace("ex:proposed a gng:ProposedGrant ;", "ex:proposed a gng:ProposedGrant , gng:ExecutedGrant ;", 1)
    with pytest.raises(materialize.InconsistentGraphError):
        check(bad)


def test_an_executed_grant_with_an_objection_deadline_fails_the_consistency_check() -> None:
    """The domain of gng:objectionDeadline is the proposed grant, so the closure types this grant as both."""
    bad = GOOD.replace(
        'gng:executedOn "2024-12-01"^^xsd:date ;',
        'gng:executedOn "2024-12-01"^^xsd:date ; gng:objectionDeadline "2026-01-01"^^xsd:date ;',
        1,
    )
    with pytest.raises(materialize.InconsistentGraphError):
        check(bad)
