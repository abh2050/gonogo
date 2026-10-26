"""Turn a typed clearance question into a structured request.

The parser is deterministic. Every value it returns is a concept from a GoNoGo scheme, a case number held in
the graph, or an ISO date, and every value keeps the character span it was read from. A value the parser
cannot find is listed as missing; it is never guessed. An optional model parser (agent/model_parser.py) can
propose the same fields, and its output goes through the same checks before any rule sees it.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from er.resolver import Party, index_parties, resolve
from kg.ns import GRAPH_APPROVED, GRAPH_RELEASE
from kg.store import Reader
from rules.model import EXCLUSIVITY_TYPES, Request

FIELDS = ("patent_key", "exclusivity", "field", "territory", "start", "end", "licensee")

MONTHS = {
    m: i + 1
    for i, m in enumerate(
        "january february march april may june july august september october november december".split()
    )
}
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
DATE = rf"(?:\d{{4}}-\d{{2}}-\d{{2}}|{_MONTH}\s+\d{{1,2}},?\s+\d{{4}})"
CASE = re.compile(r"\b([A-Z]{3}-\d{5}(?:-\d+)?(?:-[A-Z]+)?)\b")
PATENT_NO = re.compile(r"\b(?:U\.?S\.?\s+)?Patent(?:\s+No\.?)?\s+((?:\d{1,2},)?\d{3},\d{3}|\d{7,8})\b", re.I)
EXCLUSIVITY = re.compile(r"\b(non[- ]?exclusive|partially[- ]exclusive|co[- ]?exclusive|exclusive)\b", re.I)
SPAN_RANGE = re.compile(rf"\b(?:from|starting|beginning)\s+({DATE})\s+(?:to|through|until|thru|-)\s+({DATE})", re.I)
SPAN_YEARS = re.compile(
    rf"\bfor\s+((\d{{1,2}}|one|two|three|four|five|six|seven|eight|nine|ten)\s+years?)\s+(?:from|starting|beginning)\s+({DATE})",
    re.I,
)
LICENSEE_LEAD = re.compile(
    r"^\s*(?:can|could|may)\s+(.+?)\s+(?:get|obtain|take|have|receive|license)\b"
    r"|^\s*(.+?)\s+(?:wants|would like|requests|is requesting|is asking for|asks for|seeks)\b",
    re.I,
)
EXCLUSIVITY_SLUGS = {re.sub(r"[^a-z]", "", t): t for t in EXCLUSIVITY_TYPES}
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
TERRITORY_ALIASES = {
    "usa": "US", "u.s.": "US", "u.s.a.": "US", "united states of america": "US", "the united states": "US",
    "global": "WORLD", "worldwide": "WORLD", "world-wide": "WORLD", "the world": "WORLD", "all countries": "WORLD",
}  # fmt: skip


@dataclass
class Found:
    value: str
    span: tuple[int, int]
    text: str
    label: str | None = None
    how: str = "rule"


@dataclass
class Parse:
    text: str
    found: dict[str, Found] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    licensee: dict[str, Any] | None = None
    parser: str = "deterministic-v1"

    @property
    def complete(self) -> bool:
        return not [m for m in self.missing if m != "licensee"]

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["complete"] = self.complete
        return out

    def to_request(self) -> Request:
        if not self.complete:
            raise ValueError("The request is missing: " + ", ".join(self.missing))
        lic = self.licensee or {}
        return Request(
            patent_key=self.found["patent_key"].value,
            exclusivity=self.found["exclusivity"].value,
            field=self.found["field"].value,
            territory=self.found["territory"].value,
            start=self.found["start"].value,
            end=self.found["end"].value,
            licensee_name=self.found["licensee"].value if "licensee" in self.found else None,
            licensee_ids=tuple(lic.get("ids", ())),
            licensee_country=lic.get("country"),
            text=self.text,
        )


@dataclass
class Vocabulary:
    """The labels the parser may match, read from the graph once."""

    fields: dict[str, tuple[str, str]]  # lowercase label -> (concept slug, preferred label)
    territories: dict[str, tuple[str, str]]
    notations: dict[str, tuple[str, str]]  # "US" -> (slug, label)
    cases: dict[str, str]  # NASA case number -> patent key
    patent_numbers: dict[str, str]  # "8067478" -> patent key
    parties: list[Party]
    same_as: dict[str, set[str]]  # licensee IRI -> every IRI a steward linked to it

    @classmethod
    def from_store(cls, store: Reader) -> Vocabulary:
        def concepts(scheme: str) -> list[dict[str, Any]]:
            return store.select(
                f"""PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?c ?label ?alt ?notation
