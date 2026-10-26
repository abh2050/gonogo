# infra

AWS CDK in Python. Region us-east-2, profile awsnew. Three stacks:

| Stack | Holds |
|---|---|
| `gonogo-core` | KMS key, audit bucket (Object Lock), graph bucket, decisions table, event bus, Cognito with six role groups, the Verified Permissions policy store with the Cedar policies |
| `gonogo-api` | VPC with no NAT gateway, Neptune Serverless (behind `deployNeptune`), the engine, query, and loader Lambdas, API Gateway with a Cognito authorizer, request validation, and throttling |
| `gonogo-budget` | A $10 monthly budget that emails at 50, 80, and 100 percent. It outlives the other stacks. |

```bash
uv run python infra/package.py                      # build the arm64 Lambda bundle
cd infra && npx aws-cdk@2 deploy gonogo-core gonogo-api gonogo-budget -c deployNeptune=true
uv run python infra/evidence.py                     # run the checks against the deployment
uv run python scripts/teardown.py                   # remove everything but the budget
```

Set `GONOGO_BUDGET_EMAIL` in the environment to create the budget stack. The address is never committed.
`tests/infra/` synthesizes the stacks in memory and checks the templates without touching AWS.
