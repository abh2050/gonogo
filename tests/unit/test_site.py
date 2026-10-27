"""The GitHub Pages site (site/) keeps its promises: its numbers match the scored benchmark, every file it points at
exists, and it carries no wording that does not belong in a public repo."""

from __future__ import annotations

import json
import re

from gonogo.paths import ROOT

SITE = ROOT / "site"
HTML = (SITE / "index.html").read_text()
RESULTS = json.loads((ROOT / "eval" / "results.json").read_text())


def test_the_benchmark_numbers_on_the_page_are_the_scored_ones() -> None:
    for key, label in (("C+", "97.5%"), ("B", "72.5%"), ("C", "50.5%"), ("A", "20.5%")):
        assert RESULTS[key]["accuracy"] == float(label.rstrip("%"))
        assert f'data-key="{key}" data-value="{label.rstrip("%")}"' in HTML
        assert f'<div class="val">{label}</div>' in HTML
    for key, n in (("B", 32), ("A", 14)):
        assert len(RESULTS[key]["false_go"]) == n
        assert f'data-count="{n}">{n}</b>' in HTML
    assert len(RESULTS["C+"]["false_go"]) == 0 == len(RESULTS["C"]["false_go"])
    assert "97.5" in HTML and "1.6 s" in HTML and round(RESULTS["C+"]["latency_p50_s"], 1) == 1.6


def test_every_local_file_the_page_references_exists() -> None:
    refs = set(re.findall(r'(?:src|href|poster)="((?:assets/)[^"]+)"', HTML))
    refs |= set(re.findall(r'url\("(assets/[^"]+)"\)', (SITE / "styles.css").read_text()))
    assert refs
    for ref in refs:
        assert (SITE / ref).exists(), ref
    assert (SITE / "styles.css").exists() and (SITE / "main.js").exists()


def test_the_page_has_a_title_a_description_and_a_share_image() -> None:
    assert re.search(r"<title>[^<]{20,}</title>", HTML)
    assert 'name="description"' in HTML and 'property="og:image"' in HTML
    assert "assets/og.jpg" in HTML and (SITE / "assets" / "og.jpg").exists()


def test_every_image_has_alt_text_and_every_video_a_label_or_caption() -> None:
    for tag in re.findall(r"<img\b[^>]*>", HTML):
        assert re.search(r'alt="', tag), tag
    for tag in re.findall(r"<video\b[^>]*>", HTML):
        assert "aria-hidden" in tag or "aria-label" in tag or "controls" in tag, tag
    assert 'kind="captions"' in HTML


def test_the_page_keeps_the_public_repo_clean() -> None:
    text = (HTML + (SITE / "main.js").read_text()).lower()
    for word in ("job search", "hiring", "recruit", "resume", "interview", "employer", "career"):
        assert word not in text, word
    for banned in ("delve", "crucial", "pivotal", "robust", "seamless", "landscape", "leverage", "unlock", "harness"):
        assert banned not in text, banned
    assert "054772656600" not in text


def test_the_demo_and_repo_links_point_at_the_right_places() -> None:
    assert "https://gonogo-livid.vercel.app/#/ask" in HTML
    assert "https://github.com/abh2050/gonogo" in HTML
