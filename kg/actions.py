"""Governed actions: the only way the graph changes.

Each action is an event with typed inputs, a steward, and a reason. Applying an event adds triples to the
store's overlay, and nothing else. The new facts carry the same provenance as any other fact: the action
that generated them, the steward who approved them, and the recording time. A correction supersedes the
fact it replaces and never deletes it. SHACL validates the new facts before the store accepts them.

Event types:
  approve_fact   promote a candidate fact to the approved graph
  reject_fact    discard a candidate fact, with a reason
  link_identity  approve an identity link between two party nodes, which writes owl:sameAs
  reject_link    decide that two party nodes are not the same organization

An event log replays from an empty store to the same graph, so a client can hold the log and a server can
stay stateless. `to_sparql_update` writes the same triples as INSERT DATA for Fuseki or Neptune.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from pyshacl import validate as shacl_validate
from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, URIRef
from rdflib.term import Node

from gonogo.paths import SHAPES
from kg import materialize
from kg.ns import (
    GNG,
    GRAPH_APPROVED,
    GRAPH_CANDIDATE,
    GRAPH_RELEASE,
    ID,
    PROV,
    SCHEMA,
    SKOS,
    slug,
)
from kg.store import Store

DEMO_NOW = datetime(2026, 11, 1, tzinfo=UTC)
PROVENANCE = {PROV.wasGeneratedBy, GNG.recordedAt, GNG.approvedBy, GNG.supersededAt}
# Notes about the proposal stay on the candidate; they do not describe the approved fact.
PROPOSAL_NOTES = {RDFS.comment, SKOS.note}


class ActionRejectedError(ValueError):
    """Raised when an event is invalid, repeats a decision, or fails SHACL validation."""


def clock(sequence: int) -> str:
    """The demo clock: the evaluation date plus one second per event, so a replay gives the same times."""
    return (DEMO_NOW + timedelta(seconds=sequence)).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_for(store: Store) -> str:
    return clock(len(store.events))


def _dt(value: str) -> Literal:
    return Literal(value, datatype=XSD.dateTime)


def steward_node(name: str) -> URIRef:
    return URIRef(str(ID["steward/" + slug(name)]))


def _action_triples(event: dict[str, Any], kind: URIRef, used: list[URIRef]) -> list[tuple[Node, Node, Node]]:
    action = URIRef(str(ID["action/" + event["id"]]))
    steward = steward_node(event["steward"])
    triples: list[tuple[Node, Node, Node]] = [
        (action, RDF.type, kind),
        (action, PROV.startedAtTime, _dt(event["at"])),
        (action, GNG.actionReason, Literal(event["reason"])),
        (action, PROV.wasAssociatedWith, steward),
        (steward, RDF.type, GNG.Steward),
        (steward, RDFS.label, Literal(event["steward"])),
    ]
    triples += [(action, PROV.used, u) for u in used]
    return triples


def pending_candidates(store: Store) -> list[URIRef]:
    base = store.base[GRAPH_CANDIDATE]
    found = {s for s in base.subjects(RDF.type, GNG.BitemporalFact) if isinstance(s, URIRef)}
    return sorted((c for c in found if str(c) not in store.decided), key=str)


def describe_candidate(store: Store, candidate: URIRef) -> dict[str, Any]:
    g = store.base[GRAPH_CANDIDATE]
    approved = store.base[GRAPH_APPROVED]
    kinds = [str(t).rsplit("#", 1)[1] for t in g.objects(candidate, RDF.type) if str(t).startswith(str(GNG))]
    specific = [k for k in kinds if k not in ("BitemporalFact", "ExportClassification")]
    kind = sorted(specific)[0] if specific else "Fact"
    patent = g.value(candidate, GNG.aboutPatent)
    owners = [str(approved.value(o, SCHEMA.legalName) or o) for o in g.objects(candidate, GNG.coOwner)]
    complete = g.value(candidate, GNG.coOwnerListIsComplete)
    detail = f"{kind}"
    if kind == "OwnershipRecord":
        stated = "complete" if isinstance(complete, Literal) and complete.toPython() else "incomplete"
        detail = f"Ownership record: {stated}, {len(owners)} co-owner(s) listed"
    elif kind in ("RestrictedExport", "UnrestrictedExport"):
        permitted = sorted(str(t).rsplit("/", 1)[-1] for t in g.objects(candidate, GNG.permittedTerritory))
        detail = "Export classification: " + (
            f"restricted, permitted in {', '.join(permitted) or 'no country'}"
            if kind == "RestrictedExport"
            else "unrestricted"
        )
    return {
        "id": str(candidate),
        "type": "fact",
        "kind": kind,
        "summary": detail,
        "patent": str(patent) if patent else None,
        "patent_key": str(patent).rsplit("/", 1)[-1] if patent else None,
        "proposed_at": str(g.value(candidate, GNG.recordedAt)),
        "origin": "synthetic" if (candidate, PROV.wasGeneratedBy, None) in g else "real",
        "source": str(g.value(candidate, RDFS.comment) or ""),
        "warning": str(g.value(candidate, SKOS.note) or "") or None,
    }


def _current_facts(store: Store, cls: Node, patents: list[Node], at: str) -> list[URIRef]:
    """Approved facts of the same class and patent that no earlier correction replaced."""
    union = store._union([GRAPH_APPROVED])
    out = []
    for fact in union.subjects(RDF.type, cls):
        if not isinstance(fact, URIRef):
            continue
        if not set(union.objects(fact, GNG.aboutPatent)) & set(patents):
            continue
        sup = union.value(fact, GNG.supersededAt)
        if isinstance(sup, Literal) and sup.toPython() <= datetime.fromisoformat(at.replace("Z", "+00:00")):
            continue
        out.append(fact)
    return sorted(out, key=str)


def _validate(store: Store, new: list[tuple[Node, Node, Node]], check_approval: bool) -> None:
    """Run SHACL over the new triples, with the release graph and two hops of context from the approved graph."""
    release = Graph()
    for t in store.base[GRAPH_RELEASE]:
        release.add(t)
    local = Graph()
    for t in new:
        local.add(t)
    approved = store._union([GRAPH_APPROVED])
    referenced: set[Node] = {o for _, _, o in new if isinstance(o, URIRef)} | {
        s for s, _, _ in new if isinstance(s, URIRef)
    }
    for _ in range(2):  # the fact, its activity, and the agent behind the activity
        reached: set[Node] = set()
        for node in referenced:
            for t in approved.triples((node, None, None)):
                local.add(t)
                if isinstance(t[2], URIRef):
                    reached.add(t[2])
        referenced = reached
    graphs = {GRAPH_RELEASE: release, GRAPH_APPROVED: local}
    materialize.apply(graphs)
    union = Graph()
    for g in graphs.values():
        for t in g:
            union.add(t)
    files = ["gonogo-shapes.ttl", "approved-shapes.ttl"] if check_approval else ["gonogo-shapes.ttl"]
    for name in files:
        conforms, _, text = shacl_validate(
            union, shacl_graph=Graph().parse(SHAPES / name), inference="none", abort_on_first=False, meta_shacl=False
        )
        if not conforms:
            raise ActionRejectedError(f"SHACL rejected the new facts ({name}): {str(text)[:600]}")


def apply_event(store: Store, event: dict[str, Any]) -> dict[str, Any]:
    """Apply one event to the store and return a summary of what changed. The store keeps the event."""
    expected_at = clock(len(store.events) + 1)
    event = {**event, "id": event.get("id") or f"evt-{len(store.events) + 1:03d}", "at": event.get("at") or expected_at}
    if event["at"] < clock(len(store.events)):
        raise ActionRejectedError("An event cannot be recorded before the events that precede it.")
    if not (event.get("steward") or "").strip():
        raise ActionRejectedError("A steward name is required.")
    if len((event.get("reason") or "").strip()) < 3:
        raise ActionRejectedError("A reason is required.")
    handler = {
        "approve_fact": _approve_fact,
        "reject_fact": _reject_fact,
        "link_identity": _link_identity,
        "reject_link": _reject_link,
    }.get(event["action"])
    if handler is None:
        raise ActionRejectedError(f"Unknown action: {event['action']}")
    result = handler(store, event)
    store.events.append(event)
    result["event"] = event
    return result


def replay(base: Store, events: list[dict[str, Any]]) -> Store:
    """A fresh store with the events applied in order."""
    store = base.fork()
    for e in events:
        apply_event(store, e)
    return store


def _most_specific(types: set[Node], ontology: Graph) -> Node:
    candidates = sorted((t for t in types if t != GNG.BitemporalFact), key=str)
    return next(t for t in candidates if not any((o, RDFS.subClassOf, t) in ontology for o in candidates if o != t))


def _approve_fact(store: Store, event: dict[str, Any]) -> dict[str, Any]:
    candidate = URIRef(event["params"]["candidate"])
    if str(candidate) in store.decided:
        raise ActionRejectedError("That candidate already has a decision.")
    cg = store.base[GRAPH_CANDIDATE]
    props = [(p, o) for p, o in cg.predicate_objects(candidate)]
    if not props:
        raise ActionRejectedError(f"No candidate fact {candidate}.")
    types = {o for p, o in props if p == RDF.type and str(o).startswith(str(GNG))}
    # A new export classification replaces the old one whichever way it rules, so supersession works on the family.
    cls = (
        GNG.ExportClassification
        if types & {GNG.RestrictedExport, GNG.UnrestrictedExport}
        else _most_specific(types, store.base[GRAPH_RELEASE])
    )
    patents = [o for p, o in props if p == GNG.aboutPatent]
    suffix = "approved-" + event["id"]
    new = URIRef(re.sub(r"/candidate$", "", str(candidate)) + "/" + suffix)
    action = URIRef(str(ID["action/" + event["id"]]))
    steward = steward_node(event["steward"])

    triples: list[tuple[Node, Node, Node]] = [(new, p, o) for p, o in props if p not in PROVENANCE | PROPOSAL_NOTES]
    triples += [
        (new, GNG.recordedAt, _dt(event["at"])),
        (new, GNG.approvedBy, steward),
        (new, PROV.wasGeneratedBy, action),
        (new, PROV.wasDerivedFrom, candidate),
    ]
    # Keep the candidate's own origin in the approved graph, so a synthetic fact stays labeled synthetic.
    triples += [(candidate, PROV.wasGeneratedBy, o) for o in cg.objects(candidate, PROV.wasGeneratedBy)]
    superseded = _current_facts(store, cls, patents, event["at"])
    triples += [(new, GNG.supersedes, old) for old in superseded]
    triples += [(old, GNG.supersededAt, _dt(event["at"])) for old in superseded]
    triples += _action_triples(event, GNG.ApproveFact, [candidate])

    _validate(store, triples, check_approval=True)
    store.update(GRAPH_APPROVED, triples)
    store.decided[str(candidate)] = {"decision": "approved", "event": event["id"]}
    return {
        "action": "approve_fact",
        "new_facts": [str(new)],
        "superseded": [str(o) for o in superseded],
        "patents": [str(p) for p in patents],
    }


def _reject_fact(store: Store, event: dict[str, Any]) -> dict[str, Any]:
    candidate = URIRef(event["params"]["candidate"])
    if str(candidate) in store.decided:
        raise ActionRejectedError("That candidate already has a decision.")
    cg = store.base[GRAPH_CANDIDATE]
    if (candidate, RDF.type, GNG.BitemporalFact) not in cg:
        raise ActionRejectedError(f"No candidate fact {candidate}.")
    triples = _action_triples(event, GNG.RejectFact, [candidate])
    _validate(store, triples, check_approval=False)
    store.update(GRAPH_APPROVED, triples)
    store.decided[str(candidate)] = {"decision": "rejected", "event": event["id"]}
    patents = [str(o) for o in cg.objects(candidate, GNG.aboutPatent)]
    return {"action": "reject_fact", "new_facts": [], "superseded": [], "patents": patents}


def _link_identity(store: Store, event: dict[str, Any]) -> dict[str, Any]:
    from er.resolver import METHOD, pair_id

    a, b = URIRef(event["params"]["a"]), URIRef(event["params"]["b"])
    pid = pair_id(str(a), str(b))
    if pid in store.decided:
        raise ActionRejectedError("That pair already has a decision.")
    link = URIRef(str(ID["link/" + pid]))
    action = URIRef(str(ID["action/" + event["id"]]))
    steward = steward_node(event["steward"])
    first, second = sorted((a, b), key=str)
    triples: list[tuple[Node, Node, Node]] = [
        (first, OWL.sameAs, second),
        (link, RDF.type, GNG.IdentityLink),
        (link, GNG.linksParty, first),
        (link, GNG.linksParty, second),
        (link, GNG.matchScore, Literal(str(event["params"].get("score", 0)), datatype=XSD.decimal)),
        (link, GNG.matchMethod, Literal(event["params"].get("method", METHOD))),
        (link, GNG.recordedAt, _dt(event["at"])),
        (link, GNG.validFrom, Literal(event["at"][:10], datatype=XSD.date)),
        (link, GNG.approvedBy, steward),
        (link, PROV.wasGeneratedBy, action),
    ]
    triples += _action_triples(event, GNG.LinkIdentity, [a, b])
    _validate(store, triples, check_approval=True)
    store.update(GRAPH_APPROVED, triples)
    store.decided[pid] = {"decision": "linked", "event": event["id"]}
    return {"action": "link_identity", "new_facts": [str(link)], "superseded": [], "patents": [], "pair": pid}


def _reject_link(store: Store, event: dict[str, Any]) -> dict[str, Any]:
    from er.resolver import pair_id

    pid = pair_id(event["params"]["a"], event["params"]["b"])
    if pid in store.decided:
        raise ActionRejectedError("That pair already has a decision.")
    triples = _action_triples(event, GNG.RejectFact, [URIRef(event["params"]["a"]), URIRef(event["params"]["b"])])
    _validate(store, triples, check_approval=False)
    store.update(GRAPH_APPROVED, triples)
    store.decided[pid] = {"decision": "different", "event": event["id"]}
    return {"action": "reject_link", "new_facts": [], "superseded": [], "patents": [], "pair": pid}


def to_sparql_update(store: Store) -> list[str]:
    """The overlay as SPARQL UPDATE strings, one per graph, for Fuseki or Neptune. Gate 3 runs these on Neptune."""
    updates = []
    for iri, g in store.overlay.items():
        if len(g):
            body = g.serialize(format="nt").strip()
            updates.append(f"INSERT DATA {{ GRAPH <{iri}> {{\n{body}\n}} }}")
    return updates