FROM <{GRAPH_RELEASE}>
WHERE {{ ?c skos:inScheme <https://w3id.org/gonogo/scheme/{scheme}> ; skos:prefLabel ?label .
  OPTIONAL {{ ?c skos:altLabel ?alt }} OPTIONAL {{ ?c skos:notation ?notation }} }}"""
            )

        def labels(rows: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
            out: dict[str, tuple[str, str]] = {}
            for r in rows:
                slug, label = str(r["c"]).rstrip("/").rsplit("/", 1)[-1], str(r["label"])
                out[label.lower()] = (slug, label)
                if "alt" in r:
                    out[str(r["alt"]).lower()] = (slug, label)
            return out

        territory_rows = concepts("territory")
        territories = labels(territory_rows)
        notations = {
            str(r["notation"]): (str(r["c"]).rsplit("/", 1)[-1], str(r["label"]))
            for r in territory_rows
            if "notation" in r
        }
        for alias, code in TERRITORY_ALIASES.items():
            territories[alias] = notations[code]
        patents = store.select(
            f"""PREFIX gng: <https://w3id.org/gonogo/ontology#> PREFIX dct: <http://purl.org/dc/terms/>
SELECT ?key ?case ?number
FROM <{GRAPH_APPROVED}>
WHERE {{ ?p a gng:Patent ; dct:identifier ?key .
  OPTIONAL {{ ?p gng:caseNumber ?case }} OPTIONAL {{ ?p gng:patentNumber ?number }} }}"""
        )
        same_as: dict[str, set[str]] = {}
        for r in store.select(
            f"""PREFIX owl: <http://www.w3.org/2002/07/owl#>
