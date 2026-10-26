# AWS resources

The four stacks create 166 resources in us-east-2. This file is generated from the CloudFormation templates by `infra/inventory.py`, and a test fails when it falls out of date. Only Neptune bills while idle. `scripts/teardown.py` removes every stack except `gonogo-budget`.

| Stack | Resources | Holds |
|---|---:|---|
| `gonogo-core` | 41 | Identity, keys, storage, policies |
| `gonogo-api` | 99 | The network, the graph database, the functions, the API, and the ingestion workflow |
| `gonogo-ui` | 14 | Where the UI lives |
| `gonogo-eval` | 11 | The benchmark's vector search: a corpus bucket, a vector index, and a Knowledge Base |
| `gonogo-budget` | 1 | The cost alarm |

## gonogo-core

| Resource type | Count | What it is for | Cost while idle |
|---|---:|---|---|
| `AWS::Cognito::UserPool` | 1 | The sign-in directory. Admin-created users only, no self sign-up. | Free |
| `AWS::Cognito::UserPoolClient` | 1 | The browser app's client for the user name and password sign-in. | Free |
| `AWS::Cognito::UserPoolGroup` | 6 | One group per role. A token carries the group, and Cedar reads it. | Free |
| `AWS::DynamoDB::Table` | 1 | One summary row per decision, with point-in-time recovery. | Cents of storage |
| `AWS::Events::EventBus` | 1 | Receives fact approved and action events from the engine. | Free |
| `AWS::IAM::Role` | 1 | A Lambda's identity, with only the permissions its code uses. | Free |
| `AWS::KMS::Alias` | 1 | The friendly name of the project key. | Free |
| `AWS::KMS::Key` | 1 | Encrypts the buckets, the table, and Neptune. It rotates every year. | About $1 a month |
| `AWS::Lambda::Function` | 1 | Code that runs on demand. See the table of functions below. | Free while idle |
| `AWS::S3::Bucket` | 2 | Audit copies (Object Lock), graph files for loading, or the UI's files. | Cents of storage |
| `AWS::S3::BucketPolicy` | 2 | Forces HTTPS, and for the UI bucket admits only this CloudFront distribution. | Free |
| `AWS::VerifiedPermissions::Policy` | 21 | One Cedar policy, such as the rule that nobody approves what they proposed. | Free |
| `AWS::VerifiedPermissions::PolicyStore` | 1 | Holds the Cedar policies and their schema, in strict validation. | Free while idle |
| `Custom::S3AutoDeleteObjects` | 1 | Empties a bucket when the stack is deleted, so teardown leaves nothing. | Free |

## gonogo-api

| Resource type | Count | What it is for | Cost while idle |
|---|---:|---|---|
| `AWS::ApiGateway::Authorizer` | 1 | Verifies the Cognito token before any Lambda runs. | Free |
| `AWS::ApiGateway::Deployment` | 1 | A published version of the API. | Free |
| `AWS::ApiGateway::Method` | 5 | A route. Every one requires a Cognito token. | Free |
| `AWS::ApiGateway::Model` | 2 | The JSON shape that a request body must have. | Free |
| `AWS::ApiGateway::RequestValidator` | 2 | Rejects an oversize or malformed body at the gateway. | Free |
| `AWS::ApiGateway::Resource` | 7 | A path in the API. | Free |
| `AWS::ApiGateway::RestApi` | 1 | The front door of the API, regional, behind CloudFront. | Free while idle |
| `AWS::ApiGateway::Stage` | 1 | The `prod` stage, throttled at 20 requests a second. | Free while idle |
| `AWS::DynamoDB::Table` | 1 | One summary row per decision, with point-in-time recovery. | Cents of storage |
| `AWS::EC2::RouteTable` | 2 | Routes for a subnet. There is no route to the internet. | Free |
| `AWS::EC2::SecurityGroup` | 1 | Admits Neptune's port only from members of the same group. | Free |
| `AWS::EC2::SecurityGroupIngress` | 1 | The one inbound rule: Lambda to Neptune on port 8182. | Free |
| `AWS::EC2::Subnet` | 2 | An isolated subnet in one Availability Zone. | Free |
| `AWS::EC2::SubnetRouteTableAssociation` | 2 | Attaches a route table to a subnet. | Free |
| `AWS::EC2::VPC` | 1 | The private network around Neptune and two Lambdas. No internet gateway, no NAT. | Free |
| `AWS::EC2::VPCEndpoint` | 1 | A gateway endpoint so the in-VPC Lambdas reach S3 without the internet. | Free |
| `AWS::IAM::Policy` | 11 | The permissions attached to a role. | Free |
| `AWS::IAM::Role` | 14 | A Lambda's identity, with only the permissions its code uses. | Free |
| `AWS::Lambda::Function` | 13 | Code that runs on demand. See the table of functions below. | Free while idle |
| `AWS::Lambda::Permission` | 11 | Lets API Gateway call a Lambda. | Free |
| `AWS::Logs::LogGroup` | 11 | A Lambda's log, kept three days. | Cents |
| `AWS::Neptune::DBCluster` | 1 | The graph database: serverless, IAM-only, encrypted with the project key. | Yes: bills while it exists |
| `AWS::Neptune::DBInstance` | 1 | The one serverless instance, scaling between 1 and 4 capacity units. | Yes: about $0.16 per unit-hour |
| `AWS::Neptune::DBSubnetGroup` | 1 | Tells Neptune which subnets it may use. | Free |
| `AWS::S3::Bucket` | 1 | Audit copies (Object Lock), graph files for loading, or the UI's files. | Cents of storage |
| `AWS::S3::BucketPolicy` | 1 | Forces HTTPS, and for the UI bucket admits only this CloudFront distribution. | Free |
| `AWS::StepFunctions::StateMachine` | 1 | The ingestion workflow: read a PDF, extract a grant, check it, wait for a steward, write it, rerun. | Free while idle |
| `Custom::S3AutoDeleteObjects` | 1 | Empties a bucket when the stack is deleted, so teardown leaves nothing. | Free |
| `Custom::S3BucketNotifications` | 1 | Lets the ingestion inbox start the workflow when a PDF arrives. | Free |

