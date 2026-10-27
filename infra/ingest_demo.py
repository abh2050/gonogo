"""Run the ingestion workflow end to end on the deployed stacks, and write docs/ingestion-run.json.

    uv run python infra/ingest_demo.py          after: cdk deploy gonogo-core gonogo-api -c deployNeptune=true
                                                       -c deployIngest=true, and infra/evidence.py has loaded the graph

The run, with real users and real services:

 1. A sample agreement PDF (data/ingest/AGR-0901.pdf) goes into the S3 inbox, and the state machine starts.
 2. Textract reads it, the extractor builds a grant, SHACL checks it, and the workflow waits for a person.
 3. ann-steward approves. The first sample moves a verdict down (GO to NO GO), so one steward is enough. If an
    approval ever needs counsel, Cedar answers 202 and the run continues at step 4.
 4. dee-counsel gives the second review (only when step 3 said so). The workflow resumes, writes the grant to
    Neptune, and runs the booked requests on the patent again.
 5. The second sample (AGR-0902) carries a planted instruction. It runs through the same steps, and no verdict moves.

The script prints each step and the verdicts that changed, and keeps the execution history for the docs.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import users  # noqa: E402

from gonogo import aws  # noqa: E402

SAMPLES = ROOT / "data" / "ingest"
OUT = ROOT / "docs" / "ingestion-run.json"


def stack(cf: Any, name: str) -> dict[str, str]:
    return users.stack_outputs(cf, name)


def token(session: Any, core: dict[str, str], who: dict[str, str], name: str) -> str:
    out = session.client("cognito-idp").admin_initiate_auth(
        UserPoolId=core["UserPoolId"],
        ClientId=core["UserPoolClientId"],
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": name, "PASSWORD": who["password"]},
    )
    return str(out["AuthenticationResult"]["IdToken"])


def wait_for(sfn: Any, arn: str, states: tuple[str, ...], seconds: int = 300) -> dict[str, Any]:
    """Poll an execution until it is waiting at, or has finished, one of the named states."""
    end = time.time() + seconds
    while time.time() < end:
        run = sfn.describe_execution(executionArn=arn)
        if run["status"] != "RUNNING":
            return dict(run)
        events = sfn.get_execution_history(executionArn=arn, reverseOrder=True, maxResults=20)["events"]
        for e in events:
            if e["type"] == "TaskStateEntered" and e.get("stateEnteredEventDetails", {}).get("name") == "AwaitApproval":
                return {"status": "WAITING", "executionArn": arn}
        time.sleep(4)
    raise TimeoutError(f"{arn} did not reach {states} in {seconds} s")


def decide(client: httpx.Client, base: str, tok: str, exec_id: str, decision: str, reason: str) -> httpx.Response:
    return client.post(
        f"{base}/ingest/decide",
        headers={"Authorization": tok},
        json={"id": exec_id, "decision": decision, "reason": reason},
    )


def run_one(session: Any, pdf: Path, inbox: str, machine: str, base: str, toks: dict[str, str]) -> dict[str, Any]:
    s3, sfn = session.client("s3"), session.client("stepfunctions")
    started = datetime.now(UTC)
    s3.upload_file(str(pdf), inbox, pdf.name)
    print(f"{pdf.name}: uploaded to the inbox")
    arn = ""
    for _ in range(30):
        runs = [
            r
            for r in sfn.list_executions(stateMachineArn=machine, maxResults=20)["executions"]
            if r["startDate"] >= started and pdf.stem in r["name"]
        ]
        if runs:
            arn = runs[0]["executionArn"]
            break
        time.sleep(2)
    assert arn, "the state machine did not start"
    exec_name = arn.rsplit(":", 1)[-1]
    print(f"  execution {exec_name} started")
    state = wait_for(sfn, arn, ("WAITING",))
    steps = [e["stateEnteredEventDetails"]["name"] for e in sfn.get_execution_history(executionArn=arn)["events"]
             if e["type"].endswith("StateEntered")]  # fmt: skip
    print("  steps so far:", " > ".join(steps))
    result: dict[str, Any] = {"file": pdf.name, "execution": exec_name, "steps": steps, "decisions": []}
    if state["status"] != "WAITING":
        result["status"] = state["status"]
        return result
    client = httpx.Client(timeout=60.0)
    first = decide(client, base, toks["ann-steward"], exec_name, "approve", "Checked against the signed PDF.")
    result["decisions"].append({"who": "ann-steward", "status": first.status_code, "body": first.json()})
    print("  ann-steward approves:", first.status_code, first.json())
    if first.status_code == 202:
        second = decide(client, base, toks["dee-counsel"], exec_name, "second_review", "Reviewed the overlap.")
        result["decisions"].append({"who": "dee-counsel", "status": second.status_code, "body": second.json()})
        print("  dee-counsel second review:", second.status_code, second.json())
    final = sfn.describe_execution(executionArn=arn)
    for _ in range(60):
        if final["status"] != "RUNNING":
            break
        time.sleep(4)
        final = sfn.describe_execution(executionArn=arn)
    result["status"] = final["status"]
    result["output"] = json.loads(final.get("output", "null"))
    result["steps"] = [
        e["stateEnteredEventDetails"]["name"]
        for e in sfn.get_execution_history(executionArn=arn)["events"]
        if e["type"].endswith("StateEntered")
    ]
    print("  finished:", final["status"])
    for r in (result["output"] or {}).get("requests", []):
        print(f"    {r['request']}: {r['before']} -> {r['after']}" + ("  (changed)" if r["changed"] else ""))
    return result


def main() -> None:
    session = aws.session()
    cf = session.client("cloudformation")
    core, api = stack(cf, "gonogo-core"), stack(cf, "gonogo-api")
    base = api["ApiUrl"].rstrip("/")
    saved = users.ensure_users(session, core["UserPoolId"])
    toks = {n: token(session, core, saved[n], n) for n in ("ann-steward", "dee-counsel")}
    runs = [
        run_one(session, SAMPLES / f"{a}.pdf", api["InboxBucket"], api["MachineArn"], base, toks)
        for a in ("AGR-0901", "AGR-0902")
    ]
    OUT.write_text(json.dumps({"at": datetime.now(UTC).isoformat(timespec="seconds"), "runs": runs}, indent=1) + "\n")
    print("wrote", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
