"""Write docs/aws-resources.md: every resource the GoNoGo stacks create, read from the synthesized templates.

    uv run python infra/inventory.py

The list comes from the CloudFormation templates that CDK produces, so it cannot drift from what deploys. A test
fails when the file is out of date, or when a stack gains a resource type that has no description here.
"""

from __future__ import annotations

import collections
import sys
import tempfile
from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk import assertions

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stacks  # noqa: E402

OUT = ROOT / "docs" / "aws-resources.md"

# type -> (what it is for, what it costs while nothing is using it)
PURPOSE: dict[str, tuple[str, str]] = {
    "AWS::Cognito::UserPool": ("The sign-in directory. Admin-created users only, no self sign-up.", "Free"),
    "AWS::Cognito::UserPoolClient": ("The browser app's client for the user name and password sign-in.", "Free"),
    "AWS::Cognito::UserPoolGroup": ("One group per role. A token carries the group, and Cedar reads it.", "Free"),
    "AWS::DynamoDB::Table": ("One summary row per decision, with point-in-time recovery.", "Cents of storage"),
    "AWS::Events::EventBus": ("Receives fact approved and action events from the engine.", "Free"),
    "AWS::IAM::Role": ("A Lambda's identity, with only the permissions its code uses.", "Free"),
    "AWS::IAM::Policy": ("The permissions attached to a role.", "Free"),
    "AWS::KMS::Alias": ("The friendly name of the project key.", "Free"),
    "AWS::KMS::Key": ("Encrypts the buckets, the table, and Neptune. It rotates every year.", "About $1 a month"),
    "AWS::Lambda::Function": ("Code that runs on demand. See the table of functions below.", "Free while idle"),
    "AWS::Lambda::Permission": ("Lets API Gateway call a Lambda.", "Free"),
    "AWS::Lambda::LayerVersion": ("The AWS CLI layer that the UI deploy step uses to copy files.", "Free"),
    "AWS::S3::Bucket": ("Audit copies (Object Lock), graph files for loading, or the UI's files.", "Cents of storage"),
    "AWS::S3::BucketPolicy": ("Forces HTTPS, and for the UI bucket admits only this CloudFront distribution.", "Free"),
    "AWS::VerifiedPermissions::PolicyStore": (
        "Holds the Cedar policies and their schema, in strict validation.",
        "Free while idle",
    ),
    "AWS::VerifiedPermissions::Policy": (
        "One Cedar policy, such as the rule that nobody approves what they proposed.",
        "Free",
    ),
    "Custom::S3AutoDeleteObjects": ("Empties a bucket when the stack is deleted, so teardown leaves nothing.", "Free"),
    "Custom::CDKBucketDeployment": ("Copies the built UI and its config.json into the site bucket on deploy.", "Free"),
    "AWS::ApiGateway::RestApi": ("The front door of the API, regional, behind CloudFront.", "Free while idle"),
    "AWS::ApiGateway::Resource": ("A path in the API.", "Free"),
    "AWS::ApiGateway::Method": ("A route. Every one requires a Cognito token.", "Free"),
    "AWS::ApiGateway::Authorizer": ("Verifies the Cognito token before any Lambda runs.", "Free"),
    "AWS::ApiGateway::Model": ("The JSON shape that a request body must have.", "Free"),
    "AWS::ApiGateway::RequestValidator": ("Rejects an oversize or malformed body at the gateway.", "Free"),
    "AWS::ApiGateway::Deployment": ("A published version of the API.", "Free"),
    "AWS::ApiGateway::Stage": ("The `prod` stage, throttled at 20 requests a second.", "Free while idle"),
    "AWS::EC2::VPC": ("The private network around Neptune and two Lambdas. No internet gateway, no NAT.", "Free"),
    "AWS::EC2::Subnet": ("An isolated subnet in one Availability Zone.", "Free"),
    "AWS::EC2::RouteTable": ("Routes for a subnet. There is no route to the internet.", "Free"),
    "AWS::EC2::SubnetRouteTableAssociation": ("Attaches a route table to a subnet.", "Free"),
    "AWS::EC2::SecurityGroup": ("Admits Neptune's port only from members of the same group.", "Free"),
    "AWS::EC2::SecurityGroupIngress": ("The one inbound rule: Lambda to Neptune on port 8182.", "Free"),
    "AWS::EC2::VPCEndpoint": ("A gateway endpoint so the in-VPC Lambdas reach S3 without the internet.", "Free"),
    "AWS::Logs::LogGroup": ("A Lambda's log, kept three days.", "Cents"),
    "AWS::Neptune::DBSubnetGroup": ("Tells Neptune which subnets it may use.", "Free"),
    "AWS::Neptune::DBCluster": (
        "The graph database: serverless, IAM-only, encrypted with the project key.",
        "Yes: bills while it exists",
    ),
    "AWS::Neptune::DBInstance": (
        "The one serverless instance, scaling between 1 and 4 capacity units.",
        "Yes: about $0.16 per unit-hour",
    ),
    "AWS::CloudFront::Distribution": ("The one address for the UI and the API, over HTTPS.", "Free while idle"),
    "AWS::CloudFront::OriginAccessControl": ("Signs CloudFront's requests to the private bucket.", "Free"),
    "AWS::CloudFront::ResponseHeadersPolicy": (
        "Adds security headers, and a strict content policy to the app.",
        "Free",
    ),
    "AWS::StepFunctions::StateMachine": (
        "The ingestion workflow: read a PDF, extract a grant, check it, wait for a steward, write it, rerun.",
        "Free while idle",
    ),
    "Custom::S3BucketNotifications": ("Lets the ingestion inbox start the workflow when a PDF arrives.", "Free"),
    "AWS::S3Vectors::VectorBucket": ("Holds the benchmark's vector index.", "Cents of storage"),
    "AWS::S3Vectors::Index": ("The benchmark's search index over the document corpus.", "Cents of storage"),
    "AWS::Bedrock::KnowledgeBase": (
        "Embeds the corpus with Titan and answers search queries for answerer A.",
        "Free while idle",
    ),
    "AWS::Bedrock::DataSource": ("Points the Knowledge Base at the corpus bucket and chunks its documents.", "Free"),
    "AWS::Budgets::Budget": (
        "A $10 monthly budget on GoNoGo's services that emails at 50, 80, and 100 percent.",
        "Free; survives teardown",
    ),
}