SELECT ?a ?b
FROM <{GRAPH_APPROVED}>
WHERE {{ ?a owl:sameAs ?b }}"""
        ):
            group = same_as.get(str(r["a"]), {str(r["a"])}) | same_as.get(str(r["b"]), {str(r["b"])})
            for iri in group:
                same_as[iri] = group
        return cls(
            fields=labels(concepts("field-of-use")),
            territories=territories,
            notations=notations,
            cases={str(r["case"]): str(r["key"]) for r in patents if "case" in r},
            patent_numbers={str(r["number"]): str(r["key"]) for r in patents if "number" in r},
            parties=index_parties(store),
            same_as=same_as,
        )


def _label_hits(text: str, table: dict[str, tuple[str, str]], skip: tuple[int, int] | None) -> list[Found]:
    """Every concept the text names, keeping the longest label where two overlap, in order of appearance."""
    hits: list[Found] = []
    lowered = text.lower()
    for label, (slug, pref) in table.items():
        for m in re.finditer(rf"(?<![\w-]){re.escape(label)}(?![\w-])", lowered):
            if skip and m.start() < skip[1] and m.end() > skip[0]:
                continue
            hits.append(Found(slug, (m.start(), m.end()), text[m.start() : m.end()], pref))
    hits.sort(key=lambda h: (h.span[0], -(h.span[1] - h.span[0])))
    kept: list[Found] = []
    for h in hits:
        if not any(k.span[0] <= h.span[0] and h.span[1] <= k.span[1] for k in kept):
            kept.append(h)
    return kept


def _choose(out: Parse, key: str, noun: str, hits: list[Found]) -> None:
    """Take the one thing the question names. Two different things are an ambiguity to report, never a guess."""
    distinct = list(dict.fromkeys(h.value for h in hits))
    if len(distinct) == 1:
        out.found[key] = hits[0]
    elif len(distinct) > 1:
        out.notes.append(f"The question names more than one {noun} ({', '.join(distinct)}), so GoNoGo does not choose.")


def to_iso(raw: str) -> str:
    raw = raw.strip().rstrip(".")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return date.fromisoformat(raw).isoformat()
    m = re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", raw)
    if not m:
        raise ValueError(f"Not a date: {raw!r}")
    month = next(v for k, v in MONTHS.items() if k.startswith(m.group(1).lower()[:3]))
    return date(int(m.group(3)), month, int(m.group(2))).isoformat()


def _add_years(start: str, years: int) -> str:
    d = date.fromisoformat(start)
    try:
        end = d.replace(year=d.year + years)
    except ValueError:  # February 29
        end = d.replace(year=d.year + years, day=28)
    return date.fromordinal(end.toordinal() - 1).isoformat()


def parse(text: str, vocab: Vocabulary) -> Parse:
    out = Parse(text=text)
    f = out.found

    lead = LICENSEE_LEAD.search(text)
    if lead:
        g = 1 if lead.group(1) else 2
        name = lead.group(g).strip().strip(",")
        f["licensee"] = Found(name, (lead.start(g), lead.start(g) + len(name)), name)
    name_span = f["licensee"].span if "licensee" in f else None

    patents: list[Found] = []
    for m in CASE.finditer(text):
        if m.group(1) in vocab.cases:
            patents.append(Found(vocab.cases[m.group(1)], m.span(1), m.group(1), f"NASA case {m.group(1)}"))
        else:
            out.notes.append(f"The graph holds no NASA case {m.group(1)}.")
    for pm in PATENT_NO.finditer(text):
        number = re.sub(r"\D", "", pm.group(1))
        if number in vocab.patent_numbers:
            patents.append(Found(vocab.patent_numbers[number], pm.span(1), pm.group(1), f"US Patent {pm.group(1)}"))
        else:
            out.notes.append(f"The graph holds no US patent {pm.group(1)}.")
    _choose(out, "patent_key", "patent", sorted(patents, key=lambda h: h.span))

    licenses = []
    for em in EXCLUSIVITY.finditer(text):
        slug = EXCLUSIVITY_SLUGS[re.sub(r"[^a-z]", "", em.group(1).lower())]
        licenses.append(Found(slug, em.span(1), em.group(1), slug.replace("-", " ")))
    _choose(out, "exclusivity", "license type", licenses)

    _choose(out, "field", "field of use", _label_hits(text, vocab.fields, name_span))
    places = _label_hits(text, vocab.territories, name_span)
    if places:
        _choose(out, "territory", "territory", places)
    else:
        for tm in re.finditer(r"\b(?:in|for|across|throughout)\s+(?:the\s+)?([A-Z]{2})\b", text):
            if tm.group(1) in vocab.notations:
                slug, label = vocab.notations[tm.group(1)]
                f["territory"] = Found(slug, tm.span(1), tm.group(1), label)
                break

    if rm := SPAN_RANGE.search(text):
        f["start"] = Found(to_iso(rm.group(1)), rm.span(1), rm.group(1))
        f["end"] = Found(to_iso(rm.group(2)), rm.span(2), rm.group(2))
    elif ym := SPAN_YEARS.search(text):
        years = int(ym.group(2)) if ym.group(2).isdigit() else WORDS[ym.group(2).lower()]
        start = to_iso(ym.group(3))
        f["start"] = Found(start, ym.span(3), ym.group(3))
        f["end"] = Found(_add_years(start, years), ym.span(1), ym.group(1), how="computed")

    resolve_licensee(out, vocab)
    out.missing = [k for k in FIELDS if k not in f]
    return out


def resolve_licensee(out: Parse, vocab: Vocabulary) -> None:
    """Match the typed company name against the licensees in the graph, through any links a steward approved."""
    if "licensee" not in out.found:
        return
    name = out.found["licensee"].value
    status, candidates = resolve(name, vocab.parties)
    matches = [c.party.iri for c in candidates if c.outcome.status == "match"]
    if len(matches) > 1 and vocab.same_as.get(matches[0], set()) >= set(matches):
        status = "match"  # several nodes, one organization: a steward already linked them
    out.licensee = {
        "status": status,
        "ids": matches if status == "match" else [],
        "country": next((c.party.country for c in candidates if c.party.country), None) if status == "match" else None,
        "candidates": [
            {
                "iri": c.party.iri,
                "name": c.party.name,
                "status": c.outcome.status,
                "score": round(c.outcome.score, 3),
                "why": c.outcome.basis,
            }
            for c in candidates[:3]
        ],
    }
    if status == "ambiguous":
        out.notes.append(f"'{name}' may be one of several known licensees. A steward can link the right one.")
    elif status == "none":
        out.notes.append(f"'{name}' is not a known licensee, so no notice or grant can name it.")
