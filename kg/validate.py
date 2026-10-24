"""Validate the built graphs with SHACL.

Two runs:
  structure  every graph together against shapes/gonogo-shapes.ttl
  approval   release + approved + royalty against shapes/approved-shapes.ttl (every fact has an approver)

SHACL checks conformance only. It never decides a verdict.
"""

from __future__ import annotations

from typing import Any

from pyshacl import validate
from rdflib import RDF, Graph, URIRef
from rdflib.namespace import SH

from gonogo.paths import SHAPES
from kg.ns import GRAPH_APPROVED, GRAPH_RELEASE, GRAPH_ROYALTY


def _union(graphs: dict[str, Graph], names: list[str]) -> Graph:
    union = Graph()
    for name in names:
        for triple in graphs[name]:
            union.add(triple)
    return union


def run(data: Graph, shapes_file: str, name: str) -> dict[str, Any]:
    shapes = Graph().parse(SHAPES / shapes_file)
    conforms, report_graph, report_text = validate(
        data, shacl_graph=shapes, inference="none", abort_on_first=False, meta_shacl=False, advanced=False
    )
    results = list(report_graph.subjects(RDF.type, SH.ValidationResult))
    focus = [str(report_graph.value(r, SH.focusNode)) for r in results[:20]]
    return {
        "name": name,
        "conforms": bool(conforms),
        "violations": len(results),
        "examples": focus,
        "text": str(report_text),
    }


def validate_all(graphs: dict[str, Graph]) -> list[dict[str, Any]]:
    everything = _union(graphs, list(graphs))
    approved_side = _union(graphs, [GRAPH_RELEASE, GRAPH_APPROVED, GRAPH_ROYALTY])
    return [
        run(everything, "gonogo-shapes.ttl", "structure"),
        run(approved_side, "approved-shapes.ttl", "approval"),
    ]


__all__ = ["validate_all", "run", "URIRef"]
