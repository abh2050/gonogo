"""What a rule needs to ask the graph: the request, the cutoff, and a way to run reviewed templates."""

from __future__ import annotations

from datetime import date
from functools import cached_property
from pathlib import Path
from typing import Any

from rdflib import RDF, URIRef

from kg.ns import FIELD, GNG, GRAPH_APPROVED, GRAPH_RELEASE, TERRITORY, patent_iri
from kg.store import Store
from kg.templates import render
from rules.model import ClauseRef, FactRef, Request

TEMPLATES = Path(__file__).parent / "templates"
ALLOWLIST = [GRAPH_APPROVED, GRAPH_RELEASE]


class UnknownConceptError(ValueError):
    """Raised when a request names a patent, field, or territory that the graph does not hold."""


def value(row: dict[str, Any], key: str) -> Any:
    """The Python value of a bound variable, or None."""
    node = row.get(key)
    return None if node is None else getattr(node, "toPython", lambda: str(node))()


def text(row: dict[str, Any], key: str) -> str | None:
    node = row.get(key)
    return None if node is None else str(node)


def local(iri: str | None) -> str:
    return "" if iri is None else iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


class Context:
    """One evaluation: a request read at a recording cutoff, as of an evaluation date."""

    def __init__(self, store: Store, request: Request, cutoff: str, as_of: str) -> None:
        self.store = store
        self.request = request
        self.cutoff = cutoff  # xsd:dateTime lexical form
        self.as_of = as_of  # xsd:date lexical form
        self._facts: dict[str, FactRef] = {}
        self._executed: list[dict[str, Any]] | None = None
        self.queries_run = 0

    # ---- identifiers --------------------------------------------------------------------------

    @property
    def patent(self) -> str:
        return patent_iri(self.request.patent_key)

    @property
    def field_iri(self) -> str | None:
        return None if self.request.field is None else str(FIELD[self.request.field])

    @property
    def territory_iri(self) -> str | None:
        return None if self.request.territory is None else str(TERRITORY[self.request.territory])

    def validate(self) -> None:
        """Refuse a request that names something the graph does not hold, so no rule guesses."""
        if self.request.field is None or self.request.territory is None:
            raise UnknownConceptError("A request needs a field of use and a territory.")
        checks = [
            (self.patent, GNG.Patent),
            (str(self.field_iri), GNG.FieldOfUse),
            (str(self.territory_iri), GNG.Territory),
        ]
        for iri, cls in checks:
            if not self._has_type(iri, cls):
                raise UnknownConceptError(f"The graph holds no {str(cls).rsplit('#', 1)[-1]} {iri}")
        if date.fromisoformat(self.request.end) < date.fromisoformat(self.request.start):
            raise UnknownConceptError("The request ends before it starts.")

    def _has_type(self, iri: str, cls: URIRef) -> bool:
        for g in (self.store.base[GRAPH_APPROVED], self.store.base[GRAPH_RELEASE]):
            if (URIRef(iri), RDF.type, cls) in g:
                return True
        return False

    # ---- templates ----------------------------------------------------------------------------

    def params(self, **extra: dict[str, Any]) -> dict[str, dict[str, Any]]:
        p: dict[str, dict[str, Any]] = {
            "patent": {"iri": self.patent},
            "start": {"date": self.request.start},
            "end": {"date": self.request.end},
            "asof": {"date": self.as_of},
            "cutoff": {"datetime": self.cutoff},
        }
        if self.field_iri:
            p["field"] = {"iri": self.field_iri}
        if self.territory_iri:
            p["territory"] = {"iri": self.territory_iri}
        p.update(extra)
        return p

    def select(self, name: str, **extra: dict[str, Any]) -> list[dict[str, Any]]:
        template = (TEMPLATES / f"{name}.rq").read_text()
        query = render(template, self.params(**extra), ALLOWLIST)
        self.queries_run += 1
        return self.store.select(query)

    # ---- the requester's identity -------------------------------------------------------------

    @cached_property
    def licensee_set(self) -> list[str]:
        """The requester's licensee nodes and every node that a steward linked to them with owl:sameAs."""
        if not self.request.licensee_ids:
            return []
        rows = self.select("licensee_identity", ids={"iris": list(self.request.licensee_ids)})
        return sorted({str(r["same"]) for r in rows} | set(self.request.licensee_ids))

    # ---- facts and clauses --------------------------------------------------------------------

    def note_fact(self, iri: str, kind: str, label: str) -> None:
        self._facts.setdefault(iri, FactRef(iri=iri, kind=kind, label=label))

    def collect(self, iris: list[str]) -> list[FactRef]:
        """Fill in recording time, approver, origin, and sources for the facts a rule read."""
        wanted = [i for i in dict.fromkeys(iris) if i in self._facts]
        if not wanted:
            return []
        rows = self.select("facts_meta", facts={"iris": wanted})
        meta: dict[str, dict[str, Any]] = {}
        for r in rows:
            m = meta.setdefault(str(r["fact"]), {"sources": {}, "synthetic": False, "approver": None, "recorded": None})
            m["recorded"] = text(r, "recorded") or m["recorded"]
            if "approver" in r:
                m["approver"] = text(r, "approverLabel") or local(text(r, "approver"))
            if "origin" in r:
                m["synthetic"] = True
            if "source" in r and "sourceTitle" in r:
                m["sources"][str(r["source"])] = {"title": str(r["sourceTitle"]), "url": text(r, "sourceUrl") or ""}
        out: list[FactRef] = []
        for iri in wanted:
            ref = self._facts[iri]
            found = meta.get(iri)
            if found:
                ref.recorded_at = found["recorded"]
                ref.approved_by = found["approver"]
                ref.origin = "synthetic" if found["synthetic"] else "real"
                ref.sources = list(found["sources"].values())
            out.append(ref)
        return out

    def clauses_for(self, fact_iris: list[str], kinds: set[str] | None = None) -> list[ClauseRef]:
        """The clause spans behind the facts, optionally only certain kinds (grant, field, territory, term)."""
        if not fact_iris:
            return []
        out: list[ClauseRef] = []
        for r in self.select("clauses", facts={"iris": list(dict.fromkeys(fact_iris))}):
            kind = str(r["kind"])
            if kinds is not None and kind not in kinds:
                continue
            out.append(
                ClauseRef(
                    iri=str(r["clause"]),
                    fact=str(r["fact"]),
                    kind=kind,
                    text=str(r["text"]),
                    start=int(value(r, "start")),
                    end=int(value(r, "end")),
                    document=str(r["doc"]),
                    document_title=text(r, "title"),
                    document_url=text(r, "url"),
                )
            )
        return out

    def executed_overlap(self) -> list[dict[str, Any]]:
        """Executed grants that overlap the request on field, territory, and term. R2 and R3 share this."""
        if self._executed is None:
            self._executed = self.select("r2_executed_overlap")
        return self._executed
