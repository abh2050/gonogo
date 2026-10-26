# ADR 0003. RDF stays the system of record; a property graph is a projection

**Status:** Accepted, 2026-10-26
**Scope:** the store behind the rules (`kg/`, `rules/templates/`), and any graph database GoNoGo might add
**Evidence:** `pgraph/` (loader, the Cypher rule, the comparison), `pgraph/results.json`

The build plan numbered this record 0002. Separation of duties took that number in Gate 3, so this is 0003.

## Context

GoNoGo keeps its facts in RDF: an OWL ontology, SKOS vocabularies, SHACL shapes, named graphs, and PROV-O, queried
with SPARQL on Fuseki locally and Neptune on AWS. Many teams would reach for a labeled property graph (Neo4j and
Cypher) instead, because the query language is friendlier and the tooling is popular. This record tests that
choice on the rule where the graph matters most, R2 (overlapping grants), and decides.

## What was compared

`pgraph/load.py` loads the approved grants, the field and territory vocabularies, the patents, the licensees, and the
provenance links into Neo4j 5.26 Community. It makes the choices a property-graph team would make: a grant is a node,
a concept hierarchy is `BROADER` edges, times are properties, and provenance is `DERIVED_FROM` and `APPROVED_BY`
edges. `pgraph/r2.cypher` then states R2 in Cypher, and `pgraph/compare.py` runs both versions of R2 on the same
requests.

**The requests.** All 43 synthetic requests, plus sixteen variations around each of the 120 executed grants: the
grant's own field, its broader field, a narrower field, and a sibling; the grant's own territory and its broader
region; a term that overlaps and one that does not. The superseded grant also runs at two recording cutoffs, before
and after its correction. That is 1,435 requests, and 503 of them have at least one conflicting grant.

## Results

| Question | RDF and SPARQL | Property graph and Cypher |
|---|---|---|
| Same grants returned | 1,435 of 1,435 | 1,435 of 1,435 |
| Query size (lines, without comments) | 14 | 13 |
| Median time per query | 13.3 ms (rdflib, in process) | 3.2 ms (Neo4j server) |
| A grant relates five things (n-ary) | A node of class `gng:ExecutedGrant` with OWL restrictions | A node labeled `ExecutedGrant`, no restrictions |
| Field and territory coverage | Materialized `gng:coversField` plus `skos:broaderTransitive` | A path query, `BROADER*0..`, at read time |
| Facts the rules must never read | A named graph that the query does not name | A `graph` property that every query must filter |
| Who stated a fact, and from what | PROV-O terms on the fact | Edges, or properties on any edge |
| A broken load | SHACL shapes and the competency questions fail the build | Queries return nothing, with a warning |

**The two queries do the same work in about the same space.** Clarity is not a reason to choose either one. The
Cypher path pattern for the hierarchy is easier to read than a materialized closure. In exchange, the RDF closure is
itself a set of facts that the reasoner computes and SHACL checks, so a reader can see it.

**Speed is not the deciding factor.** Neo4j was about four times faster here, but the comparison sets a database
server against an in-process Python library. Every R2 query took milliseconds either way, and Gate 3 showed the
SPARQL rules give identical decisions on Neptune.

**The first comparison found a bug, and that is the most useful result.** The first load used the wrong IRIs for two
concept schemes, so no territory nodes existed. Every Cypher query then returned nothing, quietly: 503 conflicts
went missing, and only a server warning said that a label did not exist. In RDF the same mistake fails loudly,
because SHACL requires every grant's territory to be a known concept and the competency questions expect conflicts.
A property graph has no schema to check the data against, so its safety depends on tests that someone must remember
to write.

## Decision

RDF stays the system of record, for three reasons that the comparison makes concrete.

1. **Named graphs are a security boundary.** The rules must never read the candidate graph, and only finance may
   read royalty terms. In RDF that boundary is the `FROM` clause, and the query service enforces it before a query
   runs (Gate 3, `service/query.py`). In a property graph it is a property filter on every match, and one forgotten
   `WHERE n.graph = 'approved'` leaks unapproved facts into a verdict.
2. **The data checks itself.** OWL disjointness, SHACL shapes, and the competency questions catch a malformed load
   before any rule runs. The bug above is exactly the failure they prevent.
3. **The terms are standards.** PROV-O, SKOS, Dublin Core, and schema.org mean that a reader outside the project
   can follow a fact's provenance without our documentation, and w3id gives every term a permanent address.

A property graph remains a good **projection** for work that is about traversal and not about trust: network
analytics, a licensing dashboard, or graph algorithms over licensees. Such a projection is rebuilt from the approved
graph, is read-only, and never decides a verdict. Neptune can serve both models from one service, so this choice
does not lock out openCypher later.

## Costs of this choice

- SPARQL and Turtle are less familiar to most engineers than Cypher, so onboarding takes longer.
- Coverage is precomputed. A change to a vocabulary needs a rebuild, where a Cypher path query would see the change
  at once. The release workflow (Gate 3) makes that rebuild part of every ontology release.
- Provenance on a single statement needs a named graph or a fact node in RDF, where a property graph can put
  properties on any edge.
