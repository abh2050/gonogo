"""The document corpus that the retrieval answerers search: one text file per document, with a metadata file beside it.

    uv run python -m eval.corpus

Answerer A (vector RAG) and answerer B (graph agent) must see the same information as the rule engine, or the
benchmark would measure missing data instead of method. So the corpus holds four kinds of document:

1. Record cards. Every time-stamped fact in the approved graph (legal status, ownership, consent, export
   classification, filing date, executed and proposed grants), written as plain text. They are rendered from the
   graph, so they say what the rules read, including corrections and the times each fact was recorded.
2. Patent cards. Title, NASA case number, patent number, and center.
3. Agreements and notices. The clause text of each license agreement and the full text of each notice.
4. NTRS reports. The first pages of each technical report linked to an in-scope patent.

Files go to data/eval/corpus/ in the layout that a Bedrock Knowledge Base reads from S3: `<doc>.txt` and
`<doc>.txt.metadata.json` with the document id, its kind, and the patents it is about.
"""

from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from typing import Any

from pypdf import PdfReader
from rdflib import RDF, RDFS, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, SKOS

from gonogo.paths import ROOT
from kg.ns import GNG, GRAPH_APPROVED, GRAPH_RELEASE
from kg.store import Store

OUT = ROOT / "data" / "eval" / "corpus"
NTRS_PAGES = 12  # enough for the abstract, introduction, and conclusions of most reports
PATENT = "https://w3id.org/gonogo/id/patent/"
PROV = "http://www.w3.org/ns/prov#"
# Provenance plumbing that says nothing a reader needs to answer a clearance question.
SKIP = {RDF.type, URIRef(PROV + "wasGeneratedBy"), URIRef(PROV + "wasAttributedTo"), GNG.readByRule}
KINDS = [
    (GNG.PatentLegalStatus, "legal status"),
    (GNG.OwnershipRecord, "ownership record"),
    (GNG.ConsentRecord, "consent record"),
    (GNG.ExportClassification, "export classification"),
    (GNG.FilingRecord, "filing record"),
    (GNG.ExecutedGrant, "executed grant"),
    (GNG.ProposedGrant, "proposed grant"),
]


def doc_id(iri: str) -> str:
    """A short, stable document id: the last segment of the IRI (AGR-0001, OWN-KSC-11641, SPG-003)."""
    return iri.rstrip("/").rsplit("/", 1)[-1]


def card_id(iri: str) -> str:
    """A record card's id: the IRI path after /id/ (grant/executed/AGR-0001), unique across kinds of fact. Its last
    segment matches the document it came from, which is how citations are scored."""
    return iri.split("/id/", 1)[-1]


class Labels:
    def __init__(self, *graphs: Graph) -> None:
        self.graphs = graphs

    def __call__(self, term: Any) -> str:
        if isinstance(term, Literal):
            return str(term)
        if str(term).startswith(PATENT):  # questions name a case number, so every patent reference carries one
            return f"{self.name(term)} (NASA case {doc_id(str(term))})"
        return self.name(term)

    def name(self, term: Any) -> str:
        for g in self.graphs:
            for p in (SKOS.prefLabel, RDFS.label, DCTERMS.title):
                for o in g.objects(term, p):
                    if not isinstance(o, Literal) or o.language in (None, "en"):
                        return str(o)
        return doc_id(str(term))


def patents_in(g: Graph, subject: URIRef) -> list[str]:
    return sorted({doc_id(str(o)) for o in g.objects(subject, None) if str(o).startswith(PATENT)})


def instances(g: Graph, cls: URIRef) -> list[URIRef]:
    return sorted({URIRef(str(s)) for s in g.subjects(RDF.type, cls)})


# document id -> patents it is about. Filled by write(), so the scorer can read it without the files.
PATENTS: dict[str, list[str]] = {}
DRY = False


def write(doc: str, kind: str, patents: list[str], text: str) -> None:
    PATENTS[doc] = patents
    if DRY:
        return
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", doc)
    (OUT / f"{safe}.txt").write_text(text.strip() + "\n")
    meta = {"metadataAttributes": {"doc_id": doc, "doc_kind": kind, "patents": patents}}
    (OUT / f"{safe}.txt.metadata.json").write_text(json.dumps(meta))


def record_cards(g: Graph, label: Labels) -> int:
    n = 0
    for cls, kind in KINDS:
        for s in instances(g, cls):
            lines = [f"{kind.upper()} {card_id(str(s))}"]
            for p, o in sorted(g.predicate_objects(s), key=lambda po: (label(po[0]), str(po[1]))):
                if p in SKIP:
                    continue
                lines.append(f"{label(p)}: {label(o)}")
            write(card_id(str(s)), kind, patents_in(g, s), "\n".join(lines))
            n += 1
    return n


