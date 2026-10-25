"""Governed actions: the only way the graph changes.

Each action is an event with typed inputs, a steward, a role, and a reason. Applying an event adds triples to the
store's overlay, and nothing else. The new facts carry the same provenance as any other fact: the action that
generated them, the steward who approved them, and the recording time. A correction supersedes the fact it
replaces and never deletes it. SHACL validates the new facts before the store accepts them.

Event types:
  propose_fact   a steward or licensing manager puts a candidate fact forward
  approve_fact   promote a candidate fact to the approved graph
  link_identity  approve an identity link between two party nodes, which writes owl:sameAs
  second_review  counsel approves or denies an approval that a steward submitted
  reject_fact    discard a candidate fact, with a reason
  reject_link    decide that two party nodes are not the same organization

Separation of duties (docs/adr/0002-separation-of-duties.md). Cedar decides who may do what. For an approval, the
engine first builds the change, applies it to a copy of the store, and computes two flags: the fact conflicts with
an approved fact, or the approval would move a verdict from COUNSEL or NO GO to GO. Cedar then permits the
steward to approve, or to submit the approval for second review, or neither. A submitted approval changes no
verdict until counsel approves it. Nobody approves a fact that they proposed.

An event log replays from an empty store to the same graph, so a client can hold the log and a server can stay
stateless. Replay recomputes each route and rejects a log whose recorded route no longer matches the policy.
`to_sparql_update` writes the same triples as INSERT DATA for Fuseki or Neptune.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pyshacl import validate as shacl_validate
from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, URIRef
from rdflib.term import Node

from authz import cedar
from gonogo.paths import SHAPES
from kg import governance, materialize
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


def _action_triples(
    event: dict[str, Any], kind: URIRef, used: list[URIRef], second: str | None = None
) -> list[tuple[Node, Node, Node]]:
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
    if second:
        reviewer = steward_node(second)
        triples += [
            (action, RDF.type, GNG.SecondReview),
            (action, PROV.wasAssociatedWith, reviewer),
            (reviewer, RDF.type, GNG.Steward),
            (reviewer, RDFS.label, Literal(second)),
        ]
    triples += [(action, PROV.used, u) for u in used]
    return triples


def pending_candidates(store: Store) -> list[URIRef]:
    """Candidates that still need a decision. A candidate that waits for counsel is still open."""
    base = store.view([GRAPH_CANDIDATE])
    found = {s for s in base.subjects(RDF.type, GNG.BitemporalFact) if isinstance(s, URIRef)}
    final = {k for k, v in store.decided.items() if v["decision"] != "pending_second_review"}
    return sorted((c for c in found if str(c) not in final), key=str)


def _origin(store: Store, candidate: URIRef) -> str:
    """'synthetic' for generated data, 'model' for a language model's proposal, otherwise 'real'."""
    view = store.view([GRAPH_CANDIDATE, GRAPH_APPROVED])
    for run in view.objects(candidate, PROV.wasGeneratedBy):
        types = set(view.objects(run, RDF.type))
        if GNG.SyntheticGeneration in types:
            return "synthetic"
        if GNG.Extraction in types and view.value(run, GNG.promptVersion) is not None:
            return "model"
    return "real"


