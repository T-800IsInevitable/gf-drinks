#!/usr/bin/env python3
"""
Open the built app in a real browser at iPhone size, in light and dark, and
fail if anything is wrong. Run after build.py (needs site/data/).

For every restaurant page and the "All restaurants" page it checks:
  * no JavaScript errors or console errors
  * nothing wider than the screen (no sideways scrolling)
  * the list shows items
the same for each city page in cities.json (every place shown and opened), then
it switches UK -> city (search, coeliac card, reload) -> UK, and on one
restaurant it taps through: opening an item, the Show staff card, a status
button and saving a favourite.

Usage:
  pip install -r tools/requirements-dev.txt && python -m playwright install chromium
  python tools/ui_check.py [--shots DIR]   # --shots saves a screenshot of each page
"""
import argparse
import functools
import json
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

SITE = Path(__file__).resolve().parent.parent / "site"
IPHONE = {"viewport": {"width": 393, "height": 852}, "device_scale_factor": 3, "is_mobile": True, "has_touch": True}
# Berlin row tags by who makes the claim (cities.json "claim"; "place-part" uses the place's own claimLabel)
CLAIM_TAGS = {"place-all": "Says all gluten free", "list-all": "Listed as all gluten free", "separate": "Separate kitchen"}
# anything wider than the screen (sideways scrolling); the chip row scrolls sideways on purpose
WIDE_JS = """() => {
    const w = document.documentElement.clientWidth, out = [];
    if (document.documentElement.scrollWidth > w + 1) out.push('page ' + document.documentElement.scrollWidth + 'px wide');
    for (const el of document.querySelectorAll('main *, .top *')) {
        const r = el.getBoundingClientRect();
        if (r.width && r.right > w + 1 && !el.closest('.chips') && getComputedStyle(el).visibility !== 'hidden')
            out.push(el.tagName.toLowerCase() + '.' + el.className + ' ends at ' + Math.round(r.right) + 'px');
    }
    return out.slice(0, 5);
}"""


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(SITE)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", type=Path, help="save a screenshot of each page here")
    args = ap.parse_args()
    index = json.loads((SITE / "data" / "restaurants.json").read_text(encoding="utf-8"))
    ids = [r["id"] for r in index["restaurants"]]
    httpd, base = serve()
    problems = []
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for scheme in ("light", "dark"):
            for rid in [None] + ids:
                where = f"{rid or 'all restaurants'} ({scheme})"
                ctx = browser.new_context(color_scheme=scheme, **IPHONE)
                if rid is None:  # skip the first-visit restaurant picker
                    ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda e, errors=errors: errors.append(f"page error: {e}"))
                page.on("console", lambda m, errors=errors: errors.append(f"console {m.type}: {m.text}") if m.type in ("error", "warning") else None)
                page.goto(base + (f"#{rid}" if rid else ""))
                page.wait_for_selector("#list .row, #list .empty", timeout=15000)
                page.wait_for_timeout(300)
                rows = page.locator("#list .row").count()
                wide = page.evaluate(WIDE_JS)
                problems += [f"{where}: {e}" for e in errors]
                problems += [f"{where}: too wide: {w}" for w in wide]
                if not rows:
                    problems.append(f"{where}: no items listed")
                if args.shots:
                    page.screenshot(path=str(args.shots / f"{rid or 'all'}-{scheme}.png"))
                print(f"{where}: {rows} rows, {len(errors)} errors, {len(wide)} too wide")
                ctx.close()

        # the Berlin page, in light and dark, then switching to it and back
        cities = json.loads((SITE / "cities.json").read_text(encoding="utf-8"))
        for scheme in ("light", "dark"):
            for cid, c in cities.items():
                where = f"{cid} ({scheme})"
                ctx = browser.new_context(color_scheme=scheme, **IPHONE)
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda e, errors=errors: errors.append(f"page error: {e}"))
                page.on("console", lambda m, errors=errors: errors.append(f"console {m.type}: {m.text}") if m.type in ("error", "warning") else None)
                page.goto(base + f"#{cid}")
                page.wait_for_selector("#cityList .row", timeout=15000)
                for d in page.locator("#cityList details").all():  # open every place so its details are checked too
                    d.evaluate("el => el.open = true")
                page.wait_for_timeout(200)
                rows = page.locator("#cityList .row").count()
                for i, pl in enumerate(c["places"]):  # each row says who claims what, and shows its warning without opening
                    summary = page.locator("#cityList .row summary").nth(i)
                    text = summary.inner_text()
                    tag = summary.locator(".tag")
                    want = pl.get("claimLabel") or CLAIM_TAGS[pl["claim"]]
                    if want not in tag.inner_text():
                        problems.append(f"{where}: {pl['name']} tag is {tag.inner_text()!r}, expected {want!r}")
                    green = "t-asis" in tag.get_attribute("class")
                    if green != (pl["claim"] == "place-all" and not pl.get("caution")):
                        problems.append(f"{where}: {pl['name']} tag is {'green' if green else 'not green'}")
                    if pl.get("caution") and pl["flag"] not in text:
                        problems.append(f"{where}: {pl['name']} row doesn't show {pl['flag']!r}")
                    if pl["status"] != "confirmed" and "Opening not confirmed" not in text:
                        problems.append(f"{where}: {pl['name']} row doesn't say its opening isn't confirmed")
                wide = page.evaluate(WIDE_JS)
                problems += [f"{where}: {e}" for e in errors]
                problems += [f"{where}: too wide: {w}" for w in wide]
                if rows != len(c["places"]):
                    problems.append(f"{where}: {rows} places shown, expected {len(c['places'])}")
                if not page.locator("#ukView").is_hidden():
                    problems.append(f"{where}: the UK menus are showing too")
                if args.shots:
                    page.screenshot(path=str(args.shots / f"{cid}-{scheme}.png"), full_page=True)
                print(f"{where}: {rows} places, {len(errors)} errors, {len(wide)} too wide")
                ctx.close()
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
        page = ctx.new_page()
        page.goto(base)
        page.wait_for_selector("#list .row")
        cid = next(iter(cities))
        page.locator(f'#region [data-region="{cid}"]').click()
        page.wait_for_selector("#cityList .row")
        page.locator("#q").fill(cities[cid]["places"][0]["name"])
        if page.locator("#cityList .row").count() < 1:
            problems.append(f"{cid}: searching for the first place found nothing")
        page.locator("#cityCard").click()
        page.wait_for_selector("#gfcard[open]")
        page.locator("#gfcard .link-btn").click()
        page.reload()
        page.wait_for_selector("#cityList .row")  # the choice is remembered
        page.locator('#region [data-region="uk"]').click()
        page.wait_for_selector("#list .row")
        if not page.locator("#cityView").is_hidden():
            problems.append(f"switching back to UK left {cid} showing")
        print(f"switch: UK -> {cid} (search, card, reload) -> UK")
        ctx.close()

        # tap through one restaurant
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
        page.goto(base + f"#{ids[0]}")
        page.wait_for_selector("#list .row")
        first = page.locator("#list .row").first
        name = first.locator(".nm").inner_text().split("\n")[0].strip()
        first.locator("summary").click()
        first.locator(".staff-btn").click()
        page.wait_for_selector("#staff[open]")
        shown = page.locator("#staff .staff-name").inner_text().strip()
        if shown != name:
            problems.append(f"Show staff: card shows {shown!r}, expected {name!r}")
        if args.shots:
            page.screenshot(path=str(args.shots / "staff-card.png"))
        page.locator("#staff .link-btn").click()
        first.locator(".fav-btn").click()
        if "Saved" not in first.locator(".fav-btn").inner_text():
            problems.append("Save: the button didn't change to Saved")
        before = page.locator("#list .row").count()
        page.evaluate("window.scrollTo(0, 0)")  # scrolling down folds the filters away; scroll up as a person would
        page.wait_for_selector(".top:not(.collapsed)")
        page.wait_for_timeout(300)
        page.locator('#status [data-k="change"]').click()
        after = page.locator("#list .row").count()
        if after > before:
            problems.append(f"Status button: list grew from {before} to {after} rows")
        page.reload()
        page.wait_for_selector("#list .row, #list .empty")
        if page.locator('#status [data-k="change"]').get_attribute("aria-pressed") != "true":
            problems.append("Status button choice wasn't remembered after reloading")
        problems += [f"tap-through: {e}" for e in errors]
        print(f"tap-through on {ids[0]}: staff card for {name!r}, status filter {before} -> {after} rows")
        ctx.close()
        browser.close()
    httpd.shutdown()

    if problems:
        print("\nUI CHECK FAILED:")
        for pr in problems:
            print(" -", pr)
        sys.exit(1)
    print("UI checks passed")


if __name__ == "__main__":
    main()
