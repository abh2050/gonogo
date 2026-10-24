"""Two SPARQL engines for the competency-question tests.

Both run the same rendered query text, FROM clauses included. rdflib has no dataset FROM semantics for
local graphs, so its engine merges the named graphs that the FROM clauses list and strips the clauses,
which is what FROM means. Fuseki runs the query as written.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from rdflib import BNode, Graph, Literal, URIRef

from kg.templates import strip_from

FUSEKI = "http://localhost:3030"
AUTH = ("admin", "gonogo-local")


def from_graphs(query: str) -> list[str]:
    return re.findall(r"^FROM <([^>]+)>", query, flags=re.M)


def _norm(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, URIRef):
        return f"<{value}>"
    if isinstance(value, BNode):
        return f"_:{value}"
    if isinstance(value, Literal):
        return str(value)
    return str(value)


class RdflibEngine:
    name = "rdflib"

    def __init__(self, graphs: dict[str, Graph]) -> None:
        self.graphs = graphs

    def select(self, query: str) -> tuple[list[str], list[tuple[str | None, ...]]]:
        merged = Graph()
        for iri in from_graphs(query):
            for triple in self.graphs[iri]:
                merged.add(triple)
        result = merged.query(strip_from(query))
        variables = [str(v) for v in result.vars or []]
        rows = [tuple(_norm(row[v]) for v in variables) for row in result]
        return variables, rows


class FusekiEngine:
    name = "fuseki"

    def __init__(self, graphs: dict[str, Graph], dataset: str = "cqtest") -> None:
        self.dataset = dataset
        with httpx.Client(auth=AUTH, timeout=60) as client:
            client.delete(f"{FUSEKI}/$/datasets/{dataset}")
            r = client.post(f"{FUSEKI}/$/datasets", data={"dbName": dataset, "dbType": "mem"})
            r.raise_for_status()
            for iri, graph in graphs.items():
                body = graph.serialize(format="turtle").encode()
                client.put(
                    f"{FUSEKI}/{dataset}/data",
                    params={"graph": iri},
                    content=body,
                    headers={"Content-Type": "text/turtle"},
                ).raise_for_status()

    def select(self, query: str) -> tuple[list[str], list[tuple[str | None, ...]]]:
        r = httpx.post(
            f"{FUSEKI}/{self.dataset}/query",
            data={"query": query},
            timeout=60,
            headers={"Accept": "application/sparql-results+json"},
        )
        r.raise_for_status()
        body = r.json()
        variables = body["head"]["vars"]
        rows = []
        for binding in body["results"]["bindings"]:
            row: list[str | None] = []
            for v in variables:
                cell = binding.get(v)
                if cell is None:
                    row.append(None)
                elif cell["type"] == "uri":
                    row.append(f"<{cell['value']}>")
                else:
                    row.append(cell["value"])
            rows.append(tuple(row))
        return variables, rows

    def close(self) -> None:
        httpx.delete(f"{FUSEKI}/$/datasets/{self.dataset}", auth=AUTH, timeout=30)
