"""Write the built graphs to disk and load them into a Fuseki dataset through the Graph Store Protocol."""

from __future__ import annotations

import os

import httpx
from rdflib import Graph

from gonogo.paths import BUILD, SNAPSHOT, SYNTHETIC
from kg.ns import GRAPH_APPROVED, GRAPH_CANDIDATE, GRAPH_RELEASE, GRAPH_ROYALTY

OUT_DIR = BUILD / "kg"
FILES = {
    GRAPH_RELEASE: "release.ttl",
    GRAPH_APPROVED: "approved.ttl",
    GRAPH_CANDIDATE: "candidate.ttl",
    GRAPH_ROYALTY: "royalty.ttl",
}


def write_files(graphs: dict[str, Graph]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.mkdir(parents=True, exist_ok=True)
    # The request book lets a deployment without data/ check which verdicts an approval would change.
    (SNAPSHOT / "requests.jsonl").write_bytes((SYNTHETIC / "requests.jsonl").read_bytes())
    for name, g in graphs.items():
        g.namespace_manager.bind("gng", "https://w3id.org/gonogo/ontology#")
        body = g.serialize(format="turtle").encode()
        (OUT_DIR / FILES[name]).write_bytes(body)
        if name != GRAPH_ROYALTY:  # royalty terms never ship to the public demo (MD11)
            SNAPSHOT.mkdir(parents=True, exist_ok=True)
            (SNAPSHOT / FILES[name]).write_bytes(body)


def _auth() -> tuple[str, str]:
    return "admin", os.environ.get("FUSEKI_ADMIN_PASSWORD", "gonogo-local")


def load_all(base: str = "http://localhost:3030/gonogo") -> dict[str, int]:
    """Replace each named graph in the dataset with the built file. Return triple counts per graph."""
    with httpx.Client(timeout=300, auth=_auth()) as client:
        for graph_iri, filename in FILES.items():
            body = (OUT_DIR / filename).read_bytes()
            r = client.put(
                f"{base}/data", params={"graph": graph_iri}, content=body, headers={"Content-Type": "text/turtle"}
            )
            r.raise_for_status()
        query = "SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g"
        r = client.get(f"{base}/query", params={"query": query}, headers={"Accept": "application/sparql-results+json"})
        r.raise_for_status()
        counts = {b["g"]["value"]: int(b["n"]["value"]) for b in r.json()["results"]["bindings"]}
    for graph_iri in FILES:
        print(f"  loaded {graph_iri}: {counts.get(graph_iri, 0):,} triples")
    return counts