def describe_candidate(store: Store, candidate: URIRef) -> dict[str, Any]:
    g = store.view([GRAPH_CANDIDATE])
    approved = store.view([GRAPH_APPROVED])
    kinds = [str(t).rsplit("#", 1)[1] for t in g.objects(candidate, RDF.type) if str(t).startswith(str(GNG))]
    specific = [k for k in kinds if k not in ("BitemporalFact", "ExportClassification")]
    kind = sorted(specific)[0] if specific else "Fact"
    patent = g.value(candidate, GNG.aboutPatent)
    owners = [str(approved.value(o, SCHEMA.legalName) or o) for o in g.objects(candidate, GNG.coOwner)]
    complete = g.value(candidate, GNG.coOwnerListIsComplete)
    detail = f"{kind}"
    extra: dict[str, Any] = {}
    if kind == "OwnershipRecord":
        stated = "complete" if isinstance(complete, Literal) and complete.toPython() else "incomplete"
        detail = f"Ownership record: {stated}, {len(owners)} co-owner(s) listed"
    elif kind == "FieldOfUseAssignment":
        field_ = g.value(candidate, GNG.assignsField)
        clause = g.value(candidate, GNG.sourceClause)
        quote = str(g.value(clause, GNG.spanText)) if clause else ""
        detail = f"Field of use: {str(field_).rsplit('/', 1)[-1].replace('-', ' ') if field_ else '?'}"
        extra = {"quote": quote, "grant": str(g.value(candidate, GNG.aboutGrant))}
    elif kind in ("RestrictedExport", "UnrestrictedExport"):
        permitted = sorted(str(t).rsplit("/", 1)[-1] for t in g.objects(candidate, GNG.permittedTerritory))
        detail = "Export classification: " + (
            f"restricted, permitted in {', '.join(permitted) or 'no country'}"
            if kind == "RestrictedExport"
            else "unrestricted"
        )
    found = governance.conflicts(store, candidate)
    state = store.decided.get(str(candidate), {})
    waiting = state.get("decision") == "pending_second_review"
    return {
        "id": str(candidate),
        "type": "fact",
        "kind": kind,
        "summary": detail,
        "patent": str(patent) if patent else None,
        "patent_key": str(patent).rsplit("/", 1)[-1] if patent else None,
        "proposed_at": str(g.value(candidate, GNG.recordedAt)),
        "proposed_by": governance.proposer_name(store, candidate),
        "origin": _origin(store, candidate),
        "source": str(g.value(candidate, RDFS.comment) or ""),
        "conflicts": found,
        "warning": " ".join(c["reason"] for c in found) or None,
        "state": "pending_second_review" if waiting else "proposed",
        "first_approver": state.get("first_approver") if waiting else None,
        "needs": "counsel" if waiting else "steward",
        **extra,
    }


def _current_facts(
    store: Store, cls: Node, patents: list[Node], at: str, grants: list[Node] | None = None
) -> list[URIRef]:
    """Approved facts of the same class and patent that no earlier correction replaced.

    A fact about one grant, such as a field of use assignment, replaces only facts about that grant.
    """
    union = store._union([GRAPH_APPROVED])
    out = []
    for fact in union.subjects(RDF.type, cls):
        if not isinstance(fact, URIRef):
            continue
        if not set(union.objects(fact, GNG.aboutPatent)) & set(patents):
            continue
        if grants and not set(union.objects(fact, GNG.aboutGrant)) & set(grants):
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


@dataclass
class Plan:
    """A change that has been built and validated but not yet applied."""

    kind: str  # "fact" or "link"
    key: str  # the candidate IRI, or the identity pair id
    resource: tuple[str, str]  # for Cedar
    triples: list[tuple[Node, Node, Node]]
    new_facts: list[str] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    patents: list[str] = field(default_factory=list)
    decided: dict[str, Any] = field(default_factory=dict)
    candidate: URIRef | None = None
    proposer: str = ""


def _principal(event: dict[str, Any]) -> cedar.Principal:
    try:
        return cedar.Principal(str(event.get("steward", "")), str(event.get("role") or "steward"))
    except (cedar.UnknownRoleError, ValueError) as e:
        raise ActionRejectedError(str(e)) from e


def _denied(*decisions: cedar.Decision) -> ActionRejectedError:
    """The sentence that explains a refusal: a forbid's own reason first, else the default."""
    for d in decisions:
        if d.policies and d.reasons:
            return ActionRejectedError(" ".join(d.reasons))
    return ActionRejectedError(" ".join(decisions[-1].reasons))


