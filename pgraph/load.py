"""Load the approved grants, the vocabularies, and their provenance into Neo4j as a labeled property graph.

    docker compose up -d --wait neo4j
    uv run python -m pgraph.load

Neo4j is a comparison only (docs/adr/0003-rdf-versus-property-graph.md). The RDF graph stays the system of record.
The mapping makes the choices a property-graph team would make:

- A grant is a node, because it relates a patent, a licensee, a field, a territory, and a term: an n-ary relation
  that an edge cannot hold.
- Fields and territories are nodes with BROADER edges. Coverage is a path query, not a stored closure.
- Bitemporal times are node properties. The recording cutoff becomes a WHERE clause in every query.
- A property graph has no named graphs, so each node carries a `graph` property, and every query must filter it.
- Provenance is a DERIVED_FROM edge to the source document and an APPROVED_BY edge to the approver.
"""

from __future__ import annotations

import os
from typing import Any

from neo4j import Driver, GraphDatabase
from rdflib import RDF, Graph, URIRef
from rdflib.namespace import SKOS

from eval.corpus import doc_id
from kg.ns import GNG, GRAPH_APPROVED, GRAPH_RELEASE
from kg.store import Store

PROV_DERIVED = URIRef("http://www.w3.org/ns/prov#wasDerivedFrom")
SCHEMA_NAME = URIRef("https://schema.org/legalName")


def driver() -> Driver:
    password = os.environ.get("NEO4J_PASSWORD", "gonogo-local")
    return GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", password))


def one(g: Graph, s: Any, p: Any) -> Any:
    return next(g.objects(s, p), None)


def rows(store: Store) -> dict[str, list[dict[str, Any]]]:
    a, r = store.base[GRAPH_APPROVED], store.base[GRAPH_RELEASE]
    out: dict[str, list[dict[str, Any]]] = {"concepts": [], "broader": [], "patents": [], "grants": []}
    for scheme, label in (("field-of-use", "Field"), ("territory", "Territory")):
        scheme_iri = URIRef(f"https://w3id.org/gonogo/scheme/{scheme}")
        for c in r.subjects(SKOS.inScheme, scheme_iri):
            out["concepts"].append({"id": doc_id(str(c)), "label": str(one(r, c, SKOS.prefLabel)), "kind": label})
            for b in r.objects(c, SKOS.broader):
                out["broader"].append({"from": doc_id(str(c)), "to": doc_id(str(b)), "kind": label})
    for p in a.subjects(RDF.type, GNG.Patent):
        out["patents"].append({"key": doc_id(str(p))})
    for cls, kind in ((GNG.ExecutedGrant, "ExecutedGrant"), (GNG.ProposedGrant, "ProposedGrant")):
        for g in a.subjects(RDF.type, cls):
            lic = one(a, g, GNG.licensee)
            out["grants"].append(
                {
                    "id": doc_id(str(g)),
                    "kind": kind,
                    "patents": sorted({doc_id(str(x)) for x in a.objects(g, GNG.aboutPatent)}),
                    "exclusivity": doc_id(str(one(a, g, GNG.exclusivityType) or "")) or None,
                    "field": doc_id(str(f)) if (f := one(a, g, GNG.fieldOfUse)) else None,
                    "territory": doc_id(str(t)) if (t := one(a, g, GNG.territory)) else None,
                    "validFrom": str(v) if (v := one(a, g, GNG.validFrom)) else None,
                    "validTo": str(v) if (v := one(a, g, GNG.validTo)) else None,
                    "recordedAt": str(one(a, g, GNG.recordedAt)),
                    "supersededAt": str(v) if (v := one(a, g, GNG.supersededAt)) else None,
                    "cap": int(str(v)) if (v := one(a, g, GNG.coExclusiveCap)) else None,
                    "licensee": str(lic) if lic else None,
                    "licenseeName": str(one(a, lic, SCHEMA_NAME) or "") if lic else None,
                    "documents": sorted(
                        {doc_id(str(d)) for d in a.objects(g, PROV_DERIVED) if "/clause/" not in str(d)}
                    ),
                    "approvedBy": str(one(a, g, GNG.approvedBy) or ""),
                }
            )
    return out


LOAD = [
    "MATCH (n) DETACH DELETE n",
    "UNWIND $concepts AS c CALL (c) { WITH c WHERE c.kind = 'Field' MERGE (:Field {id: c.id, label: c.label}) }"
    " CALL (c) { WITH c WHERE c.kind = 'Territory' MERGE (:Territory {id: c.id, label: c.label}) }",
    "UNWIND $broader AS b MATCH (x {id: b.from}), (y {id: b.to}) WHERE labels(x) = labels(y) MERGE (x)-[:BROADER]->(y)",
    "UNWIND $patents AS p MERGE (:Patent {key: p.key})",
    """UNWIND $grants AS g
    CREATE (n:Grant {id: g.id, graph: 'approved', exclusivity: g.exclusivity, cap: g.cap,
                     validFrom: CASE WHEN g.validFrom IS NULL THEN NULL ELSE date(g.validFrom) END,
                     validTo: CASE WHEN g.validTo IS NULL THEN NULL ELSE date(g.validTo) END,
                     recordedAt: datetime(g.recordedAt),
                     supersededAt: CASE WHEN g.supersededAt IS NULL THEN NULL ELSE datetime(g.supersededAt) END})
    WITH n, g CALL (n, g) { WITH n, g WHERE g.kind = 'ExecutedGrant' SET n:ExecutedGrant }
    CALL (n, g) { WITH n, g WHERE g.kind = 'ProposedGrant' SET n:ProposedGrant }
    WITH n, g UNWIND g.patents AS key MATCH (p:Patent {key: key}) MERGE (n)-[:ABOUT]->(p)
    WITH DISTINCT n, g OPTIONAL MATCH (f:Field {id: g.field}) FOREACH (_ IN CASE WHEN f IS NULL THEN [] ELSE [1] END |
        MERGE (n)-[:FIELD]->(f))
    WITH n, g OPTIONAL MATCH (t:Territory {id: g.territory}) FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END |
        MERGE (n)-[:TERRITORY]->(t))
    WITH n, g FOREACH (_ IN CASE WHEN g.licensee IS NULL THEN [] ELSE [1] END |
        MERGE (l:Licensee {iri: g.licensee}) ON CREATE SET l.name = g.licenseeName MERGE (n)-[:LICENSEE]->(l))
    WITH n, g UNWIND (CASE WHEN size(g.documents) = 0 THEN [NULL] ELSE g.documents END) AS d
    FOREACH (_ IN CASE WHEN d IS NULL THEN [] ELSE [1] END |
        MERGE (doc:Document {id: d}) MERGE (n)-[:DERIVED_FROM]->(doc))
    WITH DISTINCT n, g MERGE (a:Agent {iri: g.approvedBy}) MERGE (n)-[:APPROVED_BY]->(a)""",
]


def load(store: Store | None = None) -> dict[str, int]:
    data = rows(store or Store.from_build())
    with driver() as d, d.session() as s:
        for q in LOAD:
            s.run(q, parameters=dict(data)).consume()
        counts = s.run("MATCH (n) RETURN count(n) AS nodes").single()
        rels = s.run("MATCH ()-[r]->() RETURN count(r) AS rels").single()
    return {"nodes": counts["nodes"] if counts else 0, "relationships": rels["rels"] if rels else 0}


if __name__ == "__main__":
    print(load())
