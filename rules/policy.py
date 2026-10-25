"""The decision combiner: turn rule statuses into one verdict under a versioned precedence policy."""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from typing import Any

import yaml

from gonogo.paths import ROOT
from rules.model import Status

POLICY_FILE = ROOT / "config" / "precedence.yaml"


@lru_cache(maxsize=1)
def load_policy(path: str = str(POLICY_FILE)) -> dict[str, Any]:
    with open(path) as f:
        policy: dict[str, Any] = yaml.safe_load(f)
    return policy


def policy_version() -> str:
    return str(load_policy()["version"])


def combine(statuses: Iterable[Status], policy: dict[str, Any] | None = None) -> str:
    """Apply the precedence list from the top. The first status that appears decides the verdict."""
    policy = policy or load_policy()
    present = {str(s) for s in statuses} - set(policy["ignored_statuses"])
    for entry in policy["precedence"]:
        if entry["status"] in present:
            return str(entry["verdict"])
    return str(policy["default_verdict"])
