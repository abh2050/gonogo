"""Read secrets from the environment, falling back to the git-ignored .env file."""

from __future__ import annotations

import os

from gonogo.paths import ROOT


def get(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name and value.strip():
                return value.strip()
    return None
