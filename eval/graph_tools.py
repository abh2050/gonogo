"""The tools answerer B may call: graph lookups through the rules' own SPARQL templates, and passages for one patent.

The tools return facts, never statuses or verdicts. They apply the recording cutoff and the field and territory
hierarchies, because those are what the graph and its templates do; deciding what the facts mean is left to the
model. Each row names the record it came from (a corpus document id), so an answer can cite it.

Every method takes and returns plain JSON values, so the tools can be tested without an agent framework.
"""

from __future__ import annotations

import re
from typing import Any

from agent.parser import Vocabulary
from er.resolver import resolve
from eval.corpus import card_id, doc_id
from kg.store import Store
from rules.context import Context
from rules.model import Request

DEFAULT_CUTOFF = "2026-11-01T00:00:00Z"
AS_OF = "2026-11-01"


def plain(value: Any) -> str:
    s = str(value)
    if "/id/" in s:
        return card_id(s)
    if s.startswith("https://w3id.org/gonogo/"):
        return doc_id(s)
    return s


def rows(raw: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{k: plain(v) for k, v in r.items()} for r in raw]


class GraphTools:
    def __init__(self, store: Store, vocab: Vocabulary, search: Any = None) -> None:
        self.store = store
        self.vocab = vocab
        self.search = search
        self.titles = {
            doc_id(str(r["p"])): str(r["title"])
            for r in store.select(
                "PREFIX dcterms: <http://purl.org/dc/terms/>\nPREFIX gng: <https://w3id.org/gonogo/ontology#>\n"
                "SELECT ?p ?title\nFROM <https://w3id.org/gonogo/graph/approved>\n"
                "WHERE { ?p a gng:Patent ; dcterms:title ?title }"
            )
        }

    def _ctx(self, patent_key: str, records_before: str | None, **req: Any) -> Context:
        request = Request(
            patent_key=patent_key,
            exclusivity=req.get("exclusivity", "non-exclusive"),
            field=req.get("field"),
            territory=req.get("territory"),
            start=req.get("start", AS_OF),
            end=req.get("end", AS_OF),
            licensee_ids=tuple(req.get("licensee_ids", ())),
        )
        return Context(self.store, request, cutoff=_cutoff(records_before), as_of=AS_OF)

    def find_patent(self, reference: str) -> dict[str, Any]:
        """A patent by NASA case number, US patent number, or words from its title."""
        ref = reference.strip()
        case = re.search(r"\b[A-Z]{3}-\d{4,6}(?:-[A-Z0-9]+)*\b", ref.upper())
        number = re.sub(r"\D", "", ref) if re.fullmatch(r"(?:US\s*)?(?:Patent\s*)?[\d,\s]+", ref, re.I) else ""
        key = (self.vocab.cases.get(case.group(0)) if case else None) or self.vocab.patent_numbers.get(number)
        if key:
            return {"patent_key": key, "title": self.titles.get(key, "")}
        words = {w for w in re.findall(r"[a-z]{4,}", ref.lower())}
        scored = sorted(
            ((len(words & set(re.findall(r"[a-z]{4,}", t.lower()))), k, t) for k, t in self.titles.items()),
            reverse=True,
        )
        best = [{"patent_key": k, "title": t} for n, k, t in scored[:3] if n >= max(2, len(words) // 2)]
        return {"matches": best} if best else {"error": f"No patent in scope matches {reference!r}."}

    def find_concept(self, kind: str, words: str) -> dict[str, Any]:
        """A field of use or territory concept id for the user's words."""
        table = self.vocab.fields if kind == "field" else self.vocab.territories
        hit = table.get(words.strip().lower()) or self.vocab.notations.get(words.strip().upper())
        if hit:
            return {"id": hit[0], "label": hit[1]}
        return {"error": f"No {kind} concept is labeled {words!r}.", "known": sorted(v[1] for v in table.values())[:60]}

    def find_licensee(self, name: str) -> dict[str, Any]:
        """The licensee records that match a company name, with each one's country."""
        status, candidates = resolve(name, self.vocab.parties)
        return {
            "status": status,
            "matches": [
                {"licensee_id": c.party.iri, "name": c.party.name, "country": c.party.country}
                for c in candidates[:3]
                if c.outcome.status == "match"
            ],
        }

    def patent_records(self, patent_key: str, records_before: str | None = None) -> dict[str, Any]:
        """Legal status, filing date, export classification, ownership, and consent records for a patent."""
        ctx = self._ctx(patent_key, records_before)
        return {
            "legal_status": rows(ctx.select("r1_status")),
            "filing": rows(ctx.select("r1_filing")),
            "export_classification": rows(ctx.select("r5_export")),
            "ownership": rows(ctx.select("r6_ownership")),
            "consents": rows(ctx.select("r6_consent")),
        }

    def overlapping_grants(
        self, patent_key: str, field: str, territory: str, start: str, end: str, records_before: str | None = None
    ) -> dict[str, Any]:
        """Executed grants, and other parties' proposed grants, on the patent whose field, territory, and term
        overlap the request. The graph checks the field and territory hierarchies in both directions."""
        ctx = self._ctx(patent_key, records_before, field=field, territory=territory, start=start, end=end)
        return {
            "executed": rows(ctx.select("r2_executed_overlap")),
            "proposed": rows(ctx.select("r2_proposed_overlap")),
        }

    def notices_for(
        self, patent_key: str, licensee_ids: list[str], records_before: str | None = None
    ) -> dict[str, Any]:
        """Notices of intent to license the patent to these licensee records, with each objection deadline."""
        if not licensee_ids:
            return {"notices": [], "note": "No licensee records were given."}
        ctx = self._ctx(patent_key, records_before, licensee_ids=licensee_ids)
        return {"notices": rows(ctx.select("r4_notices", mine={"iris": ctx.licensee_set}))}

    def search_documents(self, patent_key: str, query: str) -> dict[str, Any]:
        """Passages from documents about one patent: agreements, notices, records, and NASA reports."""
        if self.search is None:
            return {"passages": []}
        from eval.rag import retrieve

        return {"passages": retrieve(self.search, query, k=6, patent=patent_key)}


def _cutoff(records_before: str | None) -> str:
    if not records_before:
        return DEFAULT_CUTOFF
    return records_before if "T" in records_before else f"{records_before}T00:00:00Z"
