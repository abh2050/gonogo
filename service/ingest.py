"""The ingestion workflow: an agreement PDF dropped in the inbox becomes a proposed grant, waits for a steward, and
once approved is written to Neptune, and the requests it affects run again.

    S3 inbox -> ocr (Textract) -> extract -> check (SHACL) -> await approval (task token) -> apply -> rerun

Each step is one Lambda handler below, and infra/stacks.py (IngestStack) wires them into a Step Functions state
machine. The extraction is fixed patterns over the agreement's articles, not a model, and the text is evidence only:
a clause the extractor does not recognize is kept as an "other" clause and never interpreted. The approval goes
through the same actions as the Steward page (kg/actions.py), so Cedar and the two-person rule apply unchanged.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

PIPELINE = "Ingestion pipeline"
ARTICLE = re.compile(r"Article (\d+)\. ([A-Z][A-Za-z -]+?)\.")
KINDS = {
    "grant": "grant",
    "field of use": "field",
    "licensed territory": "territory",
    "term": "term",
    "royalties": "royalty",
    "royalty": "royalty",
    "sublicensing": "sublicense",
    "co-exclusive licensees": "cap",
    "export control": "export",
    "signatures": "signature",
    "correction": "correction",
}
DATE = r"([A-Z][a-z]+ \d{1,2}, \d{4})"


class ExtractionError(ValueError):
    """The agreement does not state something a grant needs. A person must read it."""


def iso(text: str) -> str:
    return datetime.strptime(text, "%B %d, %Y").date().isoformat()


def clauses(text: str) -> list[dict[str, Any]]:
    """The agreement split into clauses with their character spans. Text before Article 1 is the preamble."""
    heads = list(ARTICLE.finditer(text))
    out: list[dict[str, Any]] = []
    if heads:
        start = text.find("This Patent License Agreement")
        if 0 <= start < heads[0].start():
            out.append(
                {"kind": "preamble", "start": start, "end": heads[0].start(), "text": text[start : heads[0].start()]}
            )
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[h.start() : end].strip()
        out.append({"kind": KINDS.get(h.group(2).lower(), "other"), "start": h.start(), "end": h.start() + len(body),
                    "text": body})  # fmt: skip
    return out


def extract(text: str, vocab: Any, stored_at: str) -> dict[str, Any]:
    """Read a grant out of an agreement's text. Every value names something the graph knows, or extraction fails."""
    from er.resolver import resolve

    text = re.sub(r"\s+", " ", text).strip()
    parts = {c["kind"]: c for c in clauses(text)}
    missing: list[str] = []

    def find(pattern: str, kind: str, name: str) -> re.Match[str] | None:
        m = re.search(pattern, parts[kind]["text"]) if kind in parts else None
        if m is None:
            missing.append(name)
        return m

    title = re.search(r"PATENT LICENSE AGREEMENT (\S+)", text)
    if title is None:
        raise ExtractionError("The document has no agreement title, so it may not be a license agreement.")
    excl = find(r"grants Licensee an? ([a-z -]+?) license", "grant", "license type")
    grant_text = parts.get("grant", {}).get("text", "")
    cases = re.findall(r"NASA Case No\. ([A-Z]{3}-\d+(?:-[A-Z0-9]+)*)", grant_text)
    numbers = [re.sub(r"\D", "", n) for n in re.findall(r"U\.S\. Patent No\. ([\d,]+)", grant_text)]
    field = find(r"The Field of Use is limited to (.+?)\.(?: |$)", "field", "field of use")
    terr = find(r"The Licensed Territory is (.+?)\.(?: |$)", "territory", "territory")
    term = find(rf"takes effect on {DATE} and remains in force until {DATE}", "term", "term")
    signed = re.search(rf"entered into on {DATE}", parts.get("preamble", {}).get("text", ""))
    # The licensee is the second party, named after NASA's own description and before ("Licensee").
    parties = parts.get("preamble", {}).get("text", "").split(", an agency of the United States,")[-1]
    who = re.search(r'^\s*(?:and\s+)?(.+?) \("Licensee"\)', parties)
    cap = re.search(r"no more than (\d+) licensees", parts.get("cap", {}).get("text", ""))
    if not cases and not numbers:
        missing.append("patent")
    if signed is None:
        missing.append("execution date")
    if who is None:
        missing.append("licensee")
    if missing:
        raise ExtractionError("The agreement does not state: " + ", ".join(missing))
    assert excl and field and terr and term and signed and who

    keys = sorted({vocab.cases[c] for c in cases if c in vocab.cases}
                  | {vocab.patent_numbers[n] for n in numbers if n in vocab.patent_numbers})  # fmt: skip
    if not keys:
        raise ExtractionError(f"No patent named in the agreement is in scope: {', '.join(cases + numbers)}")
    field_hit = vocab.fields.get(field.group(1).lower())
    if field_hit is None:
        raise ExtractionError(f"The field of use {field.group(1)!r} is not a concept in the field scheme.")
    code = re.search(r"\(ISO 3166 code ([A-Z0-9-]+)\)", terr.group(1))
    terr_hit = vocab.notations.get(code.group(1)) if code else vocab.territories.get(terr.group(1).lower())
    if terr_hit is None:
        raise ExtractionError(f"The territory {terr.group(1)!r} is not a concept in the territory scheme.")
    status, candidates = resolve(who.group(1), vocab.parties)
    matches = [c.party.iri for c in candidates if c.outcome.status == "match"]
    if status != "match" or len(set(matches)) != 1:
        raise ExtractionError(f"The licensee {who.group(1)!r} is not one known licensee. A steward must link it.")
    return {
        "agreement_id": title.group(1),
        "title": title.group(0),
        "stored_at": stored_at,
        "patent_keys": keys,
        "licensee": matches[0],
        "licensee_as_written": who.group(1),
        "exclusivity": excl.group(1),
        "field_concept": field_hit[0],
        "field_text": field.group(1),
        "territory": terr_hit[0],
        "executed_on": iso(signed.group(1)),
        "valid_from": iso(term.group(1)),
        "valid_to": iso(term.group(2)),
        "sublicense_allowed": "may not grant sublicenses" not in parts.get("sublicense", {}).get("text", ""),
        "co_exclusive_cap": int(cap.group(1)) if cap else None,
        "clauses": [c for c in clauses(text) if c["kind"] != "royalty"],
        "unrecognized_clauses": [c["text"][:200] for c in clauses(text) if c["kind"] == "other"],
    }


