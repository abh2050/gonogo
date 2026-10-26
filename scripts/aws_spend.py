"""Measured AWS spend for the GoNoGo services, from Cost Explorer.

    uv run python scripts/aws_spend.py 2026-10-25 2026-10-27     start (inclusive), end (exclusive)

Cost Explorer lags by up to a day, so run it the day after a session. It reports the services that GoNoGo uses
and that no other project in the shared account does, which is also what the budget in infra/stacks.py counts.
Bedrock is shown separately because another project in the account calls it too: read the day's total and subtract
the estimate in docs/status.md.
"""

from __future__ import annotations

import json
import sys

GONOGO = {
    "Amazon Neptune",
    "Amazon Verified Permissions",
    "Amazon Cognito",
    "AWS Lambda",
    "Amazon DynamoDB",
    "AWS Key Management Service",
    "Amazon API Gateway",
    "Amazon EventBridge",
    "Amazon Virtual Private Cloud",
}


def main() -> None:
    start, end = sys.argv[1], sys.argv[2]
    # Cost Explorer is a global billing service that is served from one endpoint. The call reads billing data and
    # creates nothing. gonogo.aws allows only us-east-2, so this script is the one place that names the other region.
    import boto3

    ce = boto3.Session(profile_name="awsnew").client("ce", region_name="us-east-1")
    out = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    rows: dict[str, dict[str, float]] = {}
    for day in out["ResultsByTime"]:
        for g in day["Groups"]:
            amount = float(g["Metrics"]["UnblendedCost"]["Amount"])
            if abs(amount) > 0:
                rows.setdefault(day["TimePeriod"]["Start"], {})[g["Keys"][0]] = round(amount, 4)
    gonogo = sum(v for d in rows.values() for k, v in d.items() if k in GONOGO)
    bedrock = sum(d.get("Amazon Bedrock", 0.0) for d in rows.values())
    print(
        json.dumps(
            {"by_day": rows, "gonogo_services_usd": round(gonogo, 4), "bedrock_usd_all_projects": round(bedrock, 4)},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
