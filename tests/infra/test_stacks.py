"""The CDK stacks, synthesized in memory and checked as templates. No AWS account is touched."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk import assertions

from authz import avp
from authz.cedar import ROLES
from gonogo.aws import RegionNotAllowedError, check_region

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))
import stacks  # noqa: E402


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("lambda")
    (path / "handler.py").write_text("def handler(e, c): return {}\n")
    return path


def synth(bundle: Path, neptune: bool, email: str | None = "budget@example.invalid") -> dict[str, assertions.Template]:
    stacks.BUILD = bundle
    stacks.DIST = bundle / "dist"
    stacks.DIST.mkdir(exist_ok=True)
    (stacks.DIST / "index.html").write_text("<html></html>")
    app = cdk.App()
    env = cdk.Environment(account="123456789012", region="us-east-2")
    core = stacks.CoreStack(app, "gonogo-core", env=env)
    api = stacks.ApiStack(app, "gonogo-api", core=core, deploy_neptune=neptune, env=env)
    ui = stacks.UiStack(app, "gonogo-ui", core=core, api=api, neptune=neptune, env=env)
    budget = stacks.BudgetStack(app, "gonogo-budget", limit_usd=10, email=email, env=env) if email else None
    out = {
        "core": assertions.Template.from_stack(core),
        "api": assertions.Template.from_stack(api),
        "ui": assertions.Template.from_stack(ui),
    }
    if budget is not None:  # every stack is created before the first synthesis, because a tree cannot change after it
        out["budget"] = assertions.Template.from_stack(budget)
    return out


@pytest.fixture(scope="module")
def full(bundle: Path) -> dict[str, assertions.Template]:
    return synth(bundle, neptune=True)


@pytest.fixture(scope="module")
def light(bundle: Path) -> dict[str, assertions.Template]:
    return synth(bundle, neptune=False, email=None)


def resources(t: assertions.Template, kind: str) -> dict[str, Any]:
    return dict(t.find_resources(kind))


# ---- Money -------------------------------------------------------------------------------------------------------


def test_nothing_that_bills_while_idle_exists_without_the_neptune_flag(light: dict[str, assertions.Template]) -> None:
    api = light["api"]
    for kind in ("AWS::Neptune::DBCluster", "AWS::Neptune::DBInstance", "AWS::EC2::NatGateway", "AWS::EC2::VPC"):
        api.resource_count_is(kind, 0)
    assert "budget" not in light


def test_there_is_never_a_nat_gateway_interface_endpoint_or_internet_gateway(
    full: dict[str, assertions.Template],
) -> None:
    api = full["api"]
    api.resource_count_is("AWS::EC2::NatGateway", 0)
    api.resource_count_is("AWS::EC2::InternetGateway", 0)
    endpoints = resources(api, "AWS::EC2::VPCEndpoint")
    assert endpoints and all(e["Properties"].get("VpcEndpointType") == "Gateway" for e in endpoints.values())


def test_the_budget_is_ten_dollars_and_alerts_four_ways(full: dict[str, assertions.Template]) -> None:
    [budget] = resources(full["budget"], "AWS::Budgets::Budget").values()
    props = budget["Properties"]
    assert props["Budget"]["BudgetLimit"] == {"Amount": 10, "Unit": "USD"}
    assert props["Budget"]["CostFilters"]["Service"] == stacks.BUDGET_SERVICES, "only GoNoGo's own services count"
    assert "Amazon Bedrock" not in stacks.BUDGET_SERVICES
    notes = [
        (n["Notification"]["NotificationType"], n["Notification"]["Threshold"])
        for n in props["NotificationsWithSubscribers"]
    ]
    assert notes == [("ACTUAL", 50), ("ACTUAL", 80), ("ACTUAL", 100), ("FORECASTED", 100)]


# ---- Data at rest -------------------------------------------------------------------------------------------------


def test_every_bucket_is_private_encrypted_and_ssl_only(full: dict[str, assertions.Template]) -> None:
    core = full["core"]
    buckets = resources(core, "AWS::S3::Bucket")
    assert len(buckets) == 2
    for b in buckets.values():
        p = b["Properties"]
        assert p["PublicAccessBlockConfiguration"] == {
            "BlockPublicAcls": True,
            "BlockPublicPolicy": True,
            "IgnorePublicAcls": True,
            "RestrictPublicBuckets": True,
        }
        assert (
            p["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]["ServerSideEncryptionByDefault"][
                "SSEAlgorithm"
            ]
            == "aws:kms"
        )
    policies = " ".join(str(p) for p in resources(core, "AWS::S3::BucketPolicy").values())
    assert policies.count("aws:SecureTransport") >= 2


def test_the_audit_bucket_is_versioned_and_object_locked(full: dict[str, assertions.Template]) -> None:
    locked = [
        b for b in resources(full["core"], "AWS::S3::Bucket").values() if b["Properties"].get("ObjectLockEnabled")
    ]
    assert len(locked) == 1
    p = locked[0]["Properties"]
    assert p["VersioningConfiguration"] == {"Status": "Enabled"}
    rule = p["ObjectLockConfiguration"]["Rule"]["DefaultRetention"]
    assert rule == {"Mode": "GOVERNANCE", "Days": 1}


def test_the_decisions_table_has_point_in_time_recovery_and_a_customer_key(
    full: dict[str, assertions.Template],
) -> None:
    [table] = resources(full["core"], "AWS::DynamoDB::Table").values()
    p = table["Properties"]
    assert p["PointInTimeRecoverySpecification"] == {"PointInTimeRecoveryEnabled": True}
    assert p["SSESpecification"]["SSEType"] == "KMS" and p["BillingMode"] == "PAY_PER_REQUEST"


def test_the_key_rotates(full: dict[str, assertions.Template]) -> None:
    [key] = resources(full["core"], "AWS::KMS::Key").values()
    assert key["Properties"]["EnableKeyRotation"] is True and key["Properties"]["PendingWindowInDays"] == 7


def test_neptune_is_serverless_encrypted_and_iam_only(full: dict[str, assertions.Template]) -> None:
    [cluster] = resources(full["api"], "AWS::Neptune::DBCluster").values()
    p = cluster["Properties"]
    assert p["IamAuthEnabled"] is True and p["StorageEncrypted"] is True and p["DeletionProtection"] is False
    assert p["ServerlessScalingConfiguration"] == {"MinCapacity": 1, "MaxCapacity": 4}
    [instance] = resources(full["api"], "AWS::Neptune::DBInstance").values()
    assert instance["Properties"]["DBInstanceClass"] == "db.serverless"
    assert cluster["DeletionPolicy"] == instance["DeletionPolicy"] == "Delete", "no final snapshot is left behind"


# ---- Who can reach what -------------------------------------------------------------------------------------------


def test_every_api_method_requires_a_cognito_token(full: dict[str, assertions.Template]) -> None:
    methods = [m["Properties"] for m in resources(full["api"], "AWS::ApiGateway::Method").values()]
    assert len(methods) == 4
    assert all(m["AuthorizationType"] == "COGNITO_USER_POOLS" for m in methods)


def test_the_api_is_throttled_and_validates_request_bodies(full: dict[str, assertions.Template]) -> None:
    [stage] = resources(full["api"], "AWS::ApiGateway::Stage").values()
    settings = stage["Properties"]["MethodSettings"][0]
    assert settings["ThrottlingRateLimit"] == 20 and settings["ThrottlingBurstLimit"] == 40
    validated = [
        m["Properties"]
        for m in resources(full["api"], "AWS::ApiGateway::Method").values()
        if "RequestValidatorId" in m["Properties"]
    ]
    assert len(validated) == 2
    models = [m["Properties"]["Schema"] for m in resources(full["api"], "AWS::ApiGateway::Model").values()]
    assert all(s["additionalProperties"] is False for s in models)
    assert {s["properties"].get("query", {}).get("maxLength") for s in models} >= {8000}


def test_there_is_one_cognito_group_per_role(full: dict[str, assertions.Template]) -> None:
    groups = {g["Properties"]["GroupName"] for g in resources(full["core"], "AWS::Cognito::UserPoolGroup").values()}
    assert groups == set(ROLES)
    [pool] = resources(full["core"], "AWS::Cognito::UserPool").values()
    assert pool["Properties"]["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"] is True


def statements(t: assertions.Template, role_fragment: str) -> list[dict[str, Any]]:
    out = []
    for pol in resources(t, "AWS::IAM::Policy").values():
        if role_fragment in str(pol["Properties"]["Roles"]):
            out += pol["Properties"]["PolicyDocument"]["Statement"]
    return out


def actions(stmts: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for s in stmts:
        a = s["Action"]
        out |= set(a if isinstance(a, list) else [a])
    return out


def test_the_query_function_can_only_read_neptune_and_the_loader_alone_can_write(
    full: dict[str, assertions.Template],
) -> None:
    api = full["api"]
    query = {a for a in actions(statements(api, "Query")) if a.startswith("neptune-db:")}
    loader = {a for a in actions(statements(api, "Loader")) if a.startswith("neptune-db:")}
    assert query == {"neptune-db:connect", "neptune-db:ReadDataViaQuery"}
    assert "neptune-db:WriteDataViaQuery" in loader
    assert not any(a.startswith("neptune-db:") for a in actions(statements(api, "Engine"))), (
        "the engine never touches Neptune"
    )


def test_no_role_policy_grants_a_wildcard_action(full: dict[str, assertions.Template]) -> None:
    for stack in ("api", "core"):
        for pol in resources(full[stack], "AWS::IAM::Policy").values():
            for s in pol["Properties"]["PolicyDocument"]["Statement"]:
                acts = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
                assert "*" not in acts and not any(a.endswith(":*") for a in acts), s


def test_the_lambdas_in_the_vpc_are_the_only_ones_with_a_vpc_config(full: dict[str, assertions.Template]) -> None:
    fns = {
        k: v["Properties"]
        for k, v in resources(full["api"], "AWS::Lambda::Function").items()
        if "Handler" in v["Properties"]
    }
    in_vpc = {k for k, p in fns.items() if "VpcConfig" in p}
    assert len(fns) == 3 and len(in_vpc) == 2
    assert all(p["Architectures"] == ["arm64"] and p["Runtime"] == "python3.12" for p in fns.values())


def test_the_neptune_security_group_admits_only_its_own_members(full: dict[str, assertions.Template]) -> None:
    for ing in resources(full["api"], "AWS::EC2::SecurityGroupIngress").values():
        assert ing["Properties"]["FromPort"] == ing["Properties"]["ToPort"] == 8182
        assert "SourceSecurityGroupId" in ing["Properties"] and "CidrIp" not in ing["Properties"]
    for sg in resources(full["api"], "AWS::EC2::SecurityGroup").values():
        assert "SecurityGroupIngress" not in sg["Properties"] or not sg["Properties"]["SecurityGroupIngress"]


# ---- Policies ----------------------------------------------------------------------------------------------------


# ---- The UI -------------------------------------------------------------------------------------------------------


def test_the_ui_bucket_is_private_and_reachable_only_through_cloudfront(full: dict[str, assertions.Template]) -> None:
    ui = full["ui"]
    [bucket] = resources(ui, "AWS::S3::Bucket").values()
    assert bucket["Properties"]["PublicAccessBlockConfiguration"]["BlockPublicPolicy"] is True
    policy = str(resources(ui, "AWS::S3::BucketPolicy"))
    assert "cloudfront.amazonaws.com" in policy and "AWS:SourceArn" in policy, "access is limited to this distribution"
    ui.resource_count_is("AWS::CloudFront::OriginAccessControl", 1)


def test_cloudfront_serves_https_only_with_security_headers_and_a_strict_csp(
    full: dict[str, assertions.Template],
) -> None:
    [dist] = resources(full["ui"], "AWS::CloudFront::Distribution").values()
    cfg = dist["Properties"]["DistributionConfig"]
    assert cfg["DefaultCacheBehavior"]["ViewerProtocolPolicy"] == "redirect-to-https"
    assert "ViewerCertificate" not in cfg or cfg["ViewerCertificate"].get("CloudFrontDefaultCertificate") is True
    policies = [
        p["Properties"]["ResponseHeadersPolicyConfig"]
        for p in resources(full["ui"], "AWS::CloudFront::ResponseHeadersPolicy").values()
    ]
    csp = next(
        p["SecurityHeadersConfig"]["ContentSecurityPolicy"]["ContentSecurityPolicy"]
        for p in policies
        if "ContentSecurityPolicy" in p["SecurityHeadersConfig"]
    )
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-inline'; img" in csp
    assert "unsafe-eval" not in csp and "connect-src 'self' https://cognito-idp.us-east-2.amazonaws.com" in csp


def test_the_api_paths_pass_through_cloudfront_with_the_token_and_no_caching(
    full: dict[str, assertions.Template],
) -> None:
    [dist] = resources(full["ui"], "AWS::CloudFront::Distribution").values()
    behaviors = {b["PathPattern"]: b for b in dist["Properties"]["DistributionConfig"]["CacheBehaviors"]}
    for path in stacks.API_PATHS:
        b = behaviors[path]
        assert b["ViewerProtocolPolicy"] == "https-only" and len(b["AllowedMethods"]) == 7
    assert "/ontology/*" in behaviors


def test_the_browser_gets_its_configuration_from_a_file_the_deploy_writes(full: dict[str, assertions.Template]) -> None:
    [deploy] = resources(full["ui"], "Custom::CDKBucketDeployment").values()
    assert len(deploy["Properties"]["SourceObjectKeys"]) == 2, "the built app, and the generated config.json"
    assert deploy["Properties"]["Prune"] is True and deploy["Properties"]["DistributionPaths"] == ["/*"]


def test_the_api_is_regional_because_cloudfront_fronts_it(full: dict[str, assertions.Template]) -> None:
    [api] = resources(full["api"], "AWS::ApiGateway::RestApi").values()
    assert api["Properties"]["EndpointConfiguration"]["Types"] == ["REGIONAL"]


def test_every_cedar_policy_is_in_the_policy_store_exactly_as_the_adapter_writes_it(
    full: dict[str, assertions.Template],
) -> None:
    deployed = {
        p["Properties"]["Definition"]["Static"]["Description"]: p["Properties"]["Definition"]["Static"]["Statement"]
        for p in resources(full["core"], "AWS::VerifiedPermissions::Policy").values()
    }
    assert deployed == dict(avp.statements())
    [store] = resources(full["core"], "AWS::VerifiedPermissions::PolicyStore").values()
    assert store["Properties"]["ValidationSettings"] == {"Mode": "STRICT"}
    assert store["Properties"]["Schema"]["CedarJson"] == avp.schema_json()


def test_every_resource_carries_the_project_tag(full: dict[str, assertions.Template]) -> None:
    for kind in ("AWS::S3::Bucket", "AWS::DynamoDB::Table", "AWS::KMS::Key"):
        for r in resources(full["core"], kind).values():
            assert {"Key": "project", "Value": "gonogo"} in r["Properties"]["Tags"]


# ---- Region ------------------------------------------------------------------------------------------------------


def test_the_app_refuses_any_region_but_us_east_2() -> None:
    assert check_region("us-east-2") == "us-east-2"
    for bad in ("us-east-1", "us-west-2", "eu-west-1"):
        with pytest.raises(RegionNotAllowedError):
            check_region(bad)


# ---- The inventory ------------------------------------------------------------------------------------------------


def test_every_resource_type_has_a_plain_description_and_the_inventory_is_current() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))
    import inventory

    resources = inventory.synthesize()
    kinds = {r["Type"] for stack in resources.values() for r in stack.values()}
    assert kinds - {"AWS::CDK::Metadata"} <= set(inventory.PURPOSE), kinds - set(inventory.PURPOSE)
    assert inventory.OUT.read_text() == inventory.render(), "run: uv run python infra/inventory.py"
