"""Amazon Verified Permissions: the same policies, with a namespace.

Verified Permissions requires every type to live in a namespace, and the local policy text uses none. This module
rewrites the text and the schema for AWS and builds the requests, so one policy file serves both. A test checks
that the rewritten policies decide exactly as the originals do.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from authz import cedar

NAMESPACE = "GoNoGo"
TYPES = ("Role", "Action", "Graph", "Candidate", "IdentityPair", "Decision", "Request", "Release", "User")
_QUALIFY = re.compile(r"(?<![\w:])(" + "|".join(TYPES) + r")::")


def qualify(text: str) -> str:
    return _QUALIFY.sub(NAMESPACE + r"::\1::", text)


def statements() -> list[tuple[str, str]]:
    """(id, statement) for each policy, namespaced, with comments removed."""
    plain = "\n".join(line for line in cedar.policy_text().splitlines() if not line.strip().startswith("//"))
    out: list[tuple[str, str]] = []
    for block in re.split(r"\n(?=@id\()", "\n" + plain):
        block = block.strip()
        if block.startswith("@id("):
            out.append((re.match(r'@id\("([^"]+)"\)', block).group(1), qualify(block)))  # type: ignore[union-attr]
    return out


def schema() -> dict[str, Any]:
    local = copy.deepcopy(cedar.schema())
    return {NAMESPACE: local[""]}


def schema_json() -> str:
    return json.dumps(schema(), sort_keys=True)


def policy_text() -> str:
    return "\n\n".join(s for _, s in statements())


def _context(ctx: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (ctx or {}).items():
        out[k] = {"boolean": v} if isinstance(v, bool) else {"string": str(v)}
    return {"contextMap": out}


def request(
    principal: cedar.Principal, action: str, resource: tuple[str, str], ctx: dict[str, Any] | None
) -> dict[str, Any]:
    """The arguments of IsAuthorized for one question."""
    return {
        "principal": {"entityType": f"{NAMESPACE}::User", "entityId": principal.name},
        "action": {"actionType": f"{NAMESPACE}::Action", "actionId": action},
        "resource": {"entityType": f"{NAMESPACE}::{resource[0]}", "entityId": resource[1]},
        "context": _context(ctx),
        "entities": {
            "entityList": [
                {
                    "identifier": {"entityType": f"{NAMESPACE}::User", "entityId": principal.name},
                    "attributes": {"name": {"string": principal.name}},
                    "parents": [{"entityType": f"{NAMESPACE}::Role", "entityId": principal.role}],
                },
                {"identifier": {"entityType": f"{NAMESPACE}::Role", "entityId": principal.role}},
                {"identifier": {"entityType": f"{NAMESPACE}::{resource[0]}", "entityId": resource[1]}},
            ]
        },
    }
