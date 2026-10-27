"""Make site/assets/og.jpg, the preview that LinkedIn and other sites show when the page is shared.

    (cd site && python3 -m http.server 8765) &
    uvx --with playwright python scripts/site_og.py

It photographs the hero at 1200 x 630 with the stats strip hidden, so the headline fills the card.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "site" / "assets" / "og.jpg"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page(viewport={"width": 1200, "height": 630})
    page.goto("http://localhost:8765/")
    page.wait_for_timeout(2500)
    page.add_style_tag(
        content=".stats,.scroll-cue,.nav,.cta{display:none!important}"
        ".hero{min-height:630px!important;padding:70px 0 50px!important}"
        ".hero .wrap{width:1040px!important}"
    )
    page.wait_for_timeout(600)
    page.screenshot(path=str(OUT), type="jpeg", quality=88)
    browser.close()
print("wrote", OUT)
