"""CDK entry point.

    uv run python infra/package.py                          build the Lambda bundle
    cdk deploy gonogo-core gonogo-api -c deployNeptune=true deploy with the graph
    uv run python scripts/teardown.py                       remove everything but the budget

The region comes from config/aws.yaml through gonogo.aws and must be us-east-2. The budget email comes from the
environment (GONOGO_BUDGET_EMAIL) and is never committed. Neptune stays behind deployNeptune, which defaults to false.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import aws_cdk as cdk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stacks import ApiStack, BudgetStack, CoreStack  # noqa: E402

from gonogo.aws import check_region, load_settings  # noqa: E402

settings = load_settings()
region = check_region(settings.region)
app = cdk.App()
env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=region)
deploy_neptune = str(app.node.try_get_context("deployNeptune")).lower() == "true"

core = CoreStack(app, "gonogo-core", env=env)
ApiStack(app, "gonogo-api", core=core, deploy_neptune=deploy_neptune, env=env)

email = os.environ.get("GONOGO_BUDGET_EMAIL")
if email:
    BudgetStack(app, "gonogo-budget", limit_usd=settings.budget_usd, email=email, env=env)

app.synth()
