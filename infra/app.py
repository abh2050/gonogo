"""CDK entry point. Gate 3 fills in the stacks.

Neptune and Fargate stay behind the deployNeptune and deployFargate context flags, which
default to false, so a plain `cdk deploy` creates nothing that bills while idle.
The account and region come from config/aws.yaml through gonogo.aws, never from CDK defaults.
"""

from __future__ import annotations

import aws_cdk as cdk

from gonogo.aws import load_settings

settings = load_settings()
app = cdk.App()
env = cdk.Environment(region=settings.region)
deploy_neptune = bool(app.node.try_get_context("deployNeptune"))
deploy_fargate = bool(app.node.try_get_context("deployFargate"))

# Gate 3: network, data, graph (if deploy_neptune), agent (if deploy_fargate), api, and budget stacks.

app.synth()
