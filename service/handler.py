"""The Lambda in the VPC: the guarded SPARQL path and the decision path, both over Neptune.

Routes (API Gateway REST, Cognito authorizer):
    GET  /health      status and the caller's role
    POST /query       a SELECT or ASK, validated against the caller's graphs (service/query.py)
    POST /decide      a structured clearance request, decided by the rule engine over Neptune

The loader is a second function in this file, invoked only with Lambda permissions and never through the API.
"""

from __future__ import annotations

import json
import os
from typing import Any

from authz import cedar
from service import identity, neptune
from service import query as q

NOW = "2026-11-01T00:00:00Z"
AS_OF = "2026-11-01"
CHUNK = 3000
MAX_ONE_REQUEST = 20000
HEADERS = {"Content-Type": "application/json", "Cache-Control": "no-store"}


def respond(status: int, body: Any) -> dict[str, Any]:
    return {"statusCode": status, "headers": HEADERS, "body": json.dumps(body, default=str)}


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    claims = identity.claims_from_event(event)
    if claims is None:
        return respond(401, {"error": "No verified identity."})
    try:
        who = identity.principal_from_claims(claims)
    except identity.IdentityError as e:
        return respond(403, {"error": str(e)})
    method, resource = event.get("httpMethod"), event.get("resource")
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return respond(400, {"error": "The body is not JSON."})

    if (method, resource) == ("GET", "/health"):
        return respond(200, {"status": "ok", "role": who.role, "user": who.name, "graphs": cedar.readable_graphs(who)})
    if (method, resource) == ("POST", "/query"):
        try:
            result = q.execute(q.EndpointBackend(neptune.store()), who, str(body.get("query", "")))
        except q.QueryRefusedError as e:
            return respond(403, {"error": str(e)})
        return respond(200, {"rows": result.rows, "graphs": result.graphs, "truncated": result.truncated})
    if (method, resource) == ("POST", "/decide"):
        return decide(who, body)
    return respond(404, {"error": "No such route."})


def decide(who: cedar.Principal, body: dict[str, Any]) -> dict[str, Any]:
    from rules.context import UnknownConceptError
    from rules.engine import evaluate
    from rules.model import Request

    allowed = cedar.authorize(who, "AskClearance", ("Request", "r"))
    if not allowed.allowed:
        return respond(403, {"error": " ".join(allowed.reasons)})
    raw = dict(body.get("request") or {})
    try:
        request = Request(**{**raw, "licensee_ids": tuple(raw.get("licensee_ids") or ())})
        record = evaluate(neptune.store(), request, cutoff=NOW, as_of=AS_OF, user=who.name, role=who.role)
    except (TypeError, UnknownConceptError, ValueError) as e:
        return respond(422, {"error": str(e)})
    return respond(200, {"decision": record.to_dict(), "backend": "neptune"})


def load_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Load graph files from S3 into Neptune. Invoked by the deploy script with {"bucket", "files": {iri: key}}."""
    import boto3
    from rdflib import BNode, Graph

    s3 = boto3.client("s3")
    loaded: dict[str, int] = {}
    for iri, key in event["files"].items():
        g = Graph().parse(data=s3.get_object(Bucket=event["bucket"], Key=key)["Body"].read().decode(), format="turtle")
        neptune.update(f"DROP SILENT GRAPH <{iri}>")
        lines = g.serialize(format="nt").splitlines()
        # A blank node is scoped to one SPARQL request, so a graph that has any must go in a single request.
        has_bnodes = any(isinstance(t, BNode) for s_, _, o_ in g for t in (s_, o_))
        size = len(lines) if has_bnodes else CHUNK
        if has_bnodes and len(lines) > MAX_ONE_REQUEST:
            raise ValueError(f"{iri} has blank nodes and {len(lines)} triples: too many for one request")
        for i in range(0, len(lines), size):
            chunk = "\n".join(lines[i : i + size])
            neptune.update(f"INSERT DATA {{ GRAPH <{iri}> {{\n{chunk}\n}} }}")
        loaded[iri] = len(lines)
    return {"loaded": loaded, "endpoint": os.environ.get("NEPTUNE_ENDPOINT", "")}