## gonogo-ui

| Resource type | Count | What it is for | Cost while idle |
|---|---:|---|---|
| `AWS::CloudFront::Distribution` | 1 | The one address for the UI and the API, over HTTPS. | Free while idle |
| `AWS::CloudFront::OriginAccessControl` | 1 | Signs CloudFront's requests to the private bucket. | Free |
| `AWS::CloudFront::ResponseHeadersPolicy` | 2 | Adds security headers, and a strict content policy to the app. | Free |
| `AWS::IAM::Policy` | 1 | The permissions attached to a role. | Free |
| `AWS::IAM::Role` | 2 | A Lambda's identity, with only the permissions its code uses. | Free |
| `AWS::Lambda::Function` | 2 | Code that runs on demand. See the table of functions below. | Free while idle |
| `AWS::Lambda::LayerVersion` | 1 | The AWS CLI layer that the UI deploy step uses to copy files. | Free |
| `AWS::S3::Bucket` | 1 | Audit copies (Object Lock), graph files for loading, or the UI's files. | Cents of storage |
| `AWS::S3::BucketPolicy` | 1 | Forces HTTPS, and for the UI bucket admits only this CloudFront distribution. | Free |
| `Custom::CDKBucketDeployment` | 1 | Copies the built UI and its config.json into the site bucket on deploy. | Free |
| `Custom::S3AutoDeleteObjects` | 1 | Empties a bucket when the stack is deleted, so teardown leaves nothing. | Free |

## gonogo-eval

| Resource type | Count | What it is for | Cost while idle |
|---|---:|---|---|
| `AWS::Bedrock::DataSource` | 1 | Points the Knowledge Base at the corpus bucket and chunks its documents. | Free |
| `AWS::Bedrock::KnowledgeBase` | 1 | Embeds the corpus with Titan and answers search queries for answerer A. | Free while idle |
| `AWS::IAM::Policy` | 1 | The permissions attached to a role. | Free |
| `AWS::IAM::Role` | 2 | A Lambda's identity, with only the permissions its code uses. | Free |
| `AWS::Lambda::Function` | 1 | Code that runs on demand. See the table of functions below. | Free while idle |
| `AWS::S3::Bucket` | 1 | Audit copies (Object Lock), graph files for loading, or the UI's files. | Cents of storage |
| `AWS::S3::BucketPolicy` | 1 | Forces HTTPS, and for the UI bucket admits only this CloudFront distribution. | Free |
| `AWS::S3Vectors::Index` | 1 | The benchmark's search index over the document corpus. | Cents of storage |
| `AWS::S3Vectors::VectorBucket` | 1 | Holds the benchmark's vector index. | Cents of storage |
| `Custom::S3AutoDeleteObjects` | 1 | Empties a bucket when the stack is deleted, so teardown leaves nothing. | Free |

## gonogo-budget

| Resource type | Count | What it is for | Cost while idle |
|---|---:|---|---|
| `AWS::Budgets::Budget` | 1 | A $10 monthly budget on GoNoGo's services that emails at 50, 80, and 100 percent. | Free; survives teardown |

## The functions

| Stack | Handler | Size | Runs |
|---|---|---|---|
| `gonogo-api` | `service.engine_lambda.handler` | 1536 MB, 29 s | outside the VPC |
| `gonogo-api` | `service.handler.handler` | 1024 MB, 28 s | in the VPC |
| `gonogo-api` | `service.handler.load_handler` | 2048 MB, 600 s | in the VPC |
| `gonogo-api` | `service.ingest.apply_handler` | 1536 MB, 120 s | in the VPC |
| `gonogo-api` | `service.ingest.await_handler` | 1536 MB, 30 s | outside the VPC |
| `gonogo-api` | `service.ingest.check_handler` | 1536 MB, 120 s | outside the VPC |
| `gonogo-api` | `service.ingest.decide_handler` | 1536 MB, 30 s | outside the VPC |
| `gonogo-api` | `service.ingest.extract_handler` | 1536 MB, 60 s | outside the VPC |
| `gonogo-api` | `service.ingest.ocr_handler` | 1536 MB, 240 s | outside the VPC |
| `gonogo-api` | `service.ingest.rerun_handler` | 1536 MB, 120 s | in the VPC |
| `gonogo-api` | `service.ingest.start_handler` | 1536 MB, 30 s | outside the VPC |

`service.engine_lambda.handler` is the FastAPI app of `api/index.py`, the same code the Vercel demo runs. `service.handler.handler` answers the guarded query and the decision on Neptune. `service.handler.load_handler` writes the graphs and is never reachable through the API.

## What no resource here does

- No NAT gateway, internet gateway, or interface endpoint exists, so nothing in the VPC reaches the internet.
- No access key exists. Lambdas use their roles, and people sign in through Cognito.
- CloudFront's default domain cannot enforce TLS 1.2. Only a custom domain with a certificate can.
