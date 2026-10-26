"""CDK entry point.

    uv run python infra/package.py                          build the Lambda bundle
    (cd ui && npm run build)                                build the UI that gonogo-ui serves
    cdk deploy --all -c deployNeptune=true                  deploy with the graph
    cdk deploy gonogo-api -c deployNeptune=true -c deployIngest=true    add the ingestion workflow
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

from stacks import ApiStack, BudgetStack, CoreStack, EvalStack, UiStack  # noqa: E402

from gonogo.aws import check_region, load_settings  # noqa: E402

settings = load_settings()
region = check_region(settings.region)
app = cdk.App()
env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=region)
deploy_neptune = str(app.node.try_get_context("deployNeptune")).lower() == "true"
deploy_ingest = str(app.node.try_get_context("deployIngest")).lower() == "true"

core = CoreStack(app, "gonogo-core", env=env)
api = ApiStack(app, "gonogo-api", core=core, deploy_neptune=deploy_neptune, deploy_ingest=deploy_ingest, env=env)
UiStack(app, "gonogo-ui", core=core, api=api, neptune=deploy_neptune, env=env)
EvalStack(app, "gonogo-eval", env=env)

email = os.environ.get("GONOGO_BUDGET_EMAIL")
if email:
    BudgetStack(app, "gonogo-budget", limit_usd=settings.budget_usd, email=email, env=env)

app.synth()
