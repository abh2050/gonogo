"""Who is calling: a Cognito user, read from the claims that API Gateway verified, never from the request body."""

from __future__ import annotations

from typing import Any

from authz.cedar import ROLES, Principal


class IdentityError(PermissionError):
    pass


def groups_from(claims: dict[str, Any]) -> list[str]:
    """Cognito puts the groups claim in as a list or as a string such as '[steward]'."""
    raw = claims.get("cognito:groups", [])
    if isinstance(raw, str):
        raw = raw.strip("[]").replace(",", " ").split()
    return [str(g) for g in raw]


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    """One person holds exactly one role. A user in two groups could play both parts of a two-person rule."""
    roles = [g for g in groups_from(claims) if g in ROLES]
    if len(roles) != 1:
        raise IdentityError(f"A user must belong to exactly one role group, and this one belongs to {len(roles)}.")
    name = str(claims.get("cognito:username") or claims.get("username") or claims.get("sub") or "")
    if not name:
        raise IdentityError("The token carries no user name.")
    return Principal(name, roles[0])


def claims_from_event(event: dict[str, Any]) -> dict[str, Any] | None:
    ctx = event.get("requestContext") or {}
    auth = ctx.get("authorizer") or {}
    claims = auth.get("claims")
    return dict(claims) if claims else None