def apply_event(store: Store, event: dict[str, Any]) -> dict[str, Any]:
    """Apply one event to the store and return a summary of what changed. The store keeps the event."""
    expected_at = clock(len(store.events) + 1)
    event = {**event, "id": event.get("id") or f"evt-{len(store.events) + 1:03d}", "at": event.get("at") or expected_at}
    event.setdefault("role", "steward")
    event.setdefault("params", {})
    if event["at"] < clock(len(store.events)):
        raise ActionRejectedError("An event cannot be recorded before the events that precede it.")
    if not (event.get("steward") or "").strip():
        raise ActionRejectedError("A steward name is required.")
    if len((event.get("reason") or "").strip()) < 3:
        raise ActionRejectedError("A reason is required.")
    handler = {
        "propose_fact": _propose_fact,
        "approve_fact": _approve_fact,
        "second_review": _second_review,
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


def _commit(store: Store, plan: Plan) -> None:
    store.update(GRAPH_APPROVED, plan.triples)
    store.decided[plan.key] = plan.decided
    store.pending.pop(plan.key, None)


def _plan_fact(store: Store, event: dict[str, Any]) -> Plan:
    """Build the approval of a candidate fact. `event["second_reviewer"]` is set once counsel has agreed."""
    candidate = URIRef(event["params"]["candidate"])
    state = store.decided.get(str(candidate))
    if state and state["decision"] != "pending_second_review":
        raise ActionRejectedError("That candidate already has a decision.")
    cg = store.view([GRAPH_CANDIDATE])
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
    new = URIRef(re.sub(r"/candidate[^/]*$", "", str(candidate)) + "/" + suffix)
    steward = steward_node(event["steward"])

    skip = PROVENANCE | PROPOSAL_NOTES | {GNG.proposedBy}
    triples: list[tuple[Node, Node, Node]] = [(new, p, o) for p, o in props if p not in skip]
    triples += [
        (new, GNG.recordedAt, _dt(event["at"])),
        (new, GNG.approvedBy, steward),
        (new, PROV.wasGeneratedBy, URIRef(str(ID["action/" + event["id"]]))),
        (new, PROV.wasDerivedFrom, candidate),
    ]
    triples += [(new, GNG.proposedBy, o) for o in cg.objects(candidate, GNG.proposedBy)]
    second = event.get("second_reviewer")
    if second:
        triples.append((new, GNG.secondApprovedBy, steward_node(second)))
    # Keep the candidate's own origin in the approved graph, so a synthetic fact stays labeled synthetic.
    triples += [(candidate, PROV.wasGeneratedBy, o) for o in cg.objects(candidate, PROV.wasGeneratedBy)]
    grants = [o for p, o in props if p == GNG.aboutGrant]
    superseded = _current_facts(store, cls, patents, event["at"], grants)
    # The clause that holds a proposed fact's quote travels with it, so the approved fact can cite its words.
    for p, o in props:
        if p == GNG.sourceClause and isinstance(o, URIRef) and (o, RDF.type, GNG.Clause) in cg:
            triples += [(o, cp, co) for cp, co in cg.predicate_objects(o)]
    triples += [(new, GNG.supersedes, old) for old in superseded]
    triples += [(old, GNG.supersededAt, _dt(event["at"])) for old in superseded]
    triples += _action_triples(event, GNG.ApproveFact, [candidate], second)

    _validate(store, triples, check_approval=True)
    return Plan(
        kind="fact",
        key=str(candidate),
        resource=("Candidate", str(candidate)),
        triples=triples,
        new_facts=[str(new)],
        superseded=[str(o) for o in superseded],
        patents=[str(p) for p in patents],
        decided={"decision": "approved", "event": event["id"], "approver": event["steward"], "second": second},
        candidate=candidate,
        proposer=governance.proposer_name(store, candidate),
    )


def _plan_link(store: Store, event: dict[str, Any]) -> Plan:
    from er.resolver import METHOD, pair_id

    a, b = URIRef(event["params"]["a"]), URIRef(event["params"]["b"])
    pid = pair_id(str(a), str(b))
    state = store.decided.get(pid)
    if state and state["decision"] != "pending_second_review":
        raise ActionRejectedError("That pair already has a decision.")
    link = URIRef(str(ID["link/" + pid]))
    steward = steward_node(event["steward"])
    first, second_node = sorted((a, b), key=str)
    triples: list[tuple[Node, Node, Node]] = [
        (first, OWL.sameAs, second_node),
        (link, RDF.type, GNG.IdentityLink),
        (link, GNG.linksParty, first),
        (link, GNG.linksParty, second_node),
        (link, GNG.matchScore, Literal(str(event["params"].get("score", 0)), datatype=XSD.decimal)),
        (link, GNG.matchMethod, Literal(event["params"].get("method", METHOD))),
        (link, GNG.recordedAt, _dt(event["at"])),
        (link, GNG.validFrom, Literal(event["at"][:10], datatype=XSD.date)),
        (link, GNG.approvedBy, steward),
        (link, PROV.wasGeneratedBy, URIRef(str(ID["action/" + event["id"]]))),
    ]
    second = event.get("second_reviewer")
    if second:
        triples.append((link, GNG.secondApprovedBy, steward_node(second)))
    triples += _action_triples(event, GNG.LinkIdentity, [a, b], second)
    _validate(store, triples, check_approval=True)
    return Plan(
        kind="link",
        key=pid,
        resource=("IdentityPair", pid),
        triples=triples,
        new_facts=[str(link)],
        decided={"decision": "linked", "event": event["id"], "approver": event["steward"], "second": second},
        proposer="gonogo-er",
    )


def _review(store: Store, event: dict[str, Any], plan: Plan, action: str) -> dict[str, Any]:
    """Apply the governance rule to an approval: commit it, hold it for counsel, or refuse it."""
    if store.decided.get(plan.key, {}).get("decision") == "pending_second_review":
        raise ActionRejectedError("That approval already waits for counsel.")
    principal = _principal(event)
    sim = store.copy()
    _commit(sim, plan)
    found = governance.conflicts(store, plan.candidate) if plan.candidate is not None else []
    patents = {p.rsplit("/", 1)[-1] for p in plan.patents}
    ups = governance.upgrades_to_go(store, sim, patents, list(event["params"].get("requests") or []), event["at"])
    ctx = {
        "proposer": plan.proposer or "unrecorded",
        "firstApprover": "",
        "conflict": bool(found),
        "upgradesToGo": bool(ups),
    }
    direct = cedar.authorize(principal, action, plan.resource, ctx)
    if direct.allowed:
        route, deciding = "immediate", direct
    else:
        submit = cedar.authorize(principal, "SubmitForSecondReview", plan.resource, ctx)
        if not submit.allowed:
            raise _denied(direct, submit)
        route, deciding = "pending_second_review", submit
    if event.get("route") and event["route"] != route:
        raise ActionRejectedError(
            f"The event log says {event['route']}, but the policy now says {route}. The log was changed."
        )
    event["route"] = route
    event["policies"] = deciding.policies
    event["flags"] = {"conflicts": found, "upgrades": ups}
    summary = {
        "action": event["action"],
        "route": route,
        "flags": event["flags"],
        "policies": deciding.policies,
        "patents": plan.patents,
        "new_facts": [],
        "superseded": [],
    }
    if route == "immediate":
        _commit(store, plan)
        summary.update(new_facts=plan.new_facts, superseded=plan.superseded)
    else:
        triples = _action_triples(event, GNG.SubmitForSecondReview, [URIRef(plan.key)] if plan.kind == "fact" else [])
        _validate(store, triples, check_approval=False)
        store.update(GRAPH_APPROVED, triples)
        store.pending[plan.key] = event
        store.decided[plan.key] = {
            "decision": "pending_second_review",
            "event": event["id"],
            "first_approver": event["steward"],
            "why": [c["reason"] for c in found]
            + [f"This would move {u['patent']} from {u['from']} to GO." for u in ups],
        }
    return summary


def _approve_fact(store: Store, event: dict[str, Any]) -> dict[str, Any]:
    return _review(store, event, _plan_fact(store, event), "ApproveFact")


def _link_identity(store: Store, event: dict[str, Any]) -> dict[str, Any]:
    return _review(store, event, _plan_link(store, event), "LinkIdentity")


def _second_review(store: Store, event: dict[str, Any]) -> dict[str, Any]:
    """Counsel agrees to, or denies, an approval that a steward submitted."""
    params = event["params"]
    if "candidate" in params:
        key = str(URIRef(params["candidate"]))
        resource = ("Candidate", key)
    else:
        from er.resolver import pair_id

        key = pair_id(params["a"], params["b"])
        resource = ("IdentityPair", key)
    first = store.pending.get(key)
    if first is None:
        raise ActionRejectedError("No approval waits for counsel on that item.")
    principal = _principal(event)
    proposer = governance.proposer_name(store, URIRef(key)) if resource[0] == "Candidate" else "gonogo-er"
    ctx = {
        "proposer": proposer or "unrecorded",
        "firstApprover": first["steward"],
        "conflict": bool(first["flags"]["conflicts"]),
        "upgradesToGo": bool(first["flags"]["upgrades"]),
    }
    decision = cedar.authorize(principal, "SecondReview", resource, ctx)
    if not decision.allowed:
        raise _denied(decision)
    verdict = params.get("decision", "approve")
    if verdict not in ("approve", "deny"):
        raise ActionRejectedError("A second review approves or denies.")
    if verdict == "deny":
        triples = _action_triples(event, GNG.SecondReview, [URIRef(key)] if resource[0] == "Candidate" else [])
        _validate(store, triples, check_approval=False)
        store.update(GRAPH_APPROVED, triples)
        store.pending.pop(key)
        store.decided[key] = {
            "decision": "denied_second_review",
            "event": event["id"],
            "first_approver": first["steward"],
        }
        return {"action": "second_review", "route": "denied", "new_facts": [], "superseded": [], "patents": []}
    # Counsel agrees: the steward's approval takes effect now, recorded at counsel's time, with both approvers.
    merged = {
        **first,
        "id": event["id"],
        "at": event["at"],
        "reason": f"{first['reason']} Second review by counsel: {event['reason']}",
        "second_reviewer": event["steward"],
    }
    store.pending.pop(key)
    plan = _plan_fact(store, merged) if resource[0] == "Candidate" else _plan_link(store, merged)
    _commit(store, plan)
    return {
        "action": "second_review",
        "route": "approved",
        "new_facts": plan.new_facts,
        "superseded": plan.superseded,
        "patents": plan.patents,
    }


def _propose_fact(store: Store, event: dict[str, Any]) -> dict[str, Any]:
    """A steward or licensing manager puts a candidate fact forward. It changes no verdict until it is approved."""
    from kg.ns import TERRITORY, patent_iri

    principal = _principal(event)
    p = event["params"]
    patent_key = str(p.get("patent_key", ""))
    patent = URIRef(patent_iri(patent_key))
    if (patent, RDF.type, GNG.Patent) not in store.view([GRAPH_APPROVED]):
        raise ActionRejectedError(f"The graph holds no patent {patent_key}.")
    kind = p.get("kind")
    node = URIRef(
        str(ID[("ownership" if kind == "ownership" else "export") + f"/{patent_key}/candidate-{event['id']}"])
    )
    allowed = cedar.authorize(principal, "ProposeFact", ("Candidate", str(node)))
    if not allowed.allowed:
        raise _denied(allowed)
    proposer = steward_node(event["steward"])
    action = URIRef(str(ID["action/" + event["id"]]))
    if kind == "ownership":
        cls = GNG.OwnershipRecord
    elif kind == "export":
        cls = GNG.RestrictedExport if p.get("classification") == "restricted" else GNG.UnrestrictedExport
    else:
        raise ActionRejectedError("A steward can propose an ownership record or an export classification.")
    triples: list[tuple[Node, Node, Node]] = [
        (node, RDF.type, cls),
        (node, GNG.aboutPatent, patent),
        (node, GNG.recordedAt, _dt(event["at"])),
        (node, GNG.validFrom, Literal(event["at"][:10], datatype=XSD.date)),
        (node, PROV.wasGeneratedBy, action),
        (node, GNG.proposedBy, proposer),
        (node, RDFS.comment, Literal(f"Proposed by {event['steward']}: {event['reason']}", lang="en")),
    ]
    if cls == GNG.OwnershipRecord:
        triples.append((node, GNG.coOwnerListIsComplete, Literal(bool(p.get("complete", True)))))
        for ref in p.get("co_owners", []):
            triples.append((node, GNG.coOwner, URIRef(str(ID["co-owner/" + str(ref)]))))
    else:
        triples += [(node, GNG.permittedTerritory, TERRITORY[c]) for c in p.get("permitted_countries", [])]
    triples += _action_triples(event, GNG.ProposeFacts, [])
    _validate(store, triples, check_approval=False)
    store.update(GRAPH_CANDIDATE, triples)
    return {
        "action": "propose_fact",
        "route": "proposed",
        "candidate": str(node),
        "new_facts": [],
        "superseded": [],
        "patents": [str(patent)],
    }


def _reject_fact(store: Store, event: dict[str, Any]) -> dict[str, Any]:
    candidate = URIRef(event["params"]["candidate"])
    state = store.decided.get(str(candidate))
    if state and state["decision"] != "pending_second_review":
        raise ActionRejectedError("That candidate already has a decision.")
    cg = store.view([GRAPH_CANDIDATE])
    if (candidate, RDF.type, GNG.BitemporalFact) not in cg:
        raise ActionRejectedError(f"No candidate fact {candidate}.")
    allowed = cedar.authorize(_principal(event), "RejectFact", ("Candidate", str(candidate)))
    if not allowed.allowed:
        raise _denied(allowed)
    triples = _action_triples(event, GNG.RejectFact, [candidate])
    _validate(store, triples, check_approval=False)
    store.update(GRAPH_APPROVED, triples)
    store.pending.pop(str(candidate), None)
    store.decided[str(candidate)] = {"decision": "rejected", "event": event["id"]}
    patents = [str(o) for o in cg.objects(candidate, GNG.aboutPatent)]
    return {"action": "reject_fact", "route": "rejected", "new_facts": [], "superseded": [], "patents": patents}


def _reject_link(store: Store, event: dict[str, Any]) -> dict[str, Any]:
    from er.resolver import pair_id

    pid = pair_id(event["params"]["a"], event["params"]["b"])
    state = store.decided.get(pid)
    if state and state["decision"] != "pending_second_review":
        raise ActionRejectedError("That pair already has a decision.")
    allowed = cedar.authorize(_principal(event), "RejectLink", ("IdentityPair", pid))
    if not allowed.allowed:
        raise _denied(allowed)
    triples = _action_triples(event, GNG.RejectFact, [URIRef(event["params"]["a"]), URIRef(event["params"]["b"])])
    _validate(store, triples, check_approval=False)
    store.update(GRAPH_APPROVED, triples)
    store.pending.pop(pid, None)
    store.decided[pid] = {"decision": "different", "event": event["id"]}
    return {"action": "reject_link", "route": "rejected", "new_facts": [], "superseded": [], "patents": [], "pair": pid}


def to_sparql_update(store: Store) -> list[str]:
    """The overlay as SPARQL UPDATE strings, one per graph, for Fuseki or Neptune. Gate 3 runs these on Neptune."""
    updates = []
    for iri, g in store.overlay.items():
        if len(g):
            body = g.serialize(format="nt").strip()
            updates.append(f"INSERT DATA {{ GRAPH <{iri}> {{\n{body}\n}} }}")
    return updates