def proposal(record: dict[str, Any]) -> dict[str, Any]:
    """The steward event that puts the extracted grant forward."""
    return {
        "action": "propose_grant",
        "steward": PIPELINE,
        "role": "steward",
        "reason": f"Read from {record['stored_at']} by the ingestion workflow.",
        "params": record,
    }


# ---- Lambda handlers --------------------------------------------------------------------------------------------


def _base() -> Any:
    from api.index import base

    return base()


def start_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """S3 calls this when a PDF lands in the inbox. It starts one execution per file."""
    import boto3

    started = []
    for rec in event.get("Records", []):
        key = rec["s3"]["object"]["key"]
        name = re.sub(r"[^A-Za-z0-9_-]", "-", key)[:60] + "-" + rec["s3"]["object"].get("sequencer", "0")[-8:]
        run = boto3.client("stepfunctions").start_execution(
            stateMachineArn=os.environ["MACHINE"],
            name=name,
            input=json.dumps({"bucket": rec["s3"]["bucket"]["name"], "key": key}),
        )
        started.append(run["executionArn"])
    return {"started": started}


def ocr_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Textract reads the PDF. The job runs asynchronously, so this waits for it; agreements are a few pages."""
    import time

    import boto3

    textract = boto3.client("textract")
    loc = {"S3Object": {"Bucket": event["bucket"], "Name": event["key"]}}
    job = textract.start_document_text_detection(DocumentLocation=loc)["JobId"]
    lines: list[str] = []
    token = None
    while True:
        args: dict[str, Any] = {"JobId": job, **({"NextToken": token} if token else {})}
        out = textract.get_document_text_detection(**args)
        if out["JobStatus"] == "IN_PROGRESS":
            time.sleep(2)
            continue
        if out["JobStatus"] != "SUCCEEDED":
            raise ExtractionError(f"Textract could not read the document: {out['JobStatus']}")
        lines += [b["Text"] for b in out["Blocks"] if b["BlockType"] == "LINE"]
        token = out.get("NextToken")
        if not token:
            break
    return {**event, "text": "\n".join(lines), "pages": out.get("DocumentMetadata", {}).get("Pages", 0)}


def extract_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    from agent.parser import Vocabulary

    record = extract(event["text"], Vocabulary.from_store(_base()), f"s3://{event['bucket']}/{event['key']}")
    return {"bucket": event["bucket"], "key": event["key"], "record": record}


def check_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Propose the grant on a copy of the graph. SHACL runs inside the proposal, and a failure says what is wrong."""
    from kg.actions import ActionRejectedError, apply_event

    try:
        result = apply_event(_base().fork(), proposal(event["record"]))
    except ActionRejectedError as e:
        return {**event, "conforms": False, "problem": str(e)[:1500]}
    return {**event, "conforms": True, "candidate": result["candidate"]}


