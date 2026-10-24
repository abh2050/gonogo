"""Every document uses plain sentences and avoids the banned words from the build spec."""

import re

from gonogo.paths import ROOT

BANNED = ["delve", "crucial", "pivotal", "robust", "seamless", "landscape", "leverage", "unlock", "harness"]


def test_docs_avoid_banned_words() -> None:
    skipped = {".venv", "node_modules", "raw", "build", ".cache"}
    paths = [p for p in ROOT.rglob("*.md") if not skipped & set(p.relative_to(ROOT).parts)]
    assert len(paths) >= 8
    offenders = []
    for path in paths:
        if path.name == "prd.md":
            continue  # The PRD is kept verbatim as a reference input.
        text = path.read_text().lower()
        for word in BANNED:
            if re.search(rf"\b{word}\w*", text):
                offenders.append(f"{path.relative_to(ROOT)}: {word}")
    assert offenders == []


def test_data_sources_counts_match_the_data() -> None:
    from gonogo import counts

    doc = (ROOT / "docs" / "data-sources.md").read_text()
    assert counts.render(doc) == doc, "run: uv run python -m gonogo.counts"
