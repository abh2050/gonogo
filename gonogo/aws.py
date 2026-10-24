"""AWS session and model discovery.

Every AWS call goes through session(), which reads config/aws.yaml and refuses any
region other than the one configured there. Claude model IDs are never hardcoded:
claude_profile() discovers a us. or global. inference profile at run time.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import yaml

from gonogo.paths import CONFIG

ALLOWED_REGION = "us-east-2"
EXPIRED_SESSION_CODES = {"ExpiredToken", "ExpiredTokenException", "UnrecognizedClientException"}


class RegionNotAllowedError(RuntimeError):
    """Raised when code asks for a region the organization SCP denies."""


class ExpiredSessionError(RuntimeError):
    """Raised when the AWS session has expired. The user must run `aws login`."""


@dataclass(frozen=True)
class AwsSettings:
    profile: str
    region: str
    budget_usd: int
    deploy_neptune: bool
    deploy_fargate: bool
    claude_family: str = "sonnet"


def load_settings(path: str | os.PathLike[str] | None = None) -> AwsSettings:
    with open(path or CONFIG / "aws.yaml") as f:
        raw = yaml.safe_load(f)
    settings = AwsSettings(**raw)
    check_region(settings.region)
    return settings


def check_region(region: str | None) -> str:
    if region != ALLOWED_REGION:
        raise RegionNotAllowedError(f"GoNoGo runs only in {ALLOWED_REGION}; got {region!r}")
    return region


def session() -> Any:
    import boto3

    settings = load_settings()
    s = boto3.Session(profile_name=settings.profile, region_name=settings.region)
    check_region(s.region_name)
    return s


def raise_if_expired(exc: Exception) -> None:
    """Convert an expired-credentials error into ExpiredSessionError."""
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
    text = str(exc)
    if code in EXPIRED_SESSION_CODES or "Token has expired" in text or "token is expired" in text.lower():
        raise ExpiredSessionError("The AWS session has expired. Run `aws login` and retry.") from exc


_VERSION_RE = re.compile(r"claude-(opus|sonnet|haiku|fable)-(\d+)(?:-(\d)(?!\d))?")


def profile_version(profile_id: str) -> tuple[str, int, int] | None:
    """Return (family, major, minor) for IDs such as 'us.anthropic.claude-sonnet-5-5'."""
    m = _VERSION_RE.search(profile_id)
    if not m:
        return None
    return m.group(1), int(m.group(2)), int(m.group(3) or 0)


def pick_claude_profile(profiles: list[dict[str, Any]], family: str | None = None) -> str:
    """Choose the newest active Claude inference profile in the family, preferring us. over global."""
    override = os.environ.get("GONOGO_CLAUDE_PROFILE")
    if override:
        return override
    family = family or load_settings().claude_family
    candidates: list[tuple[int, int, bool, str]] = []
    for p in profiles:
        pid = str(p["inferenceProfileId"])
        version = profile_version(pid)
        if p.get("status", "ACTIVE") != "ACTIVE" or version is None or version[0] != family:
            continue
        if pid.split(".", 1)[0] not in {"us", "global"}:
            continue
        candidates.append((version[1], version[2], pid.startswith("us."), pid))
    if not candidates:
        raise LookupError(f"No us. or global. Claude {family} inference profile is available in {ALLOWED_REGION}")
    return max(candidates)[3]


def list_inference_profiles() -> list[dict[str, Any]]:
    client = session().client("bedrock")
    try:
        profiles: list[dict[str, Any]] = []
        for page in client.get_paginator("list_inference_profiles").paginate():
            profiles.extend(page["inferenceProfileSummaries"])
        return profiles
    except Exception as exc:
        raise_if_expired(exc)
        raise


def claude_profile() -> str:
    return pick_claude_profile(list_inference_profiles())
