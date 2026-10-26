"""Record a walk down the Architecture page: architecture-walk.gif in docs/screenshots and the MP4 in docs/media.

    uvx --with playwright python scripts/architecture_walk.py http://localhost:5173

Each step scrolls to a diagram, points at one box so its detail opens, and shows a caption. How long a step is held
comes from docs/media/narration-timing.json (see walkkit.step) when that file exists: the length of the spoken
line for that step. Without the file every step is held for the default.
"""

from __future__ import annotations

import sys

from playwright.sync_api import Page
from walkkit import encode, record, step

DEFAULT_HOLD = 4.0

# (step key, section heading, box label or None, caption)
STEPS = [
    (
        "arch-verdict",
        "From a question to a verdict",
        None,
        "A question becomes a verdict in fixed steps. No model decides.",
    ),
    (
        "arch-parser",
        "From a question to a verdict",
        "Parser",
        "The parser reads concepts and keeps the span each came from.",
    ),
    (
        "arch-rules",
        "From a question to a verdict",
        "Seven rules",
        "Seven rules run on every request, over fixed SPARQL templates.",
    ),
    (
        "arch-candidate",
        "From a question to a verdict",
        "Candidate graph",
        "Proposals wait here. No rule reads this graph.",
    ),
    (
        "arch-combiner",
        "From a question to a verdict",
        "Combiner",
        "A versioned combiner turns rule results into one verdict.",
    ),
    ("arch-record", "From a question to a verdict", "Decision record", "Every decision is signed and can be replayed."),
    ("tworule", "The two-person rule", None, "A risky approval waits for a second person, a counsel."),
    ("access", "Who may read which graph", None, "Each role reads only the graphs it is allowed to."),
]


def walk(base: str):  # type: ignore[no-untyped-def]
    def run(page: Page) -> None:
        page.goto(f"{base}/#/architecture")
        page.wait_for_selector(".dnode")
        page.wait_for_timeout(1200)
        for key, heading, box, text in STEPS:
            section = page.locator("section.section", has=page.locator("h2", has_text=heading))
            section.scroll_into_view_if_needed()
            page.evaluate(
                "(h) => { const s = [...document.querySelectorAll('section.section')]"
                ".find(x => x.querySelector('h2')?.textContent.startsWith(h));"
                " s && s.scrollIntoView({block: 'start'}); }",
                heading,
            )
            if box:
                section.locator(".dnode", has_text=box).first.hover()
            step(page, key, text, DEFAULT_HOLD)

    return run


if __name__ == "__main__":
    encode(record(walk(sys.argv[1].rstrip("/"))), "architecture-walk")
