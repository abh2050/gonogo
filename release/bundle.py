"""The release bundle: which files make one, and a digest that changes when any of them does."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

# Everything that can change a verdict. Code that decides is part of the release, not only the data it reads.
PATTERNS = [
    "ontology/gonogo.ttl",
    "ontology/schemes/*.ttl",
    "ontology/imports/*.ttl",
    "ontology/reference/*.ttl",
    "shapes/*.ttl",
    "rules/templates/*.rq",
    "rules/r*_*.py",
    "rules/engine.py",
    "rules/context.py",
    "rules/common.py",
    "rules/policy.py",
    "config/precedence.yaml",
    "mappings/gonogo.r2rml.ttl",
]


def files(root: Path) -> list[Path]:
    found: set[Path] = set()
    for pattern in PATTERNS:
        found |= {p for p in root.glob(pattern) if p.is_file()}
    return sorted(found)


def manifest(root: Path) -> dict[str, Any]:
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files(root)}
    version = str(yaml.safe_load((root / "config" / "release.yaml").read_text())["ontology_release"])
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return {"version": version, "digest": digest, "files": hashes}


def changed(base: dict[str, Any], new: dict[str, Any]) -> dict[str, list[str]]:
    a, b = base["files"], new["files"]
    return {
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
        "modified": sorted(k for k in set(a) & set(b) if a[k] != b[k]),
    }


def touched(diff: dict[str, list[str]]) -> list[str]:
    return sorted({f for fs in diff.values() for f in fs})
