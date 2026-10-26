"""Record a guided walk through the ontology graph: docs/screenshots/ontology-walk.gif and docs/media/ontology-walk.mp4.

    uvx --with playwright python scripts/ontology_gif.py http://localhost:5173

The walk clicks one class at a time. The page lights up that class's relationships and moves the dashes along their
arrows, and a caption says what the relationship means.
"""

from __future__ import annotations

import sys

from playwright.sync_api import Page
from walkkit import caption, click_dot, encode, record

# (the label drawn on the class, the caption). The captions say what the arrows mean, in the order a reader needs them.
WALK = [
    ("Patent", "A patent is the thing every license is about."),
    ("Grant", "A grant points at a patent (gng:aboutPatent). Its subclasses are proposed and executed."),
    ("Executed grant", "A signed license adds a licensee, a term, and an exclusivity type."),
    ("Field of use", "Its field sits in a SKOS hierarchy. A grant for a broader field covers the narrower ones."),
    ("Territory", "Territories nest the same way: a grant for North America covers the United States."),
    ("Bitemporal fact", "Every fact has a valid time and a recording time, so any past decision can be rerun."),
    ("Field of use assignment", "A model proposes a field of use. It stays a candidate until a person approves it."),
    ("Second review", "A conflicting or verdict-changing approval waits for counsel."),
    ("Decision", "A decision records the facts that the rules read, the release, and a signature."),
]
FIND_JS = """
(label) => {
  const squash = (s) => s.replace(/\\s+/g, '');
  const want = squash(label);
  for (const g of document.querySelectorAll('svg g')) {
    const c = g.querySelector(':scope > circle');
    if (!c) continue;
    const text = Array.from(g.querySelectorAll(':scope > text')).map((t) => t.textContent).join('');
    if (squash(text) === want) { const r = c.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }
  }
  return null;
}
"""


def walk(base: str):  # type: ignore[no-untyped-def]
    def run(page: Page) -> None:
        page.goto(f"{base}/#/ontology")
        page.wait_for_selector("svg text")
        page.wait_for_timeout(2500)  # let the layout settle
        page.evaluate("window.scrollTo(0, 260)")
        caption(page, "The ontology: 48 classes. Watch the arrows move.")
        page.wait_for_timeout(1800)
        for label, text in WALK:
            click_dot(page, FIND_JS, label)
            caption(page, text)
            page.wait_for_timeout(2600)

    return run


if __name__ == "__main__":
    encode(record(walk(sys.argv[1].rstrip("/"))), "ontology-walk")