def patent_cards(g: Graph, label: Labels) -> int:
    n = 0
    for s in instances(g, GNG.Patent):
        lines = [f"PATENT {doc_id(str(s))}"]
        for p, o in sorted(g.predicate_objects(s), key=lambda po: label(po[0])):
            if p not in SKIP and isinstance(o, Literal):
                lines.append(f"{label(p)}: {o}")
        write(f"PATENT-{doc_id(str(s))}", "patent", [doc_id(str(s))], "\n".join(lines))
        n += 1
    return n


def documents(g: Graph) -> int:
    """Agreements, rebuilt from their clauses in reading order, and notices from their full text. A document's
    patents are those of the grant with the same id (AGR-0001 is the agreement behind executed grant AGR-0001)."""
    grant_patents: dict[str, list[str]] = {}
    for cls in (GNG.ExecutedGrant, GNG.ProposedGrant):
        for s in instances(g, cls):
            grant_patents[doc_id(str(s))] = patents_in(g, s)
    clauses: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for c in g.subjects(RDF.type, GNG.Clause):
        doc = next(g.objects(c, GNG.inDocument), None)
        text = next(g.objects(c, GNG.spanText), None)
        start = next(g.objects(c, GNG.spanStart), Literal(0))
        if doc is not None and text is not None:
            clauses[str(doc)].append((int(str(start)), str(text)))
    n = 0
    for doc in instances(g, GNG.LicenseAgreement):
        parts = clauses.get(str(doc), [])
        write(doc_id(str(doc)), "license agreement", grant_patents.get(doc_id(str(doc)), []),
              "\n\n".join(t for _, t in sorted(parts)))  # fmt: skip
        n += 1
    for doc in instances(g, GNG.LicenseNotice):
        text = next(g.objects(doc, GNG.fullText), None)
        if text is None:
            continue
        write(doc_id(str(doc)), "license notice", grant_patents.get(doc_id(str(doc)), []), str(text))
        n += 1
    return n


def ntrs() -> int:
    by_report: dict[str, dict[str, Any]] = {}
    for line in (ROOT / "data" / "processed" / "ntrs.jsonl").read_text().splitlines():
        r = json.loads(line)
        if not r.get("pdf_file"):
            continue
        rep = by_report.setdefault(r["ntrs_id"], {**r, "patents": set()})
        rep["patents"].add(r["patent_key"])
    n = 0
    for rid, r in sorted(by_report.items()):
        path = ROOT / r["pdf_file"]
        body = ""
        if not DRY:
            try:
                reader = PdfReader(str(path))
                body = "\n".join((p.extract_text() or "") for p in reader.pages[:NTRS_PAGES])
            except Exception:  # a damaged or scanned PDF keeps its title and abstract only
                body = ""
        text = (
            f"NTRS REPORT {rid}: {r['title']}\nCenter: {r.get('center')}\nAbstract: {r.get('abstract', '')}\n\n{body}"
        )
        write(f"NTRS-{rid}", "ntrs report", sorted(r["patents"]), re.sub(r"[ \t]+", " ", text))
        n += 1
    return n


def patent_map(store: Store | None = None) -> dict[str, list[str]]:
    """Which patents each corpus document is about, computed without writing any file. With no built graph on disk
    (a CI job that never ran the build), the graph is built in memory."""
    global DRY
    if store is None:
        try:
            store = Store.from_build()
        except FileNotFoundError:
            from kg import build as kg_build
            from kg import materialize
            from kg.ns import GRAPH_ROYALTY

            graphs = kg_build.build_graphs()
            materialize.apply(graphs)
            store = Store({iri: g for iri, g in graphs.items() if iri != GRAPH_ROYALTY})
    DRY = True
    try:
        build(store)
    finally:
        DRY = False
    return dict(PATENTS)


def build(store: Store | None = None) -> dict[str, int]:
    store = store or Store.from_build()
    g, release = store.base[GRAPH_APPROVED], store.base[GRAPH_RELEASE]
    label = Labels(release, g)
    if not DRY:
        shutil.rmtree(OUT, ignore_errors=True)
        OUT.mkdir(parents=True)
    counts = {
        "record cards": record_cards(g, label),
        "patent cards": patent_cards(g, label),
        "agreements and notices": documents(g),
        "ntrs reports": ntrs(),
    }
    if not DRY:
        (OUT.parent / "corpus.counts.json").write_text(json.dumps(counts, indent=1))
    return counts


if __name__ == "__main__":
    counts = build()
    size = sum(f.stat().st_size for f in OUT.glob("*.txt"))
    print(counts, f"{size / 1e6:.1f} MB of text in {OUT.relative_to(ROOT)}")