def await_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Park the proposal with its task token until a steward decides (decide_handler)."""
    import boto3

    item = {
        "id": event["execution"],
        "token": event["token"],
        "status": "waiting",
        "candidate": event["candidate"],
        "record": json.dumps(event["record"]),
        "events": json.dumps([]),
    }
    boto3.resource("dynamodb").Table(os.environ["PENDING_TABLE"]).put_item(Item=item)
    return {"parked": event["execution"]}


def decide_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """POST /ingest/decide {id, decision: approve|reject|second_review, reason}. The caller comes from the token.

    The approval runs through kg/actions on a copy of the graph, so the same Cedar policies and the two-person rule
    decide. When the approval needs counsel, the workflow keeps waiting, and counsel's second review releases it.
    """
    import boto3

    from kg.actions import ActionRejectedError, replay
    from service import identity
    from service.handler import respond

    claims = identity.claims_from_event(event)
    if claims is None:
        return respond(401, {"error": "Sign in first."})
    who = identity.principal_from_claims(claims)
    body = json.loads(event.get("body") or "{}")
    table = boto3.resource("dynamodb").Table(os.environ["PENDING_TABLE"])
    item = table.get_item(Key={"id": str(body.get("id", ""))}).get("Item")
    if not item or item["status"] not in ("waiting", "pending_second_review"):
        return respond(404, {"error": "No proposal is waiting under that id."})
    sfn = boto3.client("stepfunctions")
    record = json.loads(str(item["record"]))
    events = [proposal(record), *json.loads(str(item["events"]))]
    action = {"approve": "approve_fact", "reject": "reject_fact", "second_review": "second_review"}.get(
        str(body.get("decision"))
    )
    if action is None:
        return respond(422, {"error": "decision must be approve, reject, or second_review"})
    params: dict[str, Any] = {"candidate": str(item["candidate"])}
    if action == "second_review":
        params["approve"] = True
    step: dict[str, Any] = {
        "action": action,
        "steward": who.name,
        "role": who.role,
        "reason": str(body.get("reason", "")),
        "params": params,
    }
    try:
        store = replay(_base(), events + [step])
    except ActionRejectedError as e:
        return respond(403, {"error": str(e)})
    route = store.decided.get(str(item["candidate"]), {}).get("decision", "")
    done = [*json.loads(str(item["events"])), step]

    def mark(status: str) -> None:
        table.update_item(
            Key={"id": item["id"]},
            UpdateExpression="SET #s = :s, events = :e",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": status, ":e": json.dumps(done)},
        )

    if action == "reject_fact":
        sfn.send_task_failure(taskToken=str(item["token"]), error="Rejected", cause=step["reason"][:250])
        mark("rejected")
        return respond(200, {"status": "rejected"})
    if route == "pending_second_review":
        mark("pending_second_review")
        why = "The approval needs counsel's second review."
        return respond(202, {"status": "pending_second_review", "why": why})
    sfn.send_task_success(taskToken=str(item["token"]), output=json.dumps({"events": events[:1] + done}))
    mark("approved")
    return respond(200, {"status": "approved"})


def apply_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Replay the proposal and the approval on the graph snapshot, and send the new triples to Neptune."""
    from kg.actions import replay, to_sparql_update
    from service import neptune

    store = replay(_base(), event["decision"]["events"])
    updates = to_sparql_update(store)
    for u in updates:
        neptune.update(u)
    approved_at = store.events[-1]["at"]
    return {**event, "updates": len(updates), "approved_at": approved_at}


def rerun_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Run every booked request on the new grant's patents twice on Neptune: with records up to one second before
    the approval, and with the approval. The difference is what the new agreement changed."""
    from datetime import timedelta

    from rules.book import load_book, to_request
    from rules.engine import evaluate
    from service import neptune

    store = neptune.store()
    keys = set(event["record"]["patent_keys"])
    after = event["approved_at"]
    before = (datetime.fromisoformat(after.replace("Z", "+00:00")) - timedelta(seconds=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    changes = []
    for row in load_book():
        if row["patent_key"] not in keys:
            continue
        req = to_request(row)
        v0 = evaluate(store, req, cutoff=before, as_of="2026-11-01", user=PIPELINE).verdict
        v1 = evaluate(store, req, cutoff=after, as_of="2026-11-01", user=PIPELINE).verdict
        changes.append({"request": row["request_id"], "before": v0, "after": v1, "changed": v0 != v1})
    return {"agreement": event["record"]["agreement_id"], "approved_at": after, "requests": changes}
