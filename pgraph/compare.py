"""Run R2 in SPARQL (rules/templates/r2_executed_overlap.rq) and in Cypher (pgraph/r2.cypher) on the same requests,
and compare the grants each returns.

    uv run python -m pgraph.load && uv run python -m pgraph.compare

The requests are every synthetic request, plus sixteen variations around each executed grant: the grant's field,
its broader field, a narrower one, and a sibling; the grant's territory and its broader region; and a term that
overlaps and one that does not. Writes pgraph/results.json.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

from rdflib import RDF
from rdflib.namespace import SKOS

from eval.corpus import doc_id
from kg.ns import GNG, GRAPH_APPROVED, GRAPH_RELEASE
from kg.store import Store
from pgraph.load import driver
from rules.context import Context
from rules.model import Request

HERE = Path(__file__).resolve().parent
CYPHER = (HERE / "r2.cypher").read_text()
CUTOFF, AS_OF = "2026-11-01T00:00:00Z", "2026-11-01"


def requests(store: Store) -> list[dict[str, Any]]:
    root = HERE.parent / "data" / "synthetic" / "requests.jsonl"
    out = [
        {"patent": r["patent_key"], "field": r["field_concept"], "territory": r["territory"], "start": r["start"],
         "end": r["end"], "cutoff": CUTOFF, "why": r["request_id"]}
        for r in map(json.loads, root.read_text().splitlines())
    ]  # fmt: skip
    a, rel = store.base[GRAPH_APPROVED], store.base[GRAPH_RELEASE]
    broader = {doc_id(str(c)): doc_id(str(b)) for c, b in rel.subject_objects(SKOS.broader)}
    narrower: dict[str, list[str]] = {}
    for c, b in broader.items():
        narrower.setdefault(b, []).append(c)
    for g in sorted(set(a.subjects(RDF.type, GNG.ExecutedGrant)), key=str):
        patent = doc_id(str(next(a.objects(g, GNG.aboutPatent))))
        field = doc_id(str(next(a.objects(g, GNG.fieldOfUse))))
        terr = doc_id(str(next(a.objects(g, GNG.territory))))
        start, end = str(next(a.objects(g, GNG.validFrom))), str(next(a.objects(g, GNG.validTo)))
        parent = broader.get(field)
        fields = [field, parent, *(sorted(narrower.get(field, []))[:1]),
                  *(sorted(x for x in narrower.get(parent or "", []) if x != field)[:1])]  # fmt: skip
        terrs = [terr, broader.get(terr) or terr]
        terms = [(start, end), ("2099-01-01", "2099-12-31")]
        for f in [x for x in fields if x]:
            for t in terrs:
                for s, e in terms:
                    out.append({"patent": patent, "field": f, "territory": t, "start": s, "end": e,
                                "cutoff": CUTOFF, "why": f"variation of {doc_id(str(g))}"})  # fmt: skip
    # The superseded grant, before and after its correction was recorded.
    for cutoff in ("2026-10-25T00:00:00Z", CUTOFF):
        out += [dict(r, cutoff=cutoff, why=f"{r['why']} at {cutoff[:10]}") for r in out if "AGR-0018" in r["why"]][:4]
    return out


def sparql(store: Store, r: dict[str, Any]) -> set[str]:
    req = Request(r["patent"], "non-exclusive", r["field"], r["territory"], r["start"], r["end"])
    return {doc_id(str(x["grant"])) for x in Context(store, req, r["cutoff"], AS_OF).select("r2_executed_overlap")}


def main() -> dict[str, Any]:
    store = Store.from_build()
    reqs = requests(store)
    agree, differ = 0, []
    t_sparql: list[float] = []
    t_cypher: list[float] = []
    nonempty = 0
    with driver() as d, d.session() as s:
        for r in reqs:
            t0 = time.perf_counter()
            a = sparql(store, r)
            t_sparql.append(time.perf_counter() - t0)
            t0 = time.perf_counter()
            b = {rec["grant"] for rec in s.run(CYPHER, **r)}
            t_cypher.append(time.perf_counter() - t0)
            nonempty += bool(a)
            if a == b:
                agree += 1
            else:
                differ.append({**r, "sparql": sorted(a), "cypher": sorted(b)})
    out = {
        "requests": len(reqs),
        "with_a_conflict": nonempty,
        "agree": agree,
        "differ": differ[:20],
        "median_ms": {
            "sparql_rdflib": round(1000 * statistics.median(t_sparql), 2),
            "cypher_neo4j": round(1000 * statistics.median(t_cypher), 2),
        },  # fmt: skip
        "query_lines": {
            "sparql": len(
                [
                    x
                    for x in (HERE.parent / "rules/templates/r2_executed_overlap.rq").read_text().splitlines()
                    if x.strip() and not x.startswith("#")
                ]
            ),
            "cypher": len([x for x in CYPHER.splitlines() if x.strip() and not x.startswith("//")]),
        },  # fmt: skip
    }
    (HERE / "results.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    r = main()
    print({k: v for k, v in r.items() if k != "differ"})
    for x in r["differ"][:5]:
        print("DIFFER", x)
