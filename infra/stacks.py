"""The GoNoGo AWS stacks. Region us-east-2 only, deployed from profile awsnew.

    gonogo-core     keys, audit and graph buckets, the decisions table, the event bus, Cognito with six role
                    groups, and the Verified Permissions policy store that holds the Cedar policies
    gonogo-api      the VPC, Neptune Serverless (when deployNeptune is true), the three Lambdas, and API Gateway
                    with a Cognito authorizer, request validation, and throttling
    gonogo-eval     the benchmark's vector search: a corpus bucket, an S3 Vectors index, and a Bedrock Knowledge
                    Base with Titan embeddings. It stands alone and is torn down with the others.
    gonogo-budget   a monthly cost budget that emails at 50, 80, and 100 percent. It outlives the other stacks.

Nothing here has a NAT gateway, an interface endpoint, or a long-lived access key. Neptune is the one resource
that bills while idle, so it sits behind the deployNeptune flag, and scripts/teardown.py removes it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
)
from aws_cdk import (
    aws_apigateway as apigw,
)
from aws_cdk import (
    aws_bedrock as bedrock,
)
from aws_cdk import (
    aws_budgets as budgets,
)
from aws_cdk import (
    aws_cloudfront as cloudfront,
)
from aws_cdk import (
    aws_cloudfront_origins as origins,
)
from aws_cdk import (
    aws_cognito as cognito,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_ec2 as ec2,
)
from aws_cdk import (
    aws_events as events,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_kms as kms,
)
from aws_cdk import (
    aws_lambda as _lambda,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import (
    aws_neptune as neptune,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_s3_deployment as s3deploy,
)
from aws_cdk import (
    aws_s3_notifications as s3n,
)
from aws_cdk import (
    aws_s3vectors as s3vectors,
)
from aws_cdk import (
    aws_stepfunctions as sfn,
)
from aws_cdk import (
    aws_stepfunctions_tasks as tasks,
)
from aws_cdk import (
    aws_verifiedpermissions as avp,
)
from constructs import Construct

from authz import avp as avp_text
from authz.cedar import ROLES

BUILD = Path(__file__).resolve().parent / "build" / "lambda"
NEPTUNE_ENGINE = "1.4.8.1"


def tag(scope: Construct) -> None:
    Tags.of(scope).add("project", "gonogo")


class CoreStack(Stack):
    def __init__(self, scope: Construct, id: str, **kw: Any) -> None:
        super().__init__(scope, id, **kw)
        tag(self)
        self.key = kms.Key(
            self,
            "Key",
            alias="alias/gonogo",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.DESTROY,
            pending_window=Duration.days(7),
        )
        # Object Lock in governance mode keeps each audit copy for a day. teardown.py bypasses it to empty the bucket.
        self.audit = s3.Bucket(
            self,
            "Audit",
            versioned=True,
            object_lock_enabled=True,
            object_lock_default_retention=s3.ObjectLockRetention.governance(Duration.days(1)),
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.key,
            enforce_ssl=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.graphs = s3.Bucket(
            self,
            "Graphs",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.key,
            enforce_ssl=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        self.decisions = dynamodb.Table(
            self,
            "Decisions",
            partition_key=dynamodb.Attribute(name="decision_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            encryption=dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=self.key,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.bus = events.EventBus(self, "Bus", event_bus_name="gonogo")

        self.pool = cognito.UserPool(
            self,
            "Pool",
            user_pool_name="gonogo",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(username=True),
            password_policy=cognito.PasswordPolicy(min_length=12, require_symbols=True, require_digits=True),
            # The evidence run signs in with scripted test users. A real deployment sets MFA to REQUIRED.
            mfa=cognito.Mfa.OFF,
            account_recovery=cognito.AccountRecovery.NONE,
            removal_policy=RemovalPolicy.DESTROY,
        )
        for role in ROLES:
            cognito.CfnUserPoolGroup(self, f"Group-{role}", user_pool_id=self.pool.user_pool_id, group_name=role)
        self.client = self.pool.add_client(
            "Client",
            # The browser signs in with a user name and password. The evidence script uses the admin flow.
            auth_flows=cognito.AuthFlow(admin_user_password=True, user_password=True),
            generate_secret=False,
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
        )

        store = avp.CfnPolicyStore(
            self,
            "Policies",
            validation_settings=avp.CfnPolicyStore.ValidationSettingsProperty(mode="STRICT"),
            schema=avp.CfnPolicyStore.SchemaDefinitionProperty(cedar_json=avp_text.schema_json()),
            description="GoNoGo Cedar policies (authz/policies/gonogo.cedar)",
        )
        self.policy_store = store
        for policy_id, statement in avp_text.statements():
            policy = avp.CfnPolicy(
                self,
                f"Policy-{policy_id}",
                policy_store_id=store.attr_policy_store_id,
                definition=avp.CfnPolicy.PolicyDefinitionProperty(
                    static=avp.CfnPolicy.StaticPolicyDefinitionProperty(statement=statement, description=policy_id)
                ),
            )
            policy.add_dependency(store)

        for name, value in {
            "UserPoolId": self.pool.user_pool_id,
            "UserPoolClientId": self.client.user_pool_client_id,
            "PolicyStoreId": store.attr_policy_store_id,
            "AuditBucket": self.audit.bucket_name,
            "GraphBucket": self.graphs.bucket_name,
            "DecisionsTable": self.decisions.table_name,
            "EventBus": self.bus.event_bus_name,
        }.items():
            cdk.CfnOutput(self, name, value=value)


class ApiStack(Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        core: CoreStack,
        deploy_neptune: bool,
        deploy_ingest: bool = False,
        **kw: Any,
    ) -> None:
        super().__init__(scope, id, **kw)
        tag(self)
        common = dict(
            runtime=_lambda.Runtime.PYTHON_3_12,
            architecture=_lambda.Architecture.ARM_64,
            code=_lambda.Code.from_asset(str(BUILD)),
        )

        def log_group(name: str) -> logs.LogGroup:
            return logs.LogGroup(
                self, f"Logs{name}", retention=logs.RetentionDays.THREE_DAYS, removal_policy=RemovalPolicy.DESTROY
            )

        # The engine: the FastAPI app of api/index.py. It reads the snapshot bundled with it, and it is not in the
        # VPC, so it can write the audit trail with ordinary service endpoints and no NAT gateway.
        self.engine = _lambda.Function(
            self,
            "Engine",
            handler="service.engine_lambda.handler",
            log_group=log_group("Engine"),
            memory_size=1536,
            timeout=Duration.seconds(29),
            environment={
                "DECISIONS_TABLE": core.decisions.table_name,
                "AUDIT_BUCKET": core.audit.bucket_name,
                "EVENT_BUS": core.bus.event_bus_name,
            },
            **common,  # type: ignore[arg-type]
        )
        core.decisions.grant_write_data(self.engine)
        core.audit.grant_put(self.engine)
        core.bus.grant_put_events_to(self.engine)
        core.key.grant_encrypt_decrypt(self.engine)

        api = apigw.RestApi(
            self,
            "Api",
            rest_api_name="gonogo",
            endpoint_types=[
                apigw.EndpointType.REGIONAL
            ],  # CloudFront fronts it, so it needs no edge network of its own
            deploy_options=apigw.StageOptions(
                stage_name="prod", throttling_rate_limit=20, throttling_burst_limit=40, metrics_enabled=True
            ),
            cloud_watch_role=False,  # the account-wide CloudWatch role is not this project's to change
        )
        self.rest_api = api
        authorizer = apigw.CognitoUserPoolsAuthorizer(self, "Auth", cognito_user_pools=[core.pool])
        secured = dict(authorizer=authorizer, authorization_type=apigw.AuthorizationType.COGNITO)

        engine_integration = apigw.LambdaIntegration(self.engine)
        proxy = api.root.add_resource("api").add_resource("{proxy+}")
        proxy.add_method("ANY", engine_integration, **secured)  # type: ignore[arg-type]

        self.neptune_endpoint = ""
        if deploy_neptune:
            self._graph(core, api, common, secured, deploy_ingest)

        cdk.CfnOutput(self, "ApiUrl", value=api.url)
        cdk.CfnOutput(self, "EngineFunction", value=self.engine.function_name)

    def _graph(
        self, core: CoreStack, api: apigw.RestApi, common: dict[str, Any], secured: dict[str, Any], deploy_ingest: bool
    ) -> None:
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="private", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24)
            ],
        )
        vpc.add_gateway_endpoint("S3", service=ec2.GatewayVpcEndpointAwsService.S3)
        # The subnets have no internet route, so open egress reaches only Neptune and the S3 gateway endpoint.
        # Ingress allows Neptune's port from members of this group and from nothing else.
        sg = ec2.SecurityGroup(self, "Sg", vpc=vpc, description="GoNoGo graph tier")
        sg.add_ingress_rule(sg, ec2.Port.tcp(8182), "Lambda to Neptune, inside this group only")

        subnets = neptune.CfnDBSubnetGroup(
            self,
            "Subnets",
            db_subnet_group_description="GoNoGo graph",
            subnet_ids=vpc.select_subnets(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED).subnet_ids,
        )
        cluster = neptune.CfnDBCluster(
            self,
            "Cluster",
            engine_version=NEPTUNE_ENGINE,
            db_subnet_group_name=subnets.ref,
            vpc_security_group_ids=[sg.security_group_id],
            iam_auth_enabled=True,
            storage_encrypted=True,
            kms_key_id=core.key.key_arn,
            backup_retention_period=1,
            deletion_protection=False,
            serverless_scaling_configuration=neptune.CfnDBCluster.ServerlessScalingConfigurationProperty(
                min_capacity=1, max_capacity=4
            ),
        )
        cluster.add_dependency(subnets)
        cluster.apply_removal_policy(RemovalPolicy.DESTROY)  # no final snapshot is left behind
        instance = neptune.CfnDBInstance(
            self, "Instance", db_instance_class="db.serverless", db_cluster_identifier=cluster.ref
        )
        instance.add_dependency(cluster)
        instance.apply_removal_policy(RemovalPolicy.DESTROY)
        self.neptune_endpoint = cluster.attr_endpoint

        env = {"NEPTUNE_ENDPOINT": cluster.attr_endpoint, "NEPTUNE_PORT": "8182"}
        vpc_args = dict(
            vpc=vpc, vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED), security_groups=[sg]
        )
        arn = f"arn:aws:neptune-db:{self.region}:{self.account}:{cluster.attr_cluster_resource_id}/*"

        def log_group(name: str) -> logs.LogGroup:
            return logs.LogGroup(
                self, f"Logs{name}", retention=logs.RetentionDays.THREE_DAYS, removal_policy=RemovalPolicy.DESTROY
            )

        def neptune_access(fn: _lambda.Function, *actions: str) -> None:
            fn.add_to_role_policy(iam.PolicyStatement(actions=list(actions), resources=[arn]))

        self.query = _lambda.Function(
            self,
            "Query",
            handler="service.handler.handler",
            log_group=log_group("Query"),
            memory_size=1024,
            timeout=Duration.seconds(28),
            environment=env,
            **vpc_args,  # type: ignore[arg-type]
            **common,
        )
        neptune_access(self.query, "neptune-db:connect", "neptune-db:ReadDataViaQuery")  # read only
        self.loader = _lambda.Function(
            self,
            "Loader",
            handler="service.handler.load_handler",
            log_group=log_group("Loader"),
            memory_size=2048,
            timeout=Duration.minutes(10),
            environment=env,
            **vpc_args,  # type: ignore[arg-type]
            **common,
        )
        neptune_access(
            self.loader,
            "neptune-db:connect",
            "neptune-db:ReadDataViaQuery",
            "neptune-db:WriteDataViaQuery",
            "neptune-db:DeleteDataViaQuery",
        )
        core.graphs.grant_read(self.loader)
        core.key.grant_decrypt(self.loader)

        query_integration = apigw.LambdaIntegration(self.query)
        api.root.add_resource("health").add_method("GET", query_integration, **secured)
        for route, limit in (("query", 8000), ("decide", 4000)):
            model = api.add_model(
                f"{route.title()}Body",
                content_type="application/json",
                schema=apigw.JsonSchema(
                    schema=apigw.JsonSchemaVersion.DRAFT4,
                    type=apigw.JsonSchemaType.OBJECT,
                    additional_properties=False,
                    properties={
                        ("query" if route == "query" else "request"): apigw.JsonSchema(
                            type=apigw.JsonSchemaType.STRING if route == "query" else apigw.JsonSchemaType.OBJECT,
                            max_length=limit if route == "query" else None,
                        )
                    },
                    required=["query" if route == "query" else "request"],
                ),
            )
            validator = api.add_request_validator(f"Validate-{route}", validate_request_body=True)
            api.root.add_resource(route).add_method(
                "POST",
                query_integration,
                request_validator=validator,
                request_models={"application/json": model},
                **secured,
            )
        cdk.CfnOutput(self, "NeptuneEndpoint", value=cluster.attr_endpoint)
        cdk.CfnOutput(self, "QueryFunction", value=self.query.function_name)
        cdk.CfnOutput(self, "LoaderFunction", value=self.loader.function_name)
        if deploy_ingest:
            self._ingest(core, api, secured, env, vpc_args, neptune_access)

    def _ingest(
        self,
        core: CoreStack,
        api: apigw.RestApi,
        secured: dict[str, Any],
        env: dict[str, str],
        vpc_args: dict[str, Any],
        neptune_access: Any,
    ) -> None:
        """The ingestion workflow (service/ingest.py). A PDF in the inbox starts a state machine that reads it with
        Textract, extracts a grant, checks it with SHACL, and waits for a steward's decision with a task token. Once
        approved, the grant is written to Neptune and the booked requests on its patents run again. It lives in this
        stack because it adds a route to this API and runs two functions in this VPC."""
        inbox = s3.Bucket(
            self,
            "Inbox",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=core.key,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        pending = dynamodb.Table(
            self,
            "Pending",
            partition_key=dynamodb.Attribute(name="id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            encryption=dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=core.key,
        )
        shared = dict(
            runtime=_lambda.Runtime.PYTHON_3_12,
            architecture=_lambda.Architecture.ARM_64,
            code=_lambda.Code.from_asset(str(BUILD)),
            memory_size=1536,
            environment={**env, "PENDING_TABLE": pending.table_name},
        )

        def fn(name: str, handler: str, timeout: int, **extra: Any) -> _lambda.Function:
            return _lambda.Function(
                self,
                name,
                handler=f"service.ingest.{handler}",
                timeout=Duration.seconds(timeout),
                log_group=logs.LogGroup(
                    self, f"Logs{name}", retention=logs.RetentionDays.THREE_DAYS, removal_policy=RemovalPolicy.DESTROY
                ),
                **{**shared, **extra},  # type: ignore[arg-type]
            )

        ocr = fn("Ocr", "ocr_handler", 240)
        inbox.grant_read(ocr)
        core.key.grant_decrypt(ocr)
        ocr.add_to_role_policy(
            iam.PolicyStatement(
                actions=["textract:StartDocumentTextDetection", "textract:GetDocumentTextDetection"], resources=["*"]
            )
        )
        extract = fn("Extract", "extract_handler", 60)
        check = fn("Check", "check_handler", 120)
        wait = fn("Wait", "await_handler", 30)
        pending.grant_write_data(wait)
        core.key.grant_encrypt_decrypt(wait)
        # The two steps that touch Neptune run in its VPC, with the same role limits as the other graph Lambdas.
        apply = fn("Apply", "apply_handler", 120, **vpc_args)
        rerun = fn("Rerun", "rerun_handler", 120, **vpc_args)
        neptune_access(
            apply,
            "neptune-db:connect",
            "neptune-db:ReadDataViaQuery",
            "neptune-db:WriteDataViaQuery",
            "neptune-db:DeleteDataViaQuery",
        )
        neptune_access(rerun, "neptune-db:connect", "neptune-db:ReadDataViaQuery")

        def step(name: str, f: _lambda.Function, **kw: Any) -> tasks.LambdaInvoke:
            return tasks.LambdaInvoke(self, name, lambda_function=f, payload_response_only=True, **kw)

        failed = sfn.Fail(self, "NotApproved", error="NotApproved", cause="A steward rejected the proposal.")
        invalid = sfn.Fail(self, "Invalid", error="Invalid", cause="The proposal did not pass the shape checks.")
        approval = tasks.LambdaInvoke(
            self,
            "AwaitApproval",
            lambda_function=wait,
            integration_pattern=sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
            payload=sfn.TaskInput.from_object(
                {
                    "execution": sfn.JsonPath.string_at("$$.Execution.Name"),
                    "token": sfn.JsonPath.task_token,
                    "candidate": sfn.JsonPath.string_at("$.candidate"),
                    "record": sfn.JsonPath.object_at("$.record"),
                }
            ),
            result_path="$.decision",
            heartbeat_timeout=None,
            task_timeout=sfn.Timeout.duration(Duration.days(7)),
        )
        approval.add_catch(failed, errors=["Rejected"], result_path="$.rejection")
        definition = (
            step("ReadWithTextract", ocr)
            .next(step("ExtractGrant", extract, result_selector={"value.$": "$"}, output_path="$.value"))
            .next(step("CheckShapes", check))
            .next(
                sfn.Choice(self, "Conforms")
                .when(sfn.Condition.boolean_equals("$.conforms", False), invalid)
                .otherwise(approval.next(step("WriteToGraph", apply)).next(step("RerunRequests", rerun)))
            )
        )
        machine = sfn.StateMachine(
            self,
            "Machine",
            state_machine_name="gonogo-ingest",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.days(8),
            tracing_enabled=True,
        )
        starter = fn("Start", "start_handler", 30, environment={"MACHINE": machine.state_machine_arn})
        machine.grant_start_execution(starter)
        inbox.add_event_notification(
            s3.EventType.OBJECT_CREATED, s3n.LambdaDestination(starter), s3.NotificationKeyFilter(suffix=".pdf")
        )
        decide = fn("Decide", "decide_handler", 30)
        pending.grant_read_write_data(decide)
        core.key.grant_encrypt_decrypt(decide)
        decide.add_to_role_policy(
            iam.PolicyStatement(actions=["states:SendTaskSuccess", "states:SendTaskFailure"], resources=["*"])
        )
        api.root.add_resource("ingest").add_resource("decide").add_method(
            "POST", apigw.LambdaIntegration(decide), **secured
        )
        cdk.CfnOutput(self, "InboxBucket", value=inbox.bucket_name)
        cdk.CfnOutput(self, "MachineArn", value=machine.state_machine_arn)


DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"
API_PATHS = ["/api/*", "/query", "/decide", "/health"]


class UiStack(Stack):
    """Where the UI lives on AWS: a private bucket behind CloudFront, with the API on the same origin.

    The browser loads the app from CloudFront and calls /api/*, /query, /decide, and /health on the same host, so the
    API needs no CORS. CloudFront forwards the Authorization header, and API Gateway checks the Cognito token.
    """

    def __init__(self, scope: Construct, id: str, *, core: CoreStack, api: ApiStack, neptune: bool, **kw: Any) -> None:
        super().__init__(scope, id, **kw)
        tag(self)
        bucket = s3.Bucket(
            self,
            "Site",
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        cognito_host = f"https://cognito-idp.{self.region}.amazonaws.com"
        secure = cloudfront.ResponseHeadersPolicy(
            self,
            "Headers",
            security_headers_behavior=cloudfront.ResponseSecurityHeadersBehavior(
                content_security_policy=cloudfront.ResponseHeadersContentSecurityPolicy(
                    override=True,
                    content_security_policy=(
                        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                        f"img-src 'self' data:; font-src 'self' data:; connect-src 'self' {cognito_host}; "
                        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
                    ),
                ),
                strict_transport_security=cloudfront.ResponseHeadersStrictTransportSecurity(
                    access_control_max_age=Duration.days(365), include_subdomains=True, override=True
                ),
                content_type_options=cloudfront.ResponseHeadersContentTypeOptions(override=True),
                frame_options=cloudfront.ResponseHeadersFrameOptions(
                    frame_option=cloudfront.HeadersFrameOption.DENY, override=True
                ),
                referrer_policy=cloudfront.ResponseHeadersReferrerPolicy(
                    referrer_policy=cloudfront.HeadersReferrerPolicy.SAME_ORIGIN, override=True
                ),
            ),
        )
        # The generated reference documentation carries inline scripts, so its path gets everything but the CSP.
        docs = cloudfront.ResponseHeadersPolicy(
            self,
            "DocsHeaders",
            security_headers_behavior=cloudfront.ResponseSecurityHeadersBehavior(
                content_type_options=cloudfront.ResponseHeadersContentTypeOptions(override=True),
                frame_options=cloudfront.ResponseHeadersFrameOptions(
                    frame_option=cloudfront.HeadersFrameOption.DENY, override=True
                ),
            ),
        )
        site = origins.S3BucketOrigin.with_origin_access_control(bucket)
        api_origin = origins.RestApiOrigin(api.rest_api)
        passthrough = cloudfront.BehaviorOptions(
            origin=api_origin,
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
            allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
            cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
            origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        )
        self.distribution = cloudfront.Distribution(
            self,
            "Cdn",
            comment="GoNoGo UI and API",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=site,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=secure,
            ),
            additional_behaviors={
                **{path: passthrough for path in API_PATHS},
                "/ontology/*": cloudfront.BehaviorOptions(
                    origin=site,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    response_headers_policy=docs,
                ),
            },
        )
        config = {
            "mode": "aws",
            "region": self.region,
            "userPoolClientId": core.client.user_pool_client_id,
            "neptune": neptune,
        }
        s3deploy.BucketDeployment(
            self,
            "Deploy",
            sources=[s3deploy.Source.asset(str(DIST)), s3deploy.Source.json_data("config.json", config)],
            destination_bucket=bucket,
            distribution=self.distribution,
            distribution_paths=["/*"],
            prune=True,
        )
        cdk.CfnOutput(self, "UiUrl", value=f"https://{self.distribution.distribution_domain_name}")
        cdk.CfnOutput(self, "DistributionId", value=self.distribution.distribution_id)


# The services that GoNoGo uses and that nothing else in the shared account does. The account is a linked account of
# an organization, so cost allocation tags are not available to it and a tag filter cannot work. Bedrock is left out
# because another project in the account calls it too. The account's own $20 budget stays as the global backstop.
BUDGET_SERVICES = [
    "Amazon Neptune",
    "Amazon Verified Permissions",
    "Amazon Cognito",
    "AWS Lambda",
    "Amazon DynamoDB",
    "AWS Key Management Service",
    "Amazon API Gateway",
    "Amazon EventBridge",
]


class BudgetStack(Stack):
    def __init__(self, scope: Construct, id: str, *, limit_usd: int, email: str, **kw: Any) -> None:
        super().__init__(scope, id, **kw)
        tag(self)

        def alert(threshold: int, kind: str) -> budgets.CfnBudget.NotificationWithSubscribersProperty:
            return budgets.CfnBudget.NotificationWithSubscribersProperty(
                notification=budgets.CfnBudget.NotificationProperty(
                    notification_type=kind,
                    comparison_operator="GREATER_THAN",
                    threshold=threshold,
                    threshold_type="PERCENTAGE",
                ),
                subscribers=[budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=email)],
            )

        budgets.CfnBudget(
            self,
            "Budget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="gonogo-monthly",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=limit_usd, unit="USD"),
                cost_filters={"Service": BUDGET_SERVICES},
            ),
            notifications_with_subscribers=[
                alert(50, "ACTUAL"),
                alert(80, "ACTUAL"),
                alert(100, "ACTUAL"),
                alert(100, "FORECASTED"),
            ],
        )
        cdk.CfnOutput(self, "BudgetLimitUsd", value=str(limit_usd))


EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024


class EvalStack(Stack):
    """Vector retrieval for the benchmark (eval/rag.py). S3 Vectors holds the index, so nothing bills while idle
    except a few megabytes of storage; an OpenSearch Serverless collection would bill by the hour."""

    def __init__(self, scope: Construct, id: str, **kw: Any) -> None:
        super().__init__(scope, id, **kw)
        tag(self)
        docs = s3.Bucket(
            self,
            "Corpus",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        vectors = s3vectors.CfnVectorBucket(self, "Vectors", vector_bucket_name=f"gonogo-eval-{self.account}")
        index = s3vectors.CfnIndex(
            self,
            "Index",
            vector_bucket_name=vectors.vector_bucket_name,
            index_name="gonogo-corpus",
            data_type="float32",
            dimension=EMBEDDING_DIMENSIONS,
            distance_metric="cosine",
            # The Knowledge Base stores each chunk's text and its own metadata on the vector. They are too large for
            # filterable metadata, which S3 Vectors caps at 2 KB, so they are marked non-filterable.
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                non_filterable_metadata_keys=["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]
            ),
        )
        index.add_dependency(vectors)
        model_arn = f"arn:aws:bedrock:{self.region}::foundation-model/{EMBEDDING_MODEL}"
        role = iam.Role(
            self,
            "KnowledgeBaseRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            ),
        )
        role.add_to_policy(iam.PolicyStatement(actions=["bedrock:InvokeModel"], resources=[model_arn]))
        docs.grant_read(role)
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "s3vectors:PutVectors",
                    "s3vectors:GetVectors",
                    "s3vectors:DeleteVectors",
                    "s3vectors:QueryVectors",
                    "s3vectors:GetIndex",
                ],
                resources=[index.attr_index_arn],
            )
        )
        kb = bedrock.CfnKnowledgeBase(
            self,
            "KnowledgeBase",
            name="gonogo-corpus",
            role_arn=role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=model_arn,
                    embedding_model_configuration=bedrock.CfnKnowledgeBase.EmbeddingModelConfigurationProperty(
                        bedrock_embedding_model_configuration=bedrock.CfnKnowledgeBase.BedrockEmbeddingModelConfigurationProperty(
                            dimensions=EMBEDDING_DIMENSIONS, embedding_data_type="FLOAT32"
                        )
                    ),
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    index_arn=index.attr_index_arn, vector_bucket_arn=vectors.attr_vector_bucket_arn
                ),
            ),
        )
        kb.node.add_dependency(role)
        source = bedrock.CfnDataSource(
            self,
            "Source",
            name="gonogo-corpus-s3",
            knowledge_base_id=kb.attr_knowledge_base_id,
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(bucket_arn=docs.bucket_arn),
            ),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy="FIXED_SIZE",
                    fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                        max_tokens=300, overlap_percentage=15
                    ),
                )
            ),
            data_deletion_policy="DELETE",
        )
        cdk.CfnOutput(self, "CorpusBucket", value=docs.bucket_name)
        cdk.CfnOutput(self, "KnowledgeBaseId", value=kb.attr_knowledge_base_id)
        cdk.CfnOutput(self, "DataSourceId", value=source.attr_data_source_id)
