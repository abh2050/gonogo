"""Build the Lambda bundle: dependencies for arm64, then the GoNoGo source and the graph snapshot.

    uv run python infra/package.py

The bundle holds exactly what the two functions import. It is built with `uv pip install --target` for the Lambda
platform, so it needs no Docker and the same bundle runs on a laptop test and in Lambda.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "infra" / "build" / "lambda"
PACKAGES = ["agent", "authz", "er", "gonogo", "kg", "rules", "service", "api"]
FILES = {"config": ["precedence.yaml", "release.yaml", "aws.yaml"], "shapes": ["*.ttl"], "ontology": ["gonogo.ttl"]}
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "README.md")


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--quiet",
            "--target",
            str(OUT),
            "--python-platform",
            "aarch64-manylinux2014",
            "--python-version",
            "3.12",
            "-r",
            str(ROOT / "infra" / "requirements-lambda.txt"),
        ],
        check=True,
    )
    for pkg in PACKAGES:
        shutil.copytree(ROOT / pkg, OUT / pkg, ignore=SKIP)
    shutil.copytree(ROOT / "rules" / "templates", OUT / "rules" / "templates", dirs_exist_ok=True)
    for folder, patterns in FILES.items():
        (OUT / folder).mkdir(exist_ok=True)
        for pattern in patterns:
            for f in (ROOT / folder).glob(pattern):
                shutil.copy(f, OUT / folder / f.name)
    # The ontology schemes that the vocabulary reads are in the snapshot, so nothing else from data/ is needed.
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    print(f"Built {OUT.relative_to(ROOT)}: {size:.0f} MB")


if __name__ == "__main__":
    main()
