"""Materialize inference before load.

Neptune does not reason at query time, so the pipeline computes the OWL 2 RL closure with owlrl and
writes the entailments that rules need into the graphs. The closure covers:

  * class membership from defined classes   (a concept in the field scheme is a FieldOfUse)
  * subclass typing                         (an ExecutedGrant is a Grant and a BitemporalFact)
  * SKOS transitive hierarchies             (skos:broaderTransitive, skos:narrowerTransitive)
  * rights coverage by property chain       (gng:coversField, gng:coversTerritory)
  * sub-property entailments                (prov:wasDerivedFrom, prov:wasAttributedTo)
  * inverses                                (skos:broader/narrower, gng:supersededBy)

owlrl also derives many trivial triples (reflexive owl:sameAs, owl:Thing typing, blank-node classes).
Only the whitelisted predicates below are kept, so the loaded graphs stay readable.

Range and domain axioms type whatever a property points at, so a grant that names a territory as its
field of use would turn that territory into a FieldOfUse and satisfy a SHACL class check. The disjointness
axioms are what reject the mistake, so the closure is followed by a check that no individual belongs to two
disjoint classes. HermiT performs the full check on the ontology and a sample (scripts/robot.sh); this
check covers every individual in the real graphs, cheaply.
"""

from __future__ import annotations

from collections import defaultdict

import owlrl
from rdflib import OWL, RDF, RDFS, Graph, URIRef
from rdflib.collection import Collection
from rdflib.term import Node

from kg.ns import DCT, GNG, GRAPH_RELEASE, PROV, SCHEMA, SKOS

KEPT_NAMESPACES = (str(GNG), str(SKOS), str(PROV), str(SCHEMA), str(DCT))
KEPT_PREDICATES = {
    SKOS.broader,
    SKOS.narrower,
    SKOS.broaderTransitive,
    SKOS.narrowerTransitive,
    SKOS.inScheme,
    SKOS.hasTopConcept,
    SKOS.topConceptOf,
    GNG.coversField,
    GNG.coversTerritory,
    GNG.supersededBy,
    PROV.wasDerivedFrom,
    PROV.wasAttributedTo,
}
# Large literals do not take part in reasoning, so they stay out of the closure for speed.
SKIPPED_PREDICATES = {GNG.fullText, GNG.spanText, GNG.spanStart, GNG.spanEnd}


def _keep(s: Node, p: Node, o: Node) -> bool:
    if not isinstance(s, URIRef):
        return False
    if p == RDF.type:
        return isinstance(o, URIRef) and str(o).startswith(KEPT_NAMESPACES)
    if p == RDFS.subClassOf:
        return isinstance(o, URIRef) and str(o).startswith(KEPT_NAMESPACES) and str(s).startswith(KEPT_NAMESPACES)
    return p in KEPT_PREDICATES and isinstance(o, URIRef)


def kept(s: Node, p: Node, o: Node) -> bool:
    """Whether an entailed triple is one the graphs store (the whitelist above)."""
    return _keep(s, p, o)


class InconsistentGraphError(ValueError):
    """Raised when an individual belongs to two disjoint classes after the closure."""

    def __init__(self, problems: list[tuple[Node, Node, Node]]) -> None:
        self.problems = problems
        shown = "; ".join(f"{x} is both {a} and {b}" for x, a, b in problems[:5])
        super().__init__(f"{len(problems)} disjointness violations: {shown}")


def disjoint_pairs(g: Graph) -> set[frozenset[Node]]:
    pairs: set[frozenset[Node]] = set()
    for a, b in g.subject_objects(OWL.disjointWith):
        if isinstance(a, URIRef) and isinstance(b, URIRef):
            pairs.add(frozenset((a, b)))
    for node in g.subjects(RDF.type, OWL.AllDisjointClasses):
        head = g.value(node, OWL.members)
        members = [m for m in Collection(g, head) if isinstance(m, URIRef)] if head else []
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                pairs.add(frozenset((a, b)))
    return pairs


def disjointness_violations(g: Graph) -> list[tuple[Node, Node, Node]]:
    found: list[tuple[Node, Node, Node]] = []
    for pair in disjoint_pairs(g):
        a, b = sorted(pair, key=str)
        for x in set(g.subjects(RDF.type, a)) & set(g.subjects(RDF.type, b)):
            found.append((x, a, b))
    return sorted(found, key=str)


def materialize(graphs: dict[str, Graph], check: bool = True) -> dict[str, Graph]:
    """Return the entailed triples, one graph per input graph. The inputs stay unchanged."""
    union = Graph()
    home: dict[Node, str] = {}
    release_subjects: set[Node] = set()
    for name, g in graphs.items():
        for s, p, o in g:
            if p in SKIPPED_PREDICATES:
                continue
            union.add((s, p, o))
            if name == GRAPH_RELEASE:
                release_subjects.add(s)
            else:
                home.setdefault(s, name)
    base = set(union)
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics, axiomatic_triples=False, datatype_axioms=False).expand(union)
    if check and (problems := disjointness_violations(union)):
        raise InconsistentGraphError(problems)

    out: dict[str, Graph] = defaultdict(Graph)
    for s, p, o in union:
        if (s, p, o) in base or not _keep(s, p, o):
            continue
        target = GRAPH_RELEASE if s in release_subjects else home.get(s)
        if target is None:
            continue
        out[target].add((s, p, o))
    return {name: out.get(name, Graph()) for name in graphs}


def apply(graphs: dict[str, Graph]) -> dict[str, int]:
    """Add the entailments to the graphs in place. Return the number of triples added per graph."""
    inferred = materialize(graphs)
    added = {}
    for name, extra in inferred.items():
        for triple in extra:
            graphs[name].add(triple)
        added[name] = len(extra)
    return added
