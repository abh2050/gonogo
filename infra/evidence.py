"""Run the Gate 3 checks against a deployed GoNoGo stack and write docs/aws-evidence.json.

    uv run python infra/evidence.py

It loads the graphs into Neptune, creates one Cognito user per role, and then checks, through API Gateway with
real tokens: that Verified Permissions answers every policy question as the local Cedar engine does; that the
leakage attacks fail for every role; that Neptune decides every request as the in-memory engine does; and that the
two-person rule holds with two different people. It records counts and timings, never a token or a password.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from botocore.config import Config
from rdflib import Literal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "infra"))

import users  # noqa: E402

from authz import avp, cedar, matrix  # noqa: E402
from gonogo import aws  # noqa: E402
from kg.ns import GRAPH_APPROVED, GRAPH_CANDIDATE, GRAPH_RELEASE, GRAPH_ROYALTY  # noqa: E402
from rules.book import load_book, to_request  # noqa: E402
from rules.engine import evaluate  # noqa: E402
from service import query as q  # noqa: E402
from tests.leakage.test_query_service import (  # noqa: E402
    ALWAYS_REFUSED,
    FAKE_GRAPHS,
    READ_EVERYTHING_IT_MAY,
    REAL,
)

OUT = ROOT / "docs" / "aws-evidence.json"
DECOY = "https://w3id.org/gonogo/id/ownership/LAR-17381-1/candidate"
NOW, AS_OF = "2026-11-01T00:00:00Z", "2026-11-01"
checks: list[dict[str, Any]] = []


def record(name: str, ok: bool, detail: str, **numbers: Any) -> bool:
    checks.append({"check": name, "passed": ok, "detail": detail, **numbers})
    print(("PASS " if ok else "FAIL ") + name + " :: " + detail)
    return ok


def outputs(cf: Any, stack: str) -> dict[str, str]:
    return {o["OutputKey"]: o["OutputValue"] for o in cf.describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]}


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return round(s[min(len(s) - 1, int(p * len(s)))] * 1000)


def main() -> None:
    session = aws.session()
    cf = session.client("cloudformation")
    core, api = outputs(cf, "gonogo-core"), outputs(cf, "gonogo-api")
    base = api["ApiUrl"].rstrip("/")
    has_graph = "NeptuneEndpoint" in api

    # ---- 1. Load the graphs into Neptune --------------------------------------------------------------------
    started = datetime.now(UTC)
    if has_graph:
        s3 = session.client("s3")
        graphs = {
            GRAPH_RELEASE: "release",
            GRAPH_APPROVED: "approved",
            GRAPH_CANDIDATE: "candidate",
            GRAPH_ROYALTY: "royalty",
        }
        for name in graphs.values():
            s3.upload_file(str(ROOT / "build" / "kg" / f"{name}.ttl"), core["GraphBucket"], f"{name}.ttl")
        lam = session.client("lambda", config=Config(read_timeout=900, retries={"max_attempts": 0}))
        t = time.time()
        out = lam.invoke(
            FunctionName=api["LoaderFunction"],
            Payload=json.dumps(
                {"bucket": core["GraphBucket"], "files": {iri: f"{n}.ttl" for iri, n in graphs.items()}}
            ),
        )
        body = json.loads(out["Payload"].read())
        from kg.store import Store

        local = Store.from_build(include_royalty=True)
        expected = {iri: len(local.base[iri]) for iri in graphs}
        record(
            "Neptune holds every triple of the four graphs",
            body.get("loaded") == expected,
            f"{sum(expected.values()):,} triples loaded in {time.time() - t:.0f} s",
            triples=expected,
        )

    # ---- 2. Verified Permissions answers as local Cedar does -------------------------------------------------
    avp_client = session.client("verifiedpermissions")
    asked = same = 0
    mismatches: list[str] = []
    for _label, action, resource, ctx in matrix.CASES:
        for role in cedar.ROLES:
            who = cedar.Principal("pat", role)
            local_allowed = cedar.authorize(who, action, resource, ctx).allowed
            remote = avp_client.is_authorized(
                policyStoreId=core["PolicyStoreId"], **avp.request(who, action, resource, ctx)
            )
            asked += 1
            if (remote["decision"] == "ALLOW") == local_allowed:
                same += 1
            else:
                mismatches.append(f"{role} {action}")
    record(
        "Verified Permissions answers every policy question as local Cedar does",
        same == asked,
        f"{same} of {asked} answers match across {len(matrix.CASES)} actions and {len(cedar.ROLES)} roles",
        mismatches=mismatches,
    )

    # ---- 3. Cognito users and tokens ------------------------------------------------------------------------
    idp = session.client("cognito-idp")
    tokens: dict[str, str] = {}
    saved = users.ensure_users(
        session, core["UserPoolId"]
    )  # the passwords live in infra/users.json, so a rerun keeps them
    for name, who in saved.items():
        auth = idp.admin_initiate_auth(
            UserPoolId=core["UserPoolId"],
            ClientId=core["UserPoolClientId"],
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": name, "PASSWORD": who["password"]},
        )
        tokens[name] = auth["AuthenticationResult"]["IdToken"]
    client = httpx.Client(timeout=40.0)

    def call(user: str | None, method: str, path: str, body: Any = None) -> httpx.Response:
        headers = {"Authorization": tokens[user]} if user else {}
        return client.request(method, base + path, json=body, headers=headers)

    record(
        "The gateway refuses a call with no token",
        call(None, "GET", "/api/health").status_code == 401,
        "401 without an Authorization header",
    )

    # ---- 4. The leakage suite, for every role, through the gateway -------------------------------------------
    if has_graph:
        from tests.leakage.conftest import ROYALTY_PATTERNS, leaks

        local_store = Store.from_build(include_royalty=True)
        elsewhere = {
            str(o)
            for g in (GRAPH_APPROVED, GRAPH_RELEASE, GRAPH_CANDIDATE)
            for _, _, o in local_store.base[g]
            if isinstance(o, Literal)
        }
        marks = sorted(
            {str(o) for _, _, o in local_store.base[GRAPH_ROYALTY] if isinstance(o, Literal) and len(str(o)) >= 8}
            - elsewhere
        )
        assert marks and ROYALTY_PATTERNS
        attacks = refused = leaked = disagree = 0
        for user, role in ((n, u["role"]) for n, u in saved.items()):
            who = cedar.Principal(user, role)
            suite = list(ALWAYS_REFUSED.values()) + [
                f"SELECT * FROM <{iri}> WHERE {{ ?s ?p ?o }} LIMIT 5" for iri in FAKE_GRAPHS
            ]
            for iri in REAL.values():
                suite.append(f"SELECT (COUNT(*) AS ?n) FROM <{iri}> WHERE {{ ?s ?p ?o }}")
            for text in suite:
                try:
                    q.validate(who, text)
                    local_ok = True
                except q.QueryRefusedError:
                    local_ok = False
                r = call(user, "POST", "/query", {"query": text})
                attacks += 1
                if r.status_code in (400, 403):
                    refused += 1
                if leaks(r.text, marks) and role != "counsel":
                    leaked += 1
                if (r.status_code == 200) != local_ok:
                    disagree += 1
            if "royalty" not in cedar.readable_graphs(who):
                for pattern in READ_EVERYTHING_IT_MAY:
                    for graph in cedar.readable_graphs(who):
                        r = call(
                            user,
                            "POST",
                            "/query",
                            {"query": f"SELECT * FROM <{REAL[graph]}> WHERE {{ {pattern} }} LIMIT 1000"},
                        )
                        attacks += 1
                        if r.status_code == 200 and leaks(r.text, marks):
                            leaked += 1
        record(
            "No role reads a graph it may not, and Neptune never sees a refused query",
            leaked == 0 and disagree == 0,
            f"{attacks} queries across {len(saved)} users: {refused} refused, {leaked} leaked royalty text, "
            f"{disagree} where the deployment and the local service disagreed",
            attacks=attacks,
            refused=refused,
            leaked=leaked,
            disagreements=disagree,
        )
        bad_body = [
            call("pat-manager", "POST", "/query", {"query": "SELECT * WHERE {}" + " " * 9000}).status_code,
            call("pat-manager", "POST", "/query", {"query": "ASK {}", "extra": 1}).status_code,
            call("pat-manager", "POST", "/query", {}).status_code,
        ]
        record(
            "The gateway rejects oversize, extra-field, and empty bodies before any Lambda runs",
            bad_body == [400, 400, 400],
            f"statuses {bad_body}",
        )

        # ---- 5. Neptune decides as the in-memory engine does ----------------------------------------------------
        local_times: list[float] = []
        remote_times: list[float] = []
        mismatched = []
        rows = load_book()
        for row in rows:
            request = to_request(row)
            t = time.time()
            local_record = evaluate(local_store, request, cutoff=NOW, as_of=AS_OF)
            local_times.append(time.time() - t)
            t = time.time()
            r = call(
                "pat-manager",
                "POST",
                "/decide",
                {"request": {**request.canonical(), "licensee_ids": list(request.licensee_ids)}},
            )
            remote_times.append(time.time() - t)
            sig = r.json().get("decision", {}).get("signature") if r.status_code == 200 else None
            if sig != local_record.signature:
                mismatched.append(row["request_id"])
        record(
            "Decisions made on Neptune carry the same signatures as decisions made in memory",
            not mismatched,
            f"{len(rows) - len(mismatched)} of {len(rows)} signatures match",
            mismatched=mismatched,
            neptune_ms={"p50": pct(remote_times, 0.5), "p95": pct(remote_times, 0.95)},
            in_memory_ms={"p50": pct(local_times, 0.5), "p95": pct(local_times, 0.95)},
        )
        sample = {**to_request(rows[0]).canonical()}
        refused_roles = {
            u: call(u, "POST", "/decide", {"request": sample}).status_code
            for u in ("fin-analyst", "aud-auditor", "owen-owner")
        }
        record(
            "Roles that may not ask are refused on the Neptune path",
            set(refused_roles.values()) == {403},
            f"statuses {refused_roles}",
        )

    # ---- 6. The two-person rule with two people --------------------------------------------------------------
    # The decoy's patent is LAR-17381-1; the request book names it.
    decoy_row = next(r for r in load_book() if r["patent_key"] == "LAR-17381-1")
    ask = decoy_row["text"]
    made: list[dict[str, Any]] = []
    first = call("pat-manager", "POST", "/api/decide", {"text": ask}).json()["decision"]
    made.append(first)
    before = first["verdict"]
    approve = {
        "event": {
            "action": "approve_fact",
            "reason": "The licensee summary looks complete.",
            "params": {"candidate": DECOY},
        }
    }
    held = call("ann-steward", "POST", "/api/act", approve)
    route = held.json()["result"]["route"] if held.status_code == 200 else held.text[:80]
    events = held.json()["events"] if held.status_code == 200 else []
    held_decision = call("pat-manager", "POST", "/api/decide", {"text": ask, "events": events}).json()["decision"]
    made.append(held_decision)
    mid = held_decision["verdict"]
    second = {
        "events": events,
        "event": {"action": "second_review", "reason": "Checked the assignment.", "params": {"candidate": DECOY}},
    }
    other_steward = call("ben-steward", "POST", "/api/act", second)
    same_person = call("ann-steward", "POST", "/api/act", second)
    counsel = call("dee-counsel", "POST", "/api/act", second)
    final = (
        call("pat-manager", "POST", "/api/decide", {"text": ask, "events": counsel.json()["events"]}).json()["decision"]
        if counsel.status_code == 200
        else {"verdict": "n/a"}
    )
    if "id" in final:
        made.append(final)
    after = final["verdict"]
    log = counsel.json()["events"] if counsel.status_code == 200 else []
    record(
        "A steward's approval of the decoy waits for a different counsel, and only then reaches GO",
        (before, route, mid, other_steward.status_code, same_person.status_code, after)
        == ("COUNSEL", "pending_second_review", "COUNSEL", 422, 422, "GO"),
        f"verdict {before}; first approval {route}; still {mid}; "
        f"a second steward refused ({other_steward.status_code}); "
        f"the first approver refused ({same_person.status_code}); counsel approved; verdict {after}",
        approvers=[(e["steward"], e["role"]) for e in log],
    )
    reads = {
        "manager reads the steward queue": call("pat-manager", "POST", "/api/queue", {}).status_code,
        "steward reads the steward queue": call("ann-steward", "POST", "/api/queue", {}).status_code,
        "finance asks a question": call("fin-analyst", "POST", "/api/decide", {"text": ask}).status_code,
        "auditor asks a question": call("aud-auditor", "POST", "/api/decide", {"text": ask}).status_code,
    }
    record(
        "Cedar gates every read behind the gateway",
        reads
        == {
            "manager reads the steward queue": 403,
            "steward reads the steward queue": 200,
            "finance asks a question": 403,
            "auditor asks a question": 403,
        },
        f"statuses {reads}",
    )
    forged = call(
        "ben-steward",
        "POST",
        "/api/act",
        {
            "event": {
                "action": "second_review",
                "steward": "dee-counsel",
                "role": "counsel",
                "reason": "Pretending.",
                "params": {"candidate": DECOY},
            },
            "events": events,
        },
    )
    record(
        "A body that claims another identity is ignored in favor of the token",
        forged.status_code == 422,
        f"status {forged.status_code}",
    )

    # ---- 7. The audit trail ----------------------------------------------------------------------------------
    time.sleep(3)
    table, bucket = core["DecisionsTable"], core["AuditBucket"]
    in_table = in_bucket = 0
    modes: set[str | None] = set()
    for d in made:
        key = f"{d['id']}#{d['events_applied']}"
        if "Item" in session.client("dynamodb").get_item(TableName=table, Key={"decision_id": {"S": key}}):
            in_table += 1
        head = session.client("s3").head_object(Bucket=bucket, Key=f"decisions/{d['id']}-{d['events_applied']}.json")
        in_bucket += 1
        modes.add(head.get("ObjectLockMode"))
    mode = ",".join(sorted(str(m) for m in modes))
    record(
        "Every decision is in DynamoDB and in a locked S3 object",
        # The three permitted decisions of the two-person flow. The two refused callers leave no record.
        len(made) == in_table == in_bucket == 3 and modes == {"GOVERNANCE"},
        f"{in_table} of {len(made)} decisions are in the table and {in_bucket} in the bucket, Object Lock mode {mode}",
    )

    # ---- 8. Engine latency -----------------------------------------------------------------------------------
    times = []
    for row in load_book()[:20]:
        t = time.time()
        call("pat-manager", "POST", "/api/decide", {"text": row["text"]})
        times.append(time.time() - t)
    passed = sum(c["passed"] for c in checks)
    report = {
        "ran_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "region": "us-east-2",
        "account": "…" + session.client("sts").get_caller_identity()["Account"][-4:],
        "neptune": has_graph,
        "engine_decide_ms": {"p50": pct(times, 0.5), "p95": pct(times, 0.95), "n": len(times)},
        "passed": passed,
        "total": len(checks),
        "checks": checks,
    }
    OUT.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"\n{passed} of {len(checks)} checks passed. Wrote {OUT.relative_to(ROOT)}")
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
