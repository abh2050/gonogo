"""Record a walk down the Benchmark page: docs/screenshots/benchmark-walk.gif and docs/media/benchmark-walk.mp4.

    uvx --with playwright python scripts/benchmark_walk.py http://localhost:5173

Each step scrolls to one section of the page and holds it for its narration (see walkkit.step).
"""

from __future__ import annotations

import sys

from playwright.sync_api import Page
from walkkit import encode, record, step

# (step key, section heading or None for the top of the page, caption)
STEPS = [
    ("bench-open", None, "200 questions, four answerers, verdicts fixed by hand"),
    ("bench-accuracy", "Verdict accuracy and citations", "GoNoGo 97.5%, graph agent 72.5%, vector RAG 20.5%"),
    ("bench-falsego", "The failure that matters: a false GO", "False GOs: graph agent 32, vector RAG 14, GoNoGo 0"),
    ("bench-why", "Where each one goes wrong", "The model reads; the rules decide"),
]
SCROLL = """
(h) => {
  if (!h) { window.scrollTo({top: 0, behavior: 'smooth'}); return; }
  const s = [...document.querySelectorAll('section.section')].find(x => x.querySelector('h2')?.textContent === h);
  s && window.scrollTo({top: s.getBoundingClientRect().top + window.scrollY - 24, behavior: 'smooth'});
}
"""


def walk(base: str):  # type: ignore[no-untyped-def]
    def run(page: Page) -> None:
        page.goto(f"{base}/#/benchmark")
        page.wait_for_selector(".confusion rect")
        page.wait_for_timeout(3000)  # the charts animate in
        for key, heading, text in STEPS:
            page.evaluate(SCROLL, heading)
            page.wait_for_timeout(700)
            step(page, key, text, 4.0)

    return run


if __name__ == "__main__":
    encode(record(walk(sys.argv[1].rstrip("/"))), "benchmark-walk")
