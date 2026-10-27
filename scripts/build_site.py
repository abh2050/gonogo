"""Prepare the GitHub Pages site: optimize the media for the web and write site/assets/data.json.

    uv run python scripts/build_site.py

The page itself is hand-written (site/index.html, styles.css, main.js). This script only produces the files it
points at, from the sources that already live in the repo, so the site cannot drift from them:

- videos: re-encoded for the web (H.264, no audio where the page loops them), with a poster frame each
- the narrated overview, with its captions converted from SRT to WebVTT
- the draw.io diagrams and the app screenshots, resized
- data.json: the benchmark numbers, read from eval/results.json
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MEDIA, SHOTS, DIAGRAMS = ROOT / "docs" / "media", ROOT / "docs" / "screenshots", ROOT / "docs" / "architecture"
OUT = ROOT / "site" / "assets"

LOOPS = {  # output name: (source, scale filter). Loops are muted, so the audio is dropped.
    "hero": (MEDIA / "graph-intro.mp4", "scale=1280:-2"),
    "ontology": (MEDIA / "ontology-walk.mp4", "scale=1100:-2"),
    "provenance": (MEDIA / "provenance-walk.mp4", "scale=1100:-2"),
    "docs-to-graph": (MEDIA / "docs-to-graph.mp4", "scale=1280:-2"),
    "trust-path": (MEDIA / "trust-path.mp4", "scale=1280:-2"),
}
IMAGES = {  # output name: (source, longest side in pixels)
    "arch-1-overview": (DIAGRAMS / "gonogo-aws-1-overview.png", 2400),
    "arch-2-request": (DIAGRAMS / "gonogo-aws-2-request-path.png", 2000),
    "arch-3-ingestion": (DIAGRAMS / "gonogo-aws-3-ingestion.png", 2200),
    "arch-4-security": (DIAGRAMS / "gonogo-aws-4-security.png", 2200),
    "arch-5-access": (DIAGRAMS / "gonogo-aws-5-data-access.png", 2000),
    "arch-6-benchmark": (DIAGRAMS / "gonogo-aws-6-benchmark.png", 2000),
    "arch-7-stacks": (DIAGRAMS / "gonogo-aws-7-stacks.png", 2000),
    "verdict-card": (SHOTS / "11-verdict-card.png", 1400),
    "parsed-question": (SHOTS / "10-ask-parsed.png", 1400),
    "held-for-counsel": (SHOTS / "12-held-for-counsel.png", 1400),  # cropped below to the banner and the facts
    "second-review": (SHOTS / "14-second-review-go.png", 1400),
    "policy-grid": (SHOTS / "13-policy-grid.png", 1400),
    "provenance-graph": (SHOTS / "15-provenance-graph.png", 1400),
    "ontology-graph": (SHOTS / "02-ontology-graph.png", 1600),
    "benchmark": (SHOTS / "17-benchmark.png", 1400),
    "architecture-page": (SHOTS / "06-architecture.png", 1400),
}


def run(*cmd: str) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def loop(name: str, source: Path, scale: str) -> None:
    if not source.exists():
        print(f"skip {name}: {source.name} is not there yet")
        return
    mp4 = OUT / f"{name}.mp4"
    run("ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-an", "-vf", f"{scale},fps=24", "-c:v", "libx264",
        "-crf", "27", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4))  # fmt: skip
    run("ffmpeg", "-y", "-loglevel", "error", "-ss", "1.5", "-i", str(source), "-frames:v", "1", "-vf", scale,
        "-q:v", "3", str(OUT / f"{name}.jpg"))  # fmt: skip
    print(f"{name}.mp4  {mp4.stat().st_size / 1e6:.1f} MB")


def overview() -> None:
    source = MEDIA / "gonogo-overview.mp4"
    mp4 = OUT / "overview.mp4"
    run("ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-vf", "scale=1280:-2", "-c:v", "libx264",
        "-crf", "28", "-preset", "slow", "-c:a", "aac", "-b:a", "96k", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(mp4))  # fmt: skip
    run("ffmpeg", "-y", "-loglevel", "error", "-ss", "4", "-i", str(source), "-frames:v", "1", "-q:v", "3",
        str(OUT / "overview.jpg"))  # fmt: skip
    srt = (MEDIA / "gonogo-overview.srt").read_text()
    vtt = "WEBVTT\n\n" + re.sub(r"(\d\d:\d\d:\d\d),(\d{3})", r"\1.\2", srt)
    (OUT / "overview.vtt").write_text(vtt)
    print(f"overview.mp4  {mp4.stat().st_size / 1e6:.1f} MB")


CROPS = {"held-for-counsel": (1100, 1360, 540)}  # name: (height, width, top offset) in the source's own pixels


def image(name: str, source: Path, longest: int) -> None:
    target = OUT / f"{name}.png"
    shutil.copy(source, target)
    if name in CROPS:
        height, width, top = CROPS[name]
        run("sips", "-c", str(height), str(width), "--cropOffset", str(top), "0", str(target))
    run("sips", "-Z", str(longest), str(target))
    print(f"{name}.png  {target.stat().st_size / 1e3:.0f} KB")


def data() -> None:
    res = json.loads((ROOT / "eval" / "results.json").read_text())
    keep = (
        "accuracy",
        "false_go_rate",
        "missed_go_rate",
        "decisive_recall",
        "latency_p50_s",
        "model_cost_usd",
        "questions",
    )
    out: dict[str, Any] = {k: {m: v[m] for m in keep} | {"false_go": len(v["false_go"])} for k, v in res.items()}
    pg = ROOT / "pgraph" / "results.json"
    out["property_graph"] = json.loads(pg.read_text()) if pg.exists() else None
    (OUT / "data.json").write_text(json.dumps(out, indent=1) + "\n")
    print("data.json")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (source, scale) in LOOPS.items():
        loop(name, source, scale)
    overview()
    for name, (source, longest) in IMAGES.items():
        image(name, source, longest)
    data()
    total = sum(f.stat().st_size for f in OUT.iterdir())
    print(f"\n{len(list(OUT.iterdir()))} files, {total / 1e6:.1f} MB in site/assets")


if __name__ == "__main__":
    main()
