"""Shared pieces for the recorded walks: a caption overlay, a recorder, and the GIF and MP4 encoders."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
MEDIA = ROOT / "docs" / "media"
VIEW = {"width": 1280, "height": 1000}

CAPTION_STYLE = (
    "position:fixed;left:50%;bottom:22px;transform:translateX(-50%);max-width:900px;padding:12px 18px;"
    "background:rgba(19,23,31,.92);color:#fff;border-radius:12px;font:600 17px Inter,system-ui,sans-serif;"
    "z-index:99;text-align:center;box-shadow:0 8px 24px rgba(0,0,0,.25)"
)
CAPTION_JS = """
([text, style]) => {
  let el = document.getElementById('walk-caption');
  if (!el) {
    el = document.createElement('div');
    el.id = 'walk-caption';
    el.style.cssText = style;
    document.body.appendChild(el);
  }
  el.textContent = text;
}
"""


def caption(page: Page, text: str) -> None:
    page.evaluate(CAPTION_JS, [text, CAPTION_STYLE])


def click_dot(page: Page, find_js: str, label: str) -> None:
    """Click a node's dot by its position. The text sits under an overlay, so the click goes to the circle."""
    at = page.evaluate(find_js, label)
    if at is None:
        raise RuntimeError(f"No node labeled {label!r}")
    page.mouse.move(at[0], at[1])
    page.mouse.click(at[0], at[1])


def record(script: Callable[[Page], Any]) -> Path:
    tmp = Path(tempfile.mkdtemp())
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        ctx = b.new_context(viewport=VIEW, record_video_dir=str(tmp), record_video_size=VIEW)
        page = ctx.new_page()
        script(page)
        video = page.video
        ctx.close()
        path = Path(video.path()) if video else Path()
        b.close()
    return path


def encode(video: Path, name: str) -> None:
    """Write docs/screenshots/<name>.gif for the README and docs/media/<name>.mp4 for the assembled video."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    gif = SHOTS / f"{name}.gif"
    filters = (
        "fps=8,scale=860:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64[p];"
        "[b][p]paletteuse=dither=bayer:bayer_scale=4"
    )
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf", filters, str(gif)], check=True)
    mp4 = MEDIA / f"{name}.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "26",
            "-r",
            "24",
            str(mp4),
        ],
        check=True,
    )
    shutil.rmtree(video.parent, ignore_errors=True)
    print(f"wrote {gif.relative_to(ROOT)} ({gif.stat().st_size / 1e6:.1f} MB) and {mp4.relative_to(ROOT)}")
