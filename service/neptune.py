"""Amazon Neptune access: SigV4-signed SPARQL over HTTPS from inside the VPC."""

from __future__ import annotations

import os
from typing import Any

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from kg.sparql_store import SparqlStore

SERVICE = "neptune-db"


def endpoint_from_env() -> str:
    host, port = os.environ["NEPTUNE_ENDPOINT"], os.environ.get("NEPTUNE_PORT", "8182")
    return f"https://{host}:{port}/sparql"


def signer(region: str) -> Any:
    """A function that adds an AWS Signature Version 4 header, with credentials fetched fresh on every call."""
    session = boto3.Session()

    def sign(method: str, url: str, body: bytes, headers: dict[str, str]) -> dict[str, str]:
        creds = session.get_credentials()
        assert creds is not None, "no AWS credentials"
        request = AWSRequest(method=method, url=url, data=body, headers=headers)
        SigV4Auth(creds.get_frozen_credentials(), SERVICE, region).add_auth(request)
        return dict(request.headers.items())

    return sign


def store(region: str | None = None) -> SparqlStore:
    region = region or os.environ.get("AWS_REGION", "us-east-2")
    return SparqlStore(endpoint_from_env(), sign=signer(region), timeout=25.0)


def update(sparql: str, region: str | None = None) -> None:
    """Send a SPARQL UPDATE. Only the loader Lambda and the steward path hold the IAM permission to call this."""
    import httpx

    region = region or os.environ.get("AWS_REGION", "us-east-2")
    body = str(httpx.QueryParams({"update": sparql})).encode()
    headers = signer(region)("POST", endpoint_from_env(), body, {"Content-Type": "application/x-www-form-urlencoded"})
    httpx.post(endpoint_from_env(), content=body, headers=headers, timeout=120.0).raise_for_status()
