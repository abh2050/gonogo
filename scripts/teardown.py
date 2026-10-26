"""Remove every GoNoGo AWS resource except the budget, then list what is left.

    uv run python scripts/teardown.py            destroy gonogo-api and gonogo-core, then report
    uv run python scripts/teardown.py --report   report only, change nothing

Run it after every AWS session. Neptune Serverless bills while idle, and the audit bucket's Object Lock needs a
bypass before CloudFormation can delete it. The script empties the buckets, destroys the stacks, and then looks
for anything that still carries the GoNoGo name or tag. The budget stack stays on purpose: it is free and it
watches for spend that something else forgot. The report goes to docs/aws-teardown.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gonogo import aws

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "docs" / "aws-teardown.json"
STACKS = ["gonogo-api", "gonogo-core"]
KEPT_ON_PURPOSE = {
    "AWS::Budgets::Budget gonogo-monthly": "Free. It emails at 50, 80, and 100 percent of the monthly limit."
}


def clients() -> dict[str, Any]:
    s = aws.session()
    return {
        name: s.client(name)
        for name in (
            "cloudformation",
            "s3",
            "neptune",
            "lambda",
            "logs",
            "dynamodb",
            "cognito-idp",
            "apigateway",
            "verifiedpermissions",
            "kms",
            "ec2",
            "events",
            "budgets",
            "sts",
            "ecs",
        )
    }


def stack_outputs(c: dict[str, Any], name: str) -> dict[str, str]:
    try:
        stack = c["cloudformation"].describe_stacks(StackName=name)["Stacks"][0]
    except Exception:
        return {}
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def empty_bucket(c: dict[str, Any], bucket: str) -> int:
    """Delete every object version and delete marker. A locked bucket needs the governance bypass; others reject it."""
    s3, removed = c["s3"], 0
    try:
        locked = (
            s3.get_object_lock_configuration(Bucket=bucket)["ObjectLockConfiguration"]["ObjectLockEnabled"] == "Enabled"
        )
    except s3.exceptions.ClientError:
        locked = False
    extra = {"BypassGovernanceRetention": True} if locked else {}
    try:
        pages = s3.get_paginator("list_object_versions").paginate(Bucket=bucket)
        for page in pages:
            items = [
                {"Key": v["Key"], "VersionId": v["VersionId"]}
                for v in (page.get("Versions", []) + page.get("DeleteMarkers", []))
            ]
            for i in range(0, len(items), 900):
                s3.delete_objects(Bucket=bucket, Delete={"Objects": items[i : i + 900], "Quiet": True}, **extra)
                removed += len(items[i : i + 900])
    except s3.exceptions.NoSuchBucket:
        pass
    return removed


def destroy(c: dict[str, Any]) -> list[str]:
    log: list[str] = []
    out = stack_outputs(c, "gonogo-core")
    for key in ("AuditBucket", "GraphBucket"):
        if bucket := out.get(key):
            log.append(f"emptied {bucket}: {empty_bucket(c, bucket)} objects")
    env = {
        **os.environ,
        "AWS_PROFILE": "awsnew",
        "AWS_REGION": "us-east-2",
        "JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION": "1",
    }
    present = [name for name in STACKS if stack_exists(c, name)]
    if present:
        subprocess.run(
            ["npx", "--yes", "aws-cdk@2", "destroy", *present, "--force"], cwd=ROOT / "infra", env=env, check=True
        )
        log.append("cdk destroy " + " ".join(present))
    # The helper that empties a bucket on delete makes a log group of its own, which CloudFormation does not own.
    for lg in c["logs"].describe_log_groups(logGroupNamePrefix="/aws/lambda/gonogo")["logGroups"]:
        c["logs"].delete_log_group(logGroupName=lg["logGroupName"])
        log.append(f"deleted log group {lg['logGroupName']}")
    return log


def stack_exists(c: dict[str, Any], name: str) -> bool:
    try:
        return bool(c["cloudformation"].describe_stacks(StackName=name)["Stacks"])
    except c["cloudformation"].exceptions.ClientError:
        return False


def leftovers(c: dict[str, Any]) -> list[dict[str, str]]:
    """Everything in us-east-2 that still carries the GoNoGo name or tag."""
    found: list[dict[str, str]] = []

    def add(kind: str, name: str, why: str) -> None:
        found.append({"resource": f"{kind} {name}", "why": KEPT_ON_PURPOSE.get(f"{kind} {name}", why)})

    for s in c["cloudformation"].list_stacks(
        StackStatusFilter=[
            "CREATE_COMPLETE",
            "UPDATE_COMPLETE",
            "ROLLBACK_COMPLETE",
            "UPDATE_ROLLBACK_COMPLETE",
            "DELETE_FAILED",
            "CREATE_IN_PROGRESS",
            "DELETE_IN_PROGRESS",
            "CREATE_FAILED",
        ]
    )["StackSummaries"]:
        if s["StackName"].startswith("gonogo"):
            add("AWS::CloudFormation::Stack", s["StackName"], f"status {s['StackStatus']}")
    for cl in c["neptune"].describe_db_clusters()["DBClusters"]:
        if cl["DBClusterIdentifier"].startswith("gonogo"):
            add("AWS::Neptune::DBCluster", cl["DBClusterIdentifier"], "bills while idle")
    for snap in c["neptune"].describe_db_cluster_snapshots(SnapshotType="manual")["DBClusterSnapshots"]:
        if snap["DBClusterIdentifier"].startswith("gonogo"):
            add("AWS::Neptune::Snapshot", snap["DBClusterSnapshotIdentifier"], "storage cost")
    for fn in c["lambda"].list_functions()["Functions"]:
        if fn["FunctionName"].startswith("gonogo"):
            add("AWS::Lambda::Function", fn["FunctionName"], "no idle cost")
    for lg in c["logs"].describe_log_groups(logGroupNamePrefix="/aws/lambda/gonogo")["logGroups"]:
        add("AWS::Logs::LogGroup", lg["logGroupName"], "three-day retention")
    for b in c["s3"].list_buckets()["Buckets"]:
        if b["Name"].startswith("gonogo-"):
            add("AWS::S3::Bucket", b["Name"], "storage cost")
    for t in c["dynamodb"].list_tables()["TableNames"]:
        if t.startswith("gonogo"):
            add("AWS::DynamoDB::Table", t, "storage cost")
    for p in c["cognito-idp"].list_user_pools(MaxResults=60)["UserPools"]:
        if p["Name"] == "gonogo":
            add("AWS::Cognito::UserPool", p["Id"], "free tier")
    for a in c["apigateway"].get_rest_apis()["items"]:
        if a["name"] == "gonogo":
            add("AWS::ApiGateway::RestApi", a["id"], "no idle cost")
    for ps in c["verifiedpermissions"].list_policy_stores()["policyStores"]:
        if "GoNoGo" in ps.get("description", ""):
            add("AWS::VerifiedPermissions::PolicyStore", ps["policyStoreId"], "no idle cost")
    for alias in c["kms"].list_aliases()["Aliases"]:
        if alias["AliasName"] == "alias/gonogo":
            add("AWS::KMS::Alias", alias["AliasName"], "a key bills about a dollar a month")
    for k in c["kms"].list_keys()["Keys"]:
        meta = c["kms"].describe_key(KeyId=k["KeyId"])["KeyMetadata"]
        if meta["KeyManager"] != "CUSTOMER" or meta["KeyState"] not in ("Enabled", "PendingDeletion"):
            continue
        tags = {t["TagKey"]: t["TagValue"] for t in c["kms"].list_resource_tags(KeyId=k["KeyId"]).get("Tags", [])}
        if tags.get("project") == "gonogo":
            when = str(meta.get("DeletionDate", ""))[:10]
            why = (
                f"pending deletion until {when}, the shortest wait KMS allows; not billed"
                if meta["KeyState"] == "PendingDeletion"
                else "a key bills about a dollar a month"
            )
            add("AWS::KMS::Key", k["KeyId"], why)
    for v in c["ec2"].describe_vpcs(Filters=[{"Name": "tag:project", "Values": ["gonogo"]}])["Vpcs"]:
        add("AWS::EC2::VPC", v["VpcId"], "no idle cost")
    for bus in c["events"].list_event_buses(NamePrefix="gonogo")["EventBuses"]:
        add("AWS::Events::EventBus", bus["Name"], "no idle cost")
    for ecs in c["ecs"].list_clusters()["clusterArns"]:
        if "gonogo" in ecs:
            add("AWS::ECS::Cluster", ecs, "bills while tasks run")
    account = c["sts"].get_caller_identity()["Account"]
    for b in c["budgets"].describe_budgets(AccountId=account).get("Budgets", []):
        if b["BudgetName"].startswith("gonogo"):
            add("AWS::Budgets::Budget", b["BudgetName"], "")
    return found


def main() -> None:
    report_only = "--report" in sys.argv
    c = clients()
    previous = json.loads(REPORT.read_text())["actions"] if REPORT.exists() else []
    log = previous if report_only else previous + destroy(c)
    left = leftovers(c)
    billing = [x for x in left if any(w in x["why"] for w in ("bills", "storage cost", "a key bills"))]
    out = {
        "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "region": "us-east-2",
        "actions": log,
        "left_behind": left,
        "still_billing": billing,
    }
    REPORT.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    if billing:
        print(f"\n{len(billing)} resource(s) still bill. Remove them or explain each one.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