STACKS = {
    "gonogo-core": "Identity, keys, storage, policies",
    "gonogo-api": "The network, the graph database, the functions, the API, and the ingestion workflow",
    "gonogo-ui": "Where the UI lives",
    "gonogo-eval": "The benchmark's vector search: a corpus bucket, a vector index, and a Knowledge Base",
    "gonogo-budget": "The cost alarm",
}


def synthesize() -> dict[str, dict[str, Any]]:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "handler.py").write_text("def handler(e, c): return {}\n")
    (tmp / "dist").mkdir()
    (tmp / "dist" / "index.html").write_text("<html></html>")
    stacks.BUILD, stacks.DIST = tmp, tmp / "dist"
    app = cdk.App()
    env = cdk.Environment(account="123456789012", region="us-east-2")
    core = stacks.CoreStack(app, "gonogo-core", env=env)
    api = stacks.ApiStack(app, "gonogo-api", core=core, deploy_neptune=True, deploy_ingest=True, env=env)
    ui = stacks.UiStack(app, "gonogo-ui", core=core, api=api, neptune=True, env=env)
    evaluation = stacks.EvalStack(app, "gonogo-eval", env=env)
    budget = stacks.BudgetStack(app, "gonogo-budget", limit_usd=10, email="alerts@example.invalid", env=env)
    return {
        s.stack_name: dict(assertions.Template.from_stack(s).to_json()["Resources"])
        for s in (core, api, ui, evaluation, budget)
    }


def functions(resources: dict[str, dict[str, Any]]) -> list[tuple[str, str, str, str]]:
    """(stack, handler, memory and timeout, where it runs) for each application function."""
    out = []
    for stack, res in resources.items():
        for r in res.values():
            p = r["Properties"] if r["Type"] == "AWS::Lambda::Function" else None
            if p and "Handler" in p and p["Handler"].startswith("service."):
                where = "in the VPC" if "VpcConfig" in p else "outside the VPC"
                out.append((stack, p["Handler"], f"{p['MemorySize']} MB, {p['Timeout']} s", where))
    return sorted(out)


def render() -> str:
    resources = synthesize()
    total = sum(len(r) for r in resources.values())
    lines = [
        "# AWS resources",
        "",
        f"The four stacks create {total} resources in us-east-2. This file is generated from the CloudFormation "
        "templates by `infra/inventory.py`, and a test fails when it falls out of date. Only Neptune bills while "
        "idle. `scripts/teardown.py` removes every stack except `gonogo-budget`.",
        "",
        "| Stack | Resources | Holds |",
        "|---|---:|---|",
    ]
    lines += [f"| `{s}` | {len(resources[s])} | {STACKS[s]} |" for s in STACKS]
    for stack in STACKS:
        counts = collections.Counter(r["Type"] for r in resources[stack].values())
        lines += [
            "",
            f"## {stack}",
            "",
            "| Resource type | Count | What it is for | Cost while idle |",
            "|---|---:|---|---|",
        ]
        for kind, n in sorted(counts.items()):
            what, cost = PURPOSE[kind]
            lines.append(f"| `{kind}` | {n} | {what} | {cost} |")
    lines += ["", "## The functions", "", "| Stack | Handler | Size | Runs |", "|---|---|---|---|"]
    lines += [f"| `{s}` | `{h}` | {size} | {where} |" for s, h, size, where in functions(resources)]
    lines += [
        "",
        "`service.engine_lambda.handler` is the FastAPI app of `api/index.py`, the same code the Vercel demo runs. "
        "`service.handler.handler` answers the guarded query and the decision on Neptune. "
        "`service.handler.load_handler` writes the graphs and is never reachable through the API.",
        "",
        "## What no resource here does",
        "",
        "- No NAT gateway, internet gateway, or interface endpoint exists, so nothing in the VPC reaches the internet.",
        "- No access key exists. Lambdas use their roles, and people sign in through Cognito.",
        "- CloudFront's default domain cannot enforce TLS 1.2. Only a custom domain with a certificate can.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    OUT.write_text(render())
    print(f"Wrote {OUT.relative_to(ROOT)}")
