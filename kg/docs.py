"""Generate the HTML reference documentation with pyLODE: python -m kg.docs

Outputs go to docs/ontology/. The output is deterministic, so CI regenerates it and fails on any difference.
"""

from __future__ import annotations

import subprocess
import sys

from gonogo.paths import DOCS, ONTOLOGY, SHAPES

OUT = DOCS / "ontology"
TARGETS = [
    (ONTOLOGY / "gonogo.ttl", "index.html", "ontpub"),
    (ONTOLOGY / "schemes" / "fields.ttl", "fields.html", "vocpub"),
    (SHAPES / "gonogo-shapes.ttl", "shapes.html", "valpub"),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for source, name, profile in TARGETS:
        subprocess.run(
            [sys.executable, "-m", "pylode", str(source), "-o", str(OUT / name), "-p", profile, "-l", "warning"],
            check=True,
        )
        print(f"wrote docs/ontology/{name}")


if __name__ == "__main__":
    main()
