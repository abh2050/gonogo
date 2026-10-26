"""Record a walk over the draw.io AWS diagram: docs/media/diagram-walk.mp4.

    uvx --with playwright python scripts/diagram_walk.py

The camera moves from one region of docs/architecture/gonogo-aws.png to the next. Each step is held for its narration,
the same way as the other walks (see walkkit.step).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from playwright.sync_api import Page
from walkkit import ROOT, encode, record, step

IMG = ROOT / "docs" / "architecture" / "gonogo-aws.png"
# (step key, caption, focus x, focus y as fractions of the picture, zoom)
STEPS = [
    ("dia-overview", "GoNoGo on AWS (us-east-2)", 0.5, 0.5, 1.0),
    ("dia-edge", "CloudFront in front of a private S3 bucket", 0.17, 0.3, 2.2),
    ("dia-auth", "API Gateway checks the Cognito token on every call", 0.37, 0.3, 2.2),
    ("dia-engine", "The engine Lambda asks Cedar who may do what", 0.55, 0.3, 2.2),
    ("dia-data", "Decisions: DynamoDB, S3 Object Lock, EventBridge, KMS", 0.8, 0.4, 1.8),
    ("dia-vpc", "A VPC with no internet route. One reader, one writer", 0.72, 0.76, 1.55),
    ("dia-cost", "A $10 budget alarm, and one script to tear it all down", 0.07, 0.75, 2.6),
]
PAGE = """<!doctype html><body style="margin:0;background:#fff;overflow:hidden">
<div id="w" style="position:absolute;left:0;top:0;transform-origin:0 0;transition:transform 1.4s ease-in-out">
<img id="i" src="{src}" style="display:block"></div></body>"""
MOVE = """
([fx, fy, zoom]) => {
  const vw = innerWidth, vh = innerHeight, img = document.getElementById('i');
  const base = Math.min(vw / img.naturalWidth, vh / img.naturalHeight);
  const w = img.naturalWidth * base, h = img.naturalHeight * base;
  img.style.width = w + 'px'; img.style.height = h + 'px';
  const ox = (vw - w) / 2, oy = (vh - h) / 2;
  const tx = vw / 2 - (ox + fx * w) * zoom, ty = vh / 2 - (oy + fy * h) * zoom;
  document.getElementById('w').style.transform = `translate(${tx}px, ${ty}px) scale(${zoom})`;
}
"""


def walk(page: Page) -> None:
    html = Path(tempfile.mkdtemp()) / "diagram.html"
    html.write_text(PAGE.format(src=IMG.as_uri()))
    page.goto(html.as_uri())
    page.wait_for_function("document.getElementById('i').complete")
    for key, text, fx, fy, zoom in STEPS:
        page.evaluate(MOVE, [fx, fy, zoom])
        step(page, key, text, 4.0)


if __name__ == "__main__":
    encode(record(walk), "diagram-walk")
