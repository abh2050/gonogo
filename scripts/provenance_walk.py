"""Record a walk along the provenance of one approved fact: docs/screenshots/provenance-walk.gif and the MP4.

    uvx --with playwright python scripts/provenance_walk.py http://localhost:5173

A steward approves a proposed export classification. The walk then follows the trail the approval left, one hop at a
time, in the vocabulary of PROV-O: who approved it, which action generated it, what it was derived from, and what
it is about.
"""

from __future__ import annotations

import sys

from playwright.sync_api import Page
from walkkit import caption, click_dot, encode, record

# (a piece of the node's label, the caption). Each hop follows one relationship.
WALK = [
    ("approved-evt", "An approved fact. Every fact carries its own provenance."),
    ("Demo Steward", "gng:approvedBy. A named person approved it, not a standing policy."),
    ("evt-001", "prov:wasGeneratedBy. The action that made it, with its time and the steward's reason."),
    ("/candidate", "prov:wasDerivedFrom. The proposal it was copied from. The proposal stays, unchanged."),
    ("Export control review desk", "gng:proposedBy. Who put it forward. A proposer can never be its approver."),
    ("v0.1", "The proposal's own origin: the run that generated it, labeled synthetic."),
    ("Extreme Low", "gng:aboutPatent. What the fact is about. Nothing here was edited or deleted."),
]
FIND_JS = """
(piece) => {
  for (const g of document.querySelectorAll('g.prov-node')) {
    const text = Array.from(g.querySelectorAll('text')).map((t) => t.textContent).join('');
    if (text.includes(piece)) {
      const c = g.querySelector('circle'); const r = c.getBoundingClientRect();
      return [r.x + r.width / 2, r.y + r.height / 2];
    }
  }
  return null;
}
"""


def walk(base: str):  # type: ignore[no-untyped-def]
    def run(page: Page) -> None:
        page.goto(f"{base}/#/steward")
        page.wait_for_selector(".queue-item")
        item = page.locator(".queue-item", has_text="LAR-17317-2").first
        item.locator("input").fill("Export control review found no restriction.")
        item.get_by_role("button", name="Approve", exact=True).click()
        page.wait_for_selector(".outcome")
        page.get_by_role("button", name="Show the new fact's provenance graph").click()
        page.wait_for_selector(".prov-node")
        page.wait_for_timeout(1500)
        page.locator(".prov").scroll_into_view_if_needed()
        page.evaluate("window.scrollBy(0, 40)")
        caption(page, "Provenance: the trail behind one approved fact.")
        page.wait_for_timeout(2000)
        for piece, text in WALK:
            click_dot(page, FIND_JS, piece)
            caption(page, text)
            page.wait_for_timeout(2800)

    return run


if __name__ == "__main__":
    encode(record(walk(sys.argv[1].rstrip("/"))), "provenance-walk")
