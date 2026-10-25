"""What the rule engine knows about an approval, so that Cedar can decide whether one person may make it.

Two facts matter. First, whether the proposed fact conflicts with a fact that a steward already approved.
Second, whether approving it would move a verdict from COUNSEL or NO GO to GO. This module computes both and
hands them to the policies in authz/policies/ as context. It never decides anything itself: a flag here only
changes which Cedar action is asked, and Cedar answers.
"""

from __future__ import annotations

from typing import Any

from rdflib import RDF, URIRef

from kg.ns import GNG, GRAPH_APPROVED, GRAPH_CANDIDATE
from kg.store import Store

UPGRADE_FROM = {"COUNSEL", "NO GO"}


def local(node: Any) -> str:
    return str(node).rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def proposer_name(store: Store, candidate: URIRef) -> str:
    """The name of whoever proposed the candidate: a steward, a licensee, a model, or a feed. Empty if unrecorded."""
    view = store.view([GRAPH_CANDIDATE, GRAPH_APPROVED])
    agent = view.value(candidate, GNG.proposedBy)
    if agent is None:
        return ""
    from kg.ns import SCHEMA

    label = view.value(agent, SCHEMA.legalName) or view.value(
        agent, URIRef("http://www.w3.org/2000/01/rdf-schema#label")
    )
    return str(label) if label is not None else local(agent)


def _current(store: Store, cls: URIRef, patent: URIRef) -> list[URIRef]:
    view = store.view([GRAPH_APPROVED])
    return [
        f
        for f in view.subjects(RDF.type, cls)
        if isinstance(f, URIRef) and (f, GNG.aboutPatent, patent) in view and view.value(f, GNG.supersededAt) is None
    ]


def conflicts(store: Store, candidate: URIRef) -> list[dict[str, str]]:
    """Ways a proposed fact contradicts a fact that is already approved. An empty list means none."""
    cand = store.view([GRAPH_CANDIDATE, GRAPH_APPROVED])
    approved = store.view([GRAPH_APPROVED])
    out: list[dict[str, str]] = []
    types = {t for t in cand.objects(candidate, RDF.type)}
    for patent in cand.objects(candidate, GNG.aboutPatent):
        if not isinstance(patent, URIRef):
            continue
        if GNG.OwnershipRecord in types:
            mine = set(cand.objects(candidate, GNG.coOwner))
            for rec in _current(store, GNG.OwnershipRecord, patent):
                gone = set(approved.objects(rec, GNG.coOwner)) - mine
                if gone:
                    names = ", ".join(sorted(local(o) for o in gone))
                    out.append(
                        {"fact": str(rec), "reason": f"It leaves out co-owner {names}, whom the approved record lists."}
                    )
        elif types & {GNG.RestrictedExport, GNG.UnrestrictedExport}:
            restricted = GNG.RestrictedExport in types
            for rec in _current(store, GNG.ExportClassification, patent):
                was = (rec, RDF.type, GNG.RestrictedExport) in approved
                if was != restricted:
                    out.append(
                        {
                            "fact": str(rec),
                            "reason": f"It says {'restricted' if restricted else 'unrestricted'}, "
                            f"and the approved classification says {'restricted' if was else 'unrestricted'}.",
                        }
                    )
                elif restricted and set(approved.objects(rec, GNG.permittedTerritory)) != set(
                    cand.objects(candidate, GNG.permittedTerritory)
                ):
                    out.append({"fact": str(rec), "reason": "It permits different countries than the approved record."})
        elif GNG.FieldOfUseAssignment in types:
            grant = cand.value(candidate, GNG.aboutGrant)
            field = cand.value(candidate, GNG.assignsField)
            for old in approved.subjects(GNG.aboutGrant, grant):
                current = approved.value(old, GNG.assignsField)
                if approved.value(old, GNG.supersededAt) is None and current != field:
                    out.append({"fact": str(old), "reason": f"The approved assignment says {local(current)}."})
            stated = approved.value(grant, GNG.fieldOfUse) if grant is not None else None
            if stated is not None and stated != field:
                out.append({"fact": str(grant), "reason": f"The notice itself states {local(stated)}."})
    return out


def _decide(store: Store, request: Any, cutoff: str) -> str:
    from rules.engine import evaluate

    return str(evaluate(store, request, cutoff=cutoff, as_of="2026-11-01").verdict)


def _session_requests(entries: list[dict[str, Any]], store: Store) -> list[Any]:
    from agent.parser import Vocabulary, parse
    from rules.model import Request

    out: list[Any] = []
    for e in entries:
        if "request" in e:
            r = dict(e["request"])
            r["licensee_ids"] = tuple(r.get("licensee_ids") or ())
            out.append(Request(**r))
        elif e.get("text"):
            parsed = parse(str(e["text"]), Vocabulary.from_store(store))
            if parsed.complete:
                out.append(parsed.to_request())
    return out


def upgrades_to_go(
    before: Store, after: Store, patents: set[str], session: list[dict[str, Any]], cutoff: str
) -> list[dict[str, str]]:
    """Questions whose verdict moves from COUNSEL or NO GO to GO when `after` replaces `before`."""
    from rules.book import requests_for_patents

    found: list[dict[str, str]] = []
    pairs = [(r, r) for r in requests_for_patents(patents)]
    # A session question is parsed against each world, because a licensee link changes what the name means.
    for entry in session:
        b, a = _session_requests([entry], before), _session_requests([entry], after)
        if b and a:
            pairs.append((b[0], a[0]))
    for rb, ra in pairs:
        try:
            was, now = _decide(before, rb, cutoff), _decide(after, ra, cutoff)
        except ValueError:
            continue
        move = {"patent": ra.patent_key, "field": str(ra.field), "from": was, "to": now}
        if was in UPGRADE_FROM and now == "GO" and move not in found:
            found.append(move)
    return found
