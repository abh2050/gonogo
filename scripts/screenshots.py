"""Take the screenshots in docs/screenshots/ from a running copy of the app.

    # the demo, from a local dev server (start `uv run uvicorn api.index:app` and `cd ui && npm run dev` first)
    uvx --with playwright python scripts/screenshots.py demo http://localhost:5173

    # the AWS deployment, signing in as a user per role
    uvx --with playwright python scripts/screenshots.py aws https://<distribution>.cloudfront.net users.json

Playwright is not a project dependency, so uvx fetches it. The pictures show the app and nothing else: no address
bar, so no distribution name, and the users file (kept out of git) is read but never written to an image.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
VIEW = {"width": 1360, "height": 900}
DECOY = "LAR-17381-1"
HOLD = "A co-owner has not consented"


def shot(page: Page, name: str, selector: str | None = None, full: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.png"
    if selector:
        page.locator(selector).first.screenshot(path=path)
    else:
        if full:  # a sticky header would float mid-page in a tall capture
            page.add_style_tag(content=".topbar{position:static !important}")
        page.screenshot(path=path, full_page=full)
    print("wrote", path.relative_to(OUT.parent.parent))


def go(page: Page, base: str, route: str, wait: str) -> None:
    page.goto(f"{base}/#/{route}")
    page.wait_for_selector(wait, timeout=30000)
    page.wait_for_timeout(400)


def reasoned(page: Page, scope: str, text: str) -> None:
    page.locator(scope).first.locator("input").first.fill(text)


def tour(page: Page, base: str) -> None:
    """The pages that do not depend on who is signed in."""
    go(page, base, "overview", "h1")
    shot(page, "01-overview", full=True)
    go(page, base, "ontology", "h1, svg")
    page.wait_for_timeout(1500)
    shot(page, "02-ontology-graph")
    go(page, base, "vocabularies", "h1")
    page.wait_for_timeout(1200)
    shot(page, "03-vocabularies")
    go(page, base, "findings", "h1")
    page.wait_for_timeout(1200)
    shot(page, "04-data-findings", full=True)
    go(page, base, "time", "h1")
    page.wait_for_timeout(1000)
    shot(page, "05-time-model")
    go(page, base, "architecture", ".dnode")
    page.wait_for_selector(".authz")
    shot(page, "06-architecture", full=True)
    page.locator(".diagram").nth(1).locator(".dnode", has_text="Query Lambda").first.hover()
    shot(page, "07-architecture-aws", ".diagram >> nth=1")


def ask_and_steward(page: Page, base: str, steward: str | None, counsel: str | None) -> None:
    """Ask, hold the decoy for counsel, and let a different counsel approve it."""
    go(page, base, "ask", ".example")
    page.get_by_text(HOLD).click()
    page.wait_for_selector(".verdict-big")
    shot(page, "10-ask-parsed", ".parse-panel")
    shot(page, "11-verdict-card", ".verdict-panel")
    go(page, base, "steward", ".queue-item")
    if steward is None:  # the demo: the visitor types a name and picks a role
        page.get_by_label("Name", exact=True).fill("Ann Steward")
    item = page.locator(".queue-item", has_text=DECOY)
    item.locator("input").fill("The licensee summary matches what I was told.")
    item.get_by_role("button", name="Approve", exact=True).click()
    page.wait_for_selector(".outcome")
    shot(page, "12-held-for-counsel", full=True)
    shot(page, "13-policy-grid", ".authz-wrap")
    if counsel is None:
        page.get_by_label("Role", exact=True).select_option("counsel")
        page.get_by_label("Name", exact=True).fill("Dee Counsel")
    item = page.locator(".queue-item", has_text=DECOY)
    item.locator("input").fill("Checked the assignment record.")
    item.get_by_role("button", name="Approve (second review)").click()
    page.wait_for_selector(".outcome .diff-verdicts")
    shot(page, "14-second-review-go", ".outcome")
    page.get_by_role("button", name="Show the new fact's provenance graph").click()
    page.wait_for_selector(".prov-node")
    page.wait_for_timeout(500)
    shot(page, "15-provenance-graph", ".prov")
    go(page, base, "history", ".timeline circle")
    shot(page, "16-history", full=True)


def demo(base: str) -> None:
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport=VIEW)
        tour(page, base)
        ask_and_steward(page, base, None, None)
        b.close()


def aws(base: str, users_file: str) -> None:
    users = json.loads(Path(users_file).read_text())  # {"pat-manager": {"password": "...", "role": "..."}, ...}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")

        def sign_in(name: str) -> Page:
            ctx = b.new_context(viewport=VIEW)
            page = ctx.new_page()
            page.goto(f"{base}/#/overview")
            page.wait_for_selector(".signin form")
            if name == "pat-manager":
                shot(page, "20-aws-sign-in")
            page.get_by_label("User name").fill(name)
            page.get_by_label("Password").fill(users[name]["password"])
            page.get_by_role("button", name="Sign in").click()
            page.wait_for_selector(".who")
            return page

        page = sign_in("pat-manager")
        go(page, base, "ask", ".example")
        page.get_by_text("A clean non-exclusive license").click()
        page.wait_for_selector(".verdict-big")
        page.get_by_role("button", name="Decide on Neptune").click()
        page.wait_for_selector(".neptune-compare .compare")
        page.wait_for_timeout(300)
        shot(page, "21-aws-neptune-compare", ".neptune-compare")
        shot(page, "22-aws-signed-in-ask", full=True)
        go(page, base, "architecture", ".dnode")
        shot(page, "23-aws-architecture", ".diagram >> nth=1")

        ann = sign_in("ann-steward")
        go(ann, base, "ask", ".example")
        ann.get_by_text(HOLD).click()
        ann.wait_for_selector(".verdict-big")
        go(ann, base, "steward", ".queue-item")
        item = ann.locator(".queue-item", has_text=DECOY)
        item.locator("input").fill("The licensee summary matches what I was told.")
        item.get_by_role("button", name="Approve", exact=True).click()
        ann.wait_for_selector(".outcome")
        shot(ann, "24-aws-held-for-counsel", full=True)
        events = ann.evaluate("sessionStorage.getItem('gonogo-session-v1')")
        dee = sign_in("dee-counsel")
        dee.evaluate("v => sessionStorage.setItem('gonogo-session-v1', v)", events)
        dee.reload()  # the app reads its session once, at start
        dee.wait_for_selector(".who")
        go(dee, base, "steward", ".queue-item")
        item = dee.locator(".queue-item", has_text=DECOY)
        item.locator("input").fill("Checked the assignment record.")
        item.get_by_role("button", name="Approve (second review)").click()
        dee.wait_for_selector(".outcome .diff-verdicts")
        shot(dee, "25-aws-second-review-go", ".outcome")
        b.close()


if __name__ == "__main__":
    mode, base = sys.argv[1], sys.argv[2].rstrip("/")
    demo(base) if mode == "demo" else aws(base, sys.argv[3])
