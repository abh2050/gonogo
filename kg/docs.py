"""Generate the HTML reference documentation with pyLODE: python -m kg.docs

Outputs go to docs/ontology/, with a copy in ui/public/ontology/. The output is deterministic, so CI
regenerates it and fails on any difference.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from gonogo.paths import DOCS, ONTOLOGY, ROOT, SHAPES

OUT = DOCS / "ontology"
# The UI serves a copy, so the live site and the w3id.org redirect can point at the same documents.
SITE = ROOT / "ui" / "public" / "ontology"
TARGETS = [
    (ONTOLOGY / "gonogo.ttl", "index.html", "ontpub"),
    (ONTOLOGY / "schemes" / "fields.ttl", "fields.html", "vocpub"),
    (ONTOLOGY / "schemes" / "territories.ttl", "territories.html", "vocpub"),
    (ONTOLOGY / "schemes" / "exclusivity.ttl", "exclusivity.html", "vocpub"),
    (ONTOLOGY / "schemes" / "legal-states.ttl", "legal-states.html", "vocpub"),
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
    shutil.rmtree(SITE, ignore_errors=True)
    shutil.copytree(OUT, SITE)
    # RDF clients that ask for Turtle through the w3id.org redirect receive these files.
    shutil.copy(ONTOLOGY / "gonogo.ttl", SITE / "gonogo.ttl")
    shutil.copy(SHAPES / "gonogo-shapes.ttl", SITE / "gonogo-shapes.ttl")
    for scheme in (ONTOLOGY / "schemes").glob("*.ttl"):
        shutil.copy(scheme, SITE / scheme.name)
    print("copied to ui/public/ontology/")


if __name__ == "__main__":
    main()
