#!/usr/bin/env python3
"""
Open the built app in a real browser at iPhone size, in light and dark, and
fail if anything is wrong. Run after build.py (needs site/data/).

For every restaurant page and the "All restaurants" page it checks:
  * no JavaScript errors or console errors
  * nothing wider than the screen (no sideways scrolling)
  * the list shows items
the same for each city page in cities.json (every place shown and opened), then
it switches UK -> city (search, coeliac card, reload) -> UK; Berlin on a
Sunday evening (open today, near me, saving); the staff card, German card and
offline header; accessibility (Larger Text, 44pt taps, contrast, VoiceOver
labels); the first visit; search staying above the keyboard; and on one
restaurant it taps through: opening an item, the Show staff card, a status
button and saving a favourite.

Usage:
  pip install -r tools/requirements-dev.txt && python -m playwright install chromium
  python tools/ui_check.py [--shots DIR]   # --shots saves a screenshot of each page
"""
import argparse
import functools
import json
import math
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

SITE = Path(__file__).resolve().parent.parent / "site"
IPHONE = {"viewport": {"width": 393, "height": 852}, "device_scale_factor": 3, "is_mobile": True, "has_touch": True}
# Berlin row tags by who makes the claim (cities.json "claim"; "place-part" uses the place's own claimLabel)
CLAIM_TAGS = {"place-all": "Says all gluten free", "list-all": "Listed as all gluten free", "separate": "Separate kitchen"}
# visible buttons in the header and lists (and place links) smaller than Apple's 44pt minimum
TAPS_JS = """() => {
    const out = [];
    for (const el of document.querySelectorAll('.top button, main button, .place-links a')) {
        const r = el.getBoundingClientRect();
        if (!r.width || el.closest('[hidden]') || getComputedStyle(el).visibility === 'hidden') continue;
        if (r.height < 43.5 || r.width < 43.5) out.push((el.id || el.className || el.tagName) + ' ' + JSON.stringify(el.textContent.trim().slice(0, 20)) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
    }
    return [...new Set(out)].slice(0, 8);
}"""
# lowest text contrast among the matching elements, against the page background (opacity included)
CONTRAST_JS = """(sel) => {
    const rgb = (s) => s.match(/[\\d.]+/g).map(Number);
    const lum = ([r, g, b]) => [r, g, b].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
        .reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0);
    let worst = 21;
    for (const el of document.querySelectorAll(sel)) {
        let op = 1;
        for (let e = el; e; e = e.parentElement) op *= parseFloat(getComputedStyle(e).opacity);
        const bg = rgb(getComputedStyle(document.body).backgroundColor), fg = rgb(getComputedStyle(el).color);
        const mix = fg.slice(0, 3).map((v, i) => v * op * (fg[3] ?? 1) + bg[i] * (1 - op * (fg[3] ?? 1)));
        const [a, b] = [lum(mix), lum(bg)].sort((x, y) => y - x);
        worst = Math.min(worst, (a + 0.05) / (b + 0.05));
    }
    return worst;
}"""
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
        if page.locator("#cityCard").is_visible():
            problems.append(f"{cid}: the coeliac card button still shows while searching")
        page.locator("#q").fill("")  # the card button comes back once the search is cleared
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

        # Berlin on a Sunday evening at Alexanderplatz: open today, nearest first, saving a place
        alex = {"latitude": 52.5219, "longitude": 13.4132}
        ctx = browser.new_context(color_scheme="light", geolocation=alex, permissions=["geolocation"], **IPHONE)
        page = ctx.new_page()
        page.clock.set_fixed_time("2026-11-01T19:00:00+01:00")  # Sunday 1 November, 19:00 in Berlin
        page.goto(base + f"#{cid}")
        page.wait_for_selector("#cityList .row")
        shown = lambda: [n.split("\n")[0].strip().lstrip("★").strip() for n in page.locator("#cityList .row .nm").all_inner_texts()]
        page.locator('#chips [data-f="open"]').click()
        want = sorted(pl["name"] for pl in cities[cid]["places"] if any((l.get("hours") or [""] * 7)[6] for l in pl["locations"]))
        if sorted(shown()) != want:
            problems.append(f"{cid} open today (Sunday): shows {sorted(shown())}, expected {want}")
        page.locator('#chips [data-f="all"]').click()
        page.locator("#chips [data-near]").click()
        page.wait_for_timeout(500)
        dist = lambda l: math.hypot((l["lat"] - alex["latitude"]) * 111.2, (l["lon"] - alex["longitude"]) * 111.2 * math.cos(math.radians(52.5)))
        nearest = sorted(cities[cid]["places"], key=lambda pl: min(dist(l) for l in pl["locations"]))
        if shown()[:3] != [pl["name"] for pl in nearest[:3]]:
            problems.append(f"{cid} near me: starts {shown()[:3]}, expected {[pl['name'] for pl in nearest[:3]]}")
        page.locator("#chips [data-near]").click()
        page.locator("#q").fill("Sonntag")  # a street name isn't a day: Sonntagstraße shouldn't match
        if "Soul Kitchen House" in shown():
            problems.append(f"{cid}: searching 'Sonntag' finds Soul Kitchen House by its street name")
        page.locator("#q").fill("")
        first = page.locator("#cityList .row").first
        first.locator("summary").click()
        first.locator(".fav-btn").click()
        page.reload()
        page.wait_for_selector("#cityList .row")
        page.evaluate("window.scrollTo(0, 0)")  # the reload keeps the scroll position, with the header folded away
        page.wait_for_selector(".top:not(.collapsed)")
        page.locator('#chips [data-f="fav"]').click()
        if page.locator("#cityList .row").count() != 1:
            problems.append(f"{cid}: after saving one place and reloading, Saved shows {page.locator('#cityList .row').count()}")
        print(f"{cid}: open on Sunday {len(want)}, nearest to Alexanderplatz {shown()[:1] and nearest[0]['name']}, saving works")
        ctx.close()

        # staff card wording, the German card, and saying when it's offline
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        page.goto(base + "#starbucks-uk")
        page.wait_for_selector("#list .row")
        sb = json.loads((SITE / "data" / "r" / "starbucks-uk.json").read_text(encoding="utf-8"))
        for order, must in (("except", "Any other milk is fine"), ("swap", "instead of")):
            item = next(i for i in sb["items"] if i["order"] == order)
            page.locator("#q").fill(item["name"])
            row = page.locator("#list .row", has=page.locator(".nm", has_text=item["name"])).first
            row.locator("summary").click()
            row.locator(".staff-btn").click()
            page.wait_for_selector("#staff[open]")
            said = page.locator("#staff .staff-order").inner_text()
            if must not in said or said.count(",") > 1:
                problems.append(f"staff card for {item['name']} ({order}): {said!r}")
            page.locator("#staff .link-btn").click()
        page.locator("#q").fill("")
        de = json.loads((SITE / "phrases.json").read_text(encoding="utf-8"))["de"]
        if not any("Fritteuse" in c["text"] for c in de["card"]):
            problems.append("German card has no line about a shared fryer")
        page.evaluate("navigator.serviceWorker.ready")
        page.reload()  # now controlled by the service worker, which keeps the saved copy
        page.wait_for_selector("#list .row")
        page.wait_for_timeout(500)
        ctx.set_offline(True)
        page.reload()
        page.wait_for_selector("#list .row")
        page.wait_for_timeout(5000)  # the service worker waits up to 4s for the network before using the saved copy
        if "offline" not in page.locator("#guideLine").inner_text().lower():
            problems.append(f"offline: the header doesn't say so ({page.locator('#guideLine').inner_text()!r})")
        print(f"staff card and offline: header {page.locator('#guideLine').inner_text()!r}")
        ctx.close()

        # accessibility: Larger Text, contrast, tap targets, VoiceOver labels
        for url, rows in (("#starbucks-uk", "#list .row"), (f"#{cid}", "#cityList .row")):
            ctx = browser.new_context(color_scheme="light", **IPHONE)
            page = ctx.new_page()
            page.goto(base + url)
            page.wait_for_selector(rows)
            page.locator(rows).first.locator("summary").click()
            if url == "#starbucks-uk":
                page.locator('#status [data-k="straight"]').click()  # the other two buttons are now unselected
            small = page.evaluate(TAPS_JS)
            problems += [f"{url}: tap target too small: {s}" for s in small]
            if url == "#starbucks-uk":
                ratio = page.evaluate(CONTRAST_JS, '#status button[aria-pressed="false"]')
                if ratio < 4.5:
                    problems.append(f"{url}: unselected status buttons have contrast {ratio:.2f}:1, under 4.5:1")
                label = page.locator("#pickBtn").get_attribute("aria-label") or ""
                if "Starbucks" not in label:
                    problems.append(f"{url}: the title button's VoiceOver label {label!r} doesn't say which restaurant")
                if page.locator(".milk.no").count() and "not" not in page.locator(".milk.no").first.text_content():
                    problems.append(f"{url}: a crossed-out milk isn't read as 'not' by VoiceOver")
            before = page.evaluate(f"parseFloat(getComputedStyle(document.querySelector('{rows} .nm')).fontSize)")
            page.add_style_tag(content="html { font-size: 22px !important; }")  # iPhone Larger Text
            page.wait_for_timeout(300)
            after = page.evaluate(f"parseFloat(getComputedStyle(document.querySelector('{rows} .nm')).fontSize)")
            if after <= before:
                problems.append(f"{url}: text doesn't grow with Larger Text ({before}px -> {after}px)")
            problems += [f"{url} with Larger Text: too wide: {w}" for w in page.evaluate(WIDE_JS)]
            print(f"accessibility {url}: {len(small)} small tap targets, text {before}px -> {after}px with Larger Text")
            ctx.close()

        # first visit: no "what changed" banner (nothing has changed for a new user), and the chooser offers Berlin
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        page.goto(base)
        page.wait_for_selector("#picker[open]")
        if page.locator("#news").is_visible():
            problems.append("first visit: the 'what changed' banner shows for a new user")
        page.locator(f'#pickList [data-region="{cid}"]').click()
        page.wait_for_selector("#cityList .row")
        if page.locator("#picker[open]").count():
            problems.append("first visit: choosing Berlin left the chooser open")
        page.locator("#pickBtn").click()
        page.wait_for_selector("#picker[open]")
        if page.locator(f'#pickList [data-region="{cid}"]').get_attribute("aria-pressed") != "true":
            problems.append("from Berlin, the chooser doesn't show Berlin as chosen")
        page.locator(f"#pickList [data-r=\"{ids[0]}\"]").click()
        page.wait_for_selector("#list .row")
        # wording: the guides do call some (avoided) items gluten free, so don't say they never use the words
        if "don't claim their food is gluten free" in page.locator("#certText").inner_text():
            problems.append("certified note says the restaurants don't claim their food is gluten free")
        page.locator("#openWarnings").click()
        page.wait_for_selector("#warnings[open]")
        if "none of these guides use" in page.locator("#warnBody").inner_text():
            problems.append("warnings intro says none of the guides use the words gluten free")
        print("first visit: chooser with Berlin, no changes banner; wording checked")
        ctx.close()

        # search: the first result sits above the iPhone keyboard (about 340pt tall), and a ruled-out milk is explained
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        for url, query, rows in ((f"#{ids[0]}", "a", "#list .row"), ("#pret-uk", "fruit", "#list .row"), (f"#{cid}", "café", "#cityList .row")):
            page.goto(base + url)
            page.wait_for_selector(rows)
            page.locator("#q").fill(query)
            page.wait_for_timeout(300)
            top = page.locator(rows).first.bounding_box()["y"] if page.locator(rows).count() else None
            if top is None or top > IPHONE["viewport"]["height"] - 340 - 50:
                problems.append(f"search {query!r} on {url}: first result at y={top}, hidden behind the keyboard")
        page.goto(base + "#starbucks-uk")
        page.wait_for_selector("#list .row")
        page.locator("#q").fill("oat milk latte")
        page.wait_for_timeout(300)
        note = page.locator("#searchNote")
        if not note.is_visible() or "Oat milk" not in note.inner_text():
            problems.append("search 'oat milk latte': no note explaining oat milk")
        if not page.locator("#list .row").count():
            problems.append("search 'oat milk latte': no lattes listed")
        print(f"search: results above the keyboard; 'oat milk latte' -> {page.locator('#list .row').count()} rows")
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
