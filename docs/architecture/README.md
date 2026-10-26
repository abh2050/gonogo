# AWS diagrams

Seven views of the AWS deployment, drawn in draw.io with the official AWS icon set. They are one file,
[gonogo-aws.drawio](gonogo-aws.drawio), with one page per view: open it in draw.io to edit, or change
`scripts/drawio_aws.py` and run `uv run python scripts/drawio_aws.py` to rebuild the file and every PNG.
The services are the ones `infra/stacks.py` deploys, and the access grid on page 5 is read from the Cedar policies.

## 1. The whole system

Zones group the services by job, and the numbers follow one clearance question from the browser to a stored,
signed decision.

![GoNoGo on AWS: edge, identity and policy, decide, record, the graph in its VPC, ingestion, the benchmark, and the cost guard](gonogo-aws-1-overview.png)

## 2. A clearance question, step by step

The same request as a sequence: sign-in, the token check, Cedar, the fixed SPARQL templates, and the stored decision.

![A sequence diagram from sign-in to the stored decision, fifteen steps](gonogo-aws-2-request-path.png)

## 3. Ingesting a license agreement

The Step Functions state machine: Textract, extraction, SHACL, a wait for a steward with a task token, the write to
Neptune, and the rerun of the requests the agreement affects.

![The ingestion state machine with its approval loop](gonogo-aws-3-ingestion.png)

## 4. Security and network boundaries

What can reach what: the VPC with no route to the internet, who may read or write Neptune, and what the build and
the live checks verify.

![The account, region, VPC, security group, and the functions that may touch Neptune](gonogo-aws-4-security.png)

## 5. Four named graphs, six roles

Which role may query which graph, read from the Cedar policies.

![A grid of six roles against the release, approved, candidate, and royalty graphs](gonogo-aws-5-data-access.png)

## 6. The benchmark

How the four answerers reach their verdicts from the same questions and facts.

![Answerers A, B, C, and C+ side by side, feeding one scorer](gonogo-aws-6-benchmark.png)

## 7. Stacks and cost

The five CDK stacks, what each holds, and what each costs while idle.

![The five stacks and their idle cost](gonogo-aws-7-stacks.png)
