"""The audit trail: a decision record in DynamoDB, a tamper-evident copy in S3 with Object Lock, and an event.

Each function does nothing when its environment variable is absent, so the Vercel demo and the tests run the
same code with no AWS account.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3


def record_decision(decision: dict[str, Any]) -> dict[str, bool]:
    wrote = {"dynamodb": False, "s3": False}
    body = json.dumps(decision, sort_keys=True, default=str)
    if table := os.environ.get("DECISIONS_TABLE"):
        boto3.client("dynamodb").put_item(
            TableName=table,
            Item={
                "decision_id": {"S": decision["id"] + "#" + str(decision["events_applied"])},
                "user": {"S": str(decision["user"])},
                "role": {"S": str(decision["role"])},
                "verdict": {"S": decision["verdict"]},
                "signature": {"S": decision["signature"]},
                "recording_cutoff": {"S": decision["recording_cutoff"]},
                "record": {"S": body},
            },
        )
        wrote["dynamodb"] = True
    if bucket := os.environ.get("AUDIT_BUCKET"):
        boto3.client("s3").put_object(
            Bucket=bucket,
            Key=f"decisions/{decision['id']}-{decision['events_applied']}.json",
            Body=body.encode(),
            ContentType="application/json",
        )
        wrote["s3"] = True
    return wrote


def publish(detail_type: str, detail: dict[str, Any]) -> bool:
    if not (bus := os.environ.get("EVENT_BUS")):
        return False
    boto3.client("events").put_events(
        Entries=[{"EventBusName": bus, "Source": "gonogo", "DetailType": detail_type, "Detail": json.dumps(detail)}]
    )
    return True
