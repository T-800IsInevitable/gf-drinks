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
offline header; the tags under item names, even status buttons, the lighter header, Help in sections, the
cross-contact-first warnings, the chooser's order and first-run welcome, the photo button, the folded Avoid
list and amber used only for items needing a change (contrast in all five themes); accessibility (Larger Text, 44pt taps, contrast, VoiceOver
labels); the first visit; search staying above the keyboard; and on one
restaurant it taps through: opening an item, the Show staff card, a status
button and saving a favourite.

Usage:
  pip install -r tools/requirements-dev.txt && python -m playwright install chromium
  python tools/ui_check.py [--shots DIR]   # --shots saves a screenshot of each page
"""
import argparse
import base64
import functools
import hashlib
import json
import math
import re
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
# each list row: its name, the small line under it, its tag, whether that tag is green, and whether it has a staff card
ROWS_JS = """() => [...document.querySelectorAll('#list details.row')].map((d) => {
    const nm = d.querySelector('.nm'), tag = d.querySelector('summary .tag');
    return { name: [...nm.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim(),
             small: (nm.querySelector('small') || { textContent: '' }).textContent, tag: tag.textContent,
             green: tag.classList.contains('t-asis') || tag.classList.contains('t-any'),
             staff: !!d.querySelector('.staff-btn'), detail: d.querySelector('.detail').textContent };
})"""
# where the menu starts on the first screen, how many items show there, and the height of any out-of-date banner
# (plus the gap after it), which is kept in full and so may push the menu down
FIRST_SCREEN_JS = """(sel) => {
    const list = document.querySelector(sel), first = list.firstElementChild;
    const stale = [...document.querySelectorAll('#stale, #cityStale')].find((e) => !e.hidden && e.offsetParent);
    return { top: Math.round(first.getBoundingClientRect().top),
             rows: [...list.querySelectorAll('.row')].filter((r) => r.getBoundingClientRect().top < innerHeight).length,
             stale: stale ? Math.round(stale.getBoundingClientRect().height) + 18 : 0 };
}"""
# sentences in the app's own words that call something gluten free without saying whose claim it is. Skipped:
# quotes, translations, other languages, the coeliac card, and item and place names (the restaurants' own words)
WORDING_JS = r"""() => {
    const skip = 'blockquote, cite, [data-quote], .star, .staff-name, .chg-list b, #favAlert b, #cardBody, [lang]:not([lang^="en"]), script, style';
    const block = 'p, li, div, h1, h2, h3, h4, summary, dt, dd, button, label, small, span.po-main > span';
    const whose = /\b(says?|said|call(s|ed)?|names?|listed|lists|labell?ed|claims?|claimed|certified|accredited|own words?|marks?|marked)\b/i;
    const texts = new Map();
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
        const el = n.parentElement;
        if (!el || el.closest(skip) || el.matches('.nm')) continue;  // a row's own text is the item's or place's name
        const b = el.closest(block) || el;
        texts.set(b, (texts.get(b) || '') + n.textContent);
    }
    const out = [];
    for (const t of texts.values()) {
        for (const s of t.replace(/\s+/g, ' ').trim().split(/(?<=[.!;])\s+/)) {
            const rest = s.replace(/gluten[ -]free (oats|wheat starch)/gi, '');  // kinds of ingredient, not claims
            if (/gluten[ -]free/i.test(rest) && !/\?$/.test(s) && !whose.test(rest)) out.push(s);
        }
    }
    return out;
}"""


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")  # 1x1 photo


class FakeGitHub:
    """Just enough of GitHub's API for Add a menu: the Git Data calls an upload makes, kept in memory.
    fail_blob=n drops the signal on the nth file; lose_answer moves the branch but the answer never arrives;
    status=(code, headers, message) answers every call with that error."""

    def __init__(self, fail_blob=None, lose_answer=False, status=None):
        self.refs = {"main": "c0"}
        self.commits = {"c0": {"tree": "t0", "parents": [], "message": ""}}
        self.trees = {"t0": {}}
        self.blobs = {}
        self.fail_blob, self.lose_answer, self.status = fail_blob, lose_answer, status
        self.blob_calls = 0
        self.other = []  # calls an upload shouldn't make, such as the old one-file-at-a-time /contents PUTs

    def commits_on(self, branch):
        out, sha = [], self.refs.get(branch)
        while sha and sha != "c0":
            out.append(sha)
            sha = (self.commits[sha]["parents"] or [None])[0]
        return out

    def files(self, branch):
        sha = self.refs.get(branch)
        return sorted(self.trees[self.commits[sha]["tree"]]) if sha else []

    def handle(self, route):
        req = route.request

        def reply(code, body=None, headers=None):
            route.fulfill(status=code, content_type="application/json", body=json.dumps(body or {}),
                          headers={"access-control-allow-origin": "*", "access-control-expose-headers": "x-ratelimit-remaining", **(headers or {})})

        def lose():
            lost, self.lose_answer = self.lose_answer, False
            return lost

        if self.status:
            code, headers, msg = self.status
            return reply(code, {"message": msg}, headers)
        path = req.url.split("/repos/T-800IsInevitable/gf-drinks", 1)[-1]
        body = json.loads(req.post_data or "{}") if req.method in ("POST", "PATCH") else {}
        sha_of = lambda s: hashlib.sha1(s.encode()).hexdigest()[:12]
        m = re.fullmatch(r"/git/ref/heads/(\w+)", path)
        if req.method == "GET" and m:
            return reply(200, {"object": {"sha": self.refs[m[1]]}}) if m[1] in self.refs else reply(404, {"message": "Not Found"})
        m = re.fullmatch(r"/git/commits/(\w+)", path)
        if req.method == "GET" and m:
            return reply(200, {"tree": {"sha": self.commits[m[1]]["tree"]}})
        if req.method == "POST" and path == "/git/blobs":
            self.blob_calls += 1
            if self.blob_calls == self.fail_blob:
                return route.abort()
            sha = sha_of(body["content"])
            self.blobs[sha] = body["content"]
            return reply(201, {"sha": sha})
        if req.method == "POST" and path == "/git/trees":
            tree = {**self.trees[body["base_tree"]], **{e["path"]: e["sha"] for e in body["tree"]}}
            sha = sha_of(json.dumps(sorted(tree.items())))  # the same files make the same folder, as in git
            self.trees[sha] = tree
            return reply(201, {"sha": sha})
        if req.method == "POST" and path == "/git/commits":
            sha = sha_of(json.dumps(body) + str(len(self.commits)))
            self.commits[sha] = body
            return reply(201, {"sha": sha})
        if req.method == "POST" and path == "/git/refs":
            name = body["ref"].removeprefix("refs/heads/")
            if name in self.refs:
                return reply(422, {"message": "Reference already exists"})
            self.refs[name] = body["sha"]
            return route.abort() if lose() else reply(201, {"object": {"sha": body["sha"]}})
        m = re.fullmatch(r"/git/refs/heads/(\w+)", path)
        if req.method == "PATCH" and m:
            if self.commits[body["sha"]]["parents"] != [self.refs.get(m[1])]:
                return reply(422, {"message": "Update is not a fast forward"})
            self.refs[m[1]] = body["sha"]
            return route.abort() if lose() else reply(200, {"object": {"sha": body["sha"]}})
        self.other.append(f"{req.method} {path}")
        return reply(404, {"message": "Not Found"})


def upload_checks(browser, base, engine):
    """Add a menu with the owner's key, against FakeGitHub. Each upload is one commit on the uploads branch (never
    main), photos are re-saved as JPEG, a dropped signal leaves nothing behind, retrying after a lost answer makes
    no second copy, a rate limit keeps the key, and an expired key is removed with advice that says so."""
    problems = []
    photo_and_pdf = [{"name": "page.png", "mimeType": "image/png", "buffer": PNG},
                     {"name": "menu.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4"}]

    def session(fake):
        # no service worker: in WebKit, requests from a page it controls get past page.route to the real GitHub
        ctx = browser.new_context(color_scheme="light", service_workers="block", **IPHONE)
        ctx.add_init_script("localStorage.setItem('gf-github-key', 'k')")
        page = ctx.new_page()
        page.route("https://api.github.com/**", fake.handle)
        page.goto(base + "#knoops-uk")
        page.wait_for_selector("#list .row")
        page.locator("#infoBtn").click()
        page.locator("#openUpload").click()
        page.wait_for_selector("#upload[open]")
        return ctx, page

    def upload(page, name="Test Cafe", files=photo_and_pdf):
        if not page.locator("#upName").input_value():
            page.locator("#upName").fill(name)
            page.locator("#upArea").fill("Berlin")
            page.set_input_files("#upFiles", files=files)
        page.locator("#upSend").click()
        # not wait_for_function: it needs eval, which the app's CSP blocks. "attached": an expired key hides the button
        page.wait_for_selector("#upSend:not([disabled])", state="attached")
        return page.locator("#upStatus").inner_text()

    # two uploads in a row: the first starts the uploads branch from main, the second builds on it
    fake = FakeGitHub()
    ctx, page = session(fake)
    page.locator("#upName").fill("Test Cafe")  # filled by hand to look at the previews before sending
    page.locator("#upArea").fill("Berlin")
    page.set_input_files("#upFiles", files=photo_and_pdf)
    if page.locator("#upThumbs .thumb").count() != 2:
        problems.append(f"{engine} upload: {page.locator('#upThumbs .thumb').count()} previews for 2 files")
    said = [upload(page), upload(page, "Second Cafe", photo_and_pdf[1:])]
    if not page.locator("#upStatus.done").count() or page.locator("#upThumbs .thumb").count():
        problems.append(f"{engine} upload: after sending, the status should say it's done and the previews should clear")
    folders = sorted({f.split("/")[1] for f in fake.files("uploads")})
    if not all(s.startswith("Uploaded") for s in said):
        problems.append(f"{engine} upload: {said}")
    if len(fake.commits_on("uploads")) != 2 or fake.refs["main"] != "c0" or fake.other:
        problems.append(f"{engine} upload: expected one commit per upload on uploads and main untouched; "
                        f"{len(fake.commits_on('uploads'))} commits, main {fake.refs['main']}, other calls {fake.other}")
    first = [f for f in fake.files("uploads") if "test-cafe" in f]
    if [f.split("/")[-1] for f in first] != ["menu-2.pdf", "page-1.jpg", "upload.json"] or len(folders) != 2:
        problems.append(f"{engine} upload: the folders hold {fake.files('uploads')}")
    jpg = next((fake.blobs[fake.trees[fake.commits[fake.refs['uploads']]['tree']][f]] for f in first if f.endswith(".jpg")), "")
    if not base64.b64decode(jpg or "").startswith(b"\xff\xd8"):
        problems.append(f"{engine} upload: the photo wasn't re-saved as a JPEG (blocked by the content security policy?)")
    ctx.close()

    # the signal drops on the second file: nothing arrives, the message says retrying is safe, and the retry works
    fake = FakeGitHub(fail_blob=2)
    ctx, page = session(fake)
    said = upload(page)
    if "uploads" in fake.refs or "safe" not in said:
        problems.append(f"{engine} dropped signal: branch {fake.refs.get('uploads')}, said {said!r}")
    said = upload(page)
    if not said.startswith("Uploaded") or len(fake.commits_on("uploads")) != 1:
        problems.append(f"{engine} retry after dropped signal: said {said!r}, {len(fake.commits_on('uploads'))} commits")
    ctx.close()

    # the upload arrives but its answer is lost: trying again mustn't make a second copy
    fake = FakeGitHub(lose_answer=True)
    ctx, page = session(fake)
    said = [upload(page), upload(page)]
    if len(fake.commits_on("uploads")) != 1 or not said[1].startswith("Uploaded"):
        problems.append(f"{engine} lost answer: {len(fake.commits_on('uploads'))} commits after retrying, said {said}")
    ctx.close()

    # GitHub's rate limit isn't the key's fault (403 with no requests left): the key stays
    fake = FakeGitHub(status=(403, {"x-ratelimit-remaining": "0"}, "API rate limit exceeded"))
    ctx, page = session(fake)
    said = upload(page)
    if "limiting" not in said or not page.evaluate("localStorage.getItem('gf-github-key')"):
        problems.append(f"{engine} rate limit: said {said!r}, key {'kept' if page.evaluate('localStorage.getItem(`gf-github-key`)') else 'removed'}")
    ctx.close()

    # an expired or deleted key: removed, with advice that says so rather than blaming the signal
    fake = FakeGitHub(status=(401, {}, "Bad credentials"))
    ctx, page = session(fake)
    said = upload(page)
    if "no longer works" not in said or "signal" in said or page.evaluate("localStorage.getItem('gf-github-key')") or page.locator("#keySetup").is_hidden():
        problems.append(f"{engine} expired key: said {said!r}, and the key should be removed with its steps reopened")
    ctx.close()
    print(f"{engine} uploads: one commit each on uploads, JPEG photos, safe retries, rate limit keeps the key, expired key removed")
    return problems


def webkit_checks(p, base, ids, cid):
    """The iPhone runs WebKit: every page loads without errors (a content security policy violation is one),
    the sheets open and close, and uploads work, in Playwright's WebKit."""
    try:
        browser = p.webkit.launch()
    except Exception as e:
        return [f"WebKit isn't installed for Playwright (run: python -m playwright install webkit): {e}"]
    problems = []
    for url in [""] + [f"#{r}" for r in ids] + [f"#{cid}"]:
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        if not url:
            ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e, errors=errors: errors.append(f"page error: {e}"))
        page.on("console", lambda m, errors=errors: errors.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
        page.goto(base + url)
        page.wait_for_selector("#cityList .row" if url == f"#{cid}" else "#list .row", timeout=15000)
        page.wait_for_timeout(300)
        if url == f"#{ids[0]}":
            row = page.locator("#list .row").first
            row.locator("summary").click()
            row.locator(".staff-btn").click()
            page.wait_for_selector("#staff[open]")
            page.locator("#staff .link-btn").click()
            page.locator("#infoBtn").click()
            page.wait_for_selector("#info[open]")
            page.locator("#info .link-btn").first.click()
            page.wait_for_timeout(300)
            if page.locator("dialog[open]").count():
                problems.append("WebKit: a Done button didn't close its sheet")
        problems += [f"WebKit {url or 'all restaurants'}: {e}" for e in errors]
        ctx.close()
    print(f"WebKit: {len(ids) + 2} pages loaded, sheets open and close")
    problems += upload_checks(browser, base, "WebKit")
    browser.close()
    return problems


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
        if page.locator(".city-intro").is_visible():
            problems.append(f"{cid}: the introduction still shows while searching")
        page.locator("#q").fill("")
        page.locator("#chips [data-card]").click()  # the coeliac card is a chip, so it's on the first screen
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
        # at 19:00 on Sunday, "still open today" means open now or opening later, not already shut for the day
        closes = lambda h: int(re.findall(r"(\d{1,2}):(\d{2})", h)[-1][0]) * 60 + int(re.findall(r"(\d{1,2}):(\d{2})", h)[-1][1]) if h else 0
        sunday = lambda pl: [(l.get("hours") or [""] * 7)[6] for l in pl["locations"]]
        for pl in cities[cid]["places"]:
            row = page.locator("#cityList .row", has=page.locator(".nm", has_text=pl["name"])).first.inner_text()
            hrs = [h for h in sunday(pl) if h]
            if hrs and max(closes(h) for h in hrs) > 19 * 60 and "Open now" not in row:
                problems.append(f"{cid} Sunday 19:00: {pl['name']} ({hrs}) doesn't say Open now")
            if hrs and max(closes(h) for h in hrs) <= 19 * 60 and "Closed now" not in row:
                problems.append(f"{cid} Sunday 19:00: {pl['name']} ({hrs}) doesn't say Closed now")
        page.locator('#chips [data-f="open"]').click()
        want = sorted(pl["name"] for pl in cities[cid]["places"] if any(closes(h) > 19 * 60 for h in sunday(pl)))
        if sorted(shown()) != want:
            problems.append(f"{cid} still open today (Sunday 19:00): shows {sorted(shown())}, expected {want}")
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

        # final review: allowed-milk search, the app's own doubts, branch hours, resuming, filters, staff card detail
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        page.goto(base + "#starbucks-uk")
        page.wait_for_selector("#list .row")
        for q in ("soya latte", "almond milk latte", "skimmed latte"):
            page.locator("#q").fill(q)
            if not page.locator("#list .row").count():
                problems.append(f"starbucks-uk: searching {q!r} finds nothing")
        page.goto(base + "#knoops-uk")
        page.wait_for_selector("#list .row")
        page.locator("#q").fill("cannoli")
        if page.locator("#list .row").count():
            problems.append("knoops-uk: cannoli still listed with no gluten ingredients despite the app's caution")
        if "Check in store" not in page.locator("#avoid").inner_text():
            problems.append("knoops-uk: cannoli aren't on the Avoid list marked 'Check in store'")
        page.locator("#q").fill("")
        page.goto(base + "#pho-uk")
        page.wait_for_selector("#list .row")
        page.locator("#q").fill("chicken")
        row = page.locator("#list .row").nth([r["name"] for r in page.evaluate(ROWS_JS)].index("Chicken"))  # six dishes are just "Chicken"
        row.locator("summary").click()
        row.locator(".staff-btn").click()
        page.wait_for_selector("#staff[open]")
        sec = page.locator("#staff .staff-sec").inner_text().strip() if page.locator("#staff .staff-sec").count() else ""
        if not sec or sec == "Chicken":
            problems.append(f"pho-uk: the staff card for 'Chicken' doesn't say which dish ({sec!r})")
        page.locator("#staff .link-btn").click()
        page.goto(base)
        page.wait_for_selector("#list .row")
        page.locator(f'#pickBtn').click()
        page.locator('#pickList [data-r="all"]').click()
        if page.locator("#cardLaunch").is_visible():
            problems.append("UK all restaurants: shows the German coeliac card button")
        ctx.close()

        ctx = browser.new_context(color_scheme="light", geolocation={"latitude": 52.50936, "longitude": 13.29682}, permissions=["geolocation"], **IPHONE)
        page = ctx.new_page()
        page.clock.set_fixed_time("2026-11-03T15:00:00+01:00")  # Tuesday 15:00, beside Oshione's Suarezstraße branch (shut 14:30)
        page.goto(base + f"#{cid}")
        page.wait_for_selector("#cityList .row")
        page.locator("#chips [data-near]").click()
        page.wait_for_timeout(500)
        osh = page.locator("#cityList .row", has=page.locator(".nm", has_text="Oshione")).first.inner_text()
        if "Open now" in osh:
            problems.append(f"{cid} near me: Oshione says open, but the nearest branch shut at 14:30 ({osh.splitlines()[1]!r})")
        page.locator("#chips [data-near]").click()
        page.locator('#chips [data-f="open"]').click()
        page.evaluate("window.scrollTo(0, 0)")
        top = page.locator("#cityList .row").first.bounding_box()["y"] if page.locator("#cityList .row").count() else 0
        if top > 450:
            problems.append(f"{cid}: after choosing a filter the first result is at y={top:.0f}, below the fold")
        page.locator('#chips [data-f="all"]').click()
        page.clock.set_fixed_time("2026-11-02T13:00:00+01:00")  # Monday 13:00
        page.reload()
        page.wait_for_selector("#cityList .row")
        tap = page.locator("#cityList .row", has=page.locator(".nm", has_text="Tapiocaria")).first.inner_text()
        if "Closed today" in tap:
            problems.append(f"{cid}: Tapiocaria says 'Closed today' on Monday, but its hours for Monday aren't known")
        page.clock.set_fixed_time("2026-11-03T13:00:00+01:00")  # Tuesday 13:00: Prana open until 15:00
        page.reload()
        page.wait_for_selector("#cityList .row")
        pra = page.locator("#cityList .row", has=page.locator(".nm", has_text="Café Prana")).first.inner_text()
        if "Open now" not in pra:
            problems.append(f"{cid}: Café Prana doesn't say open at 13:00 on Tuesday")
        page.clock.set_fixed_time("2026-11-03T16:00:00+01:00")  # back in the app at 16:00: Prana shut at 15:00
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_timeout(800)
        pra = page.locator("#cityList .row", has=page.locator(".nm", has_text="Café Prana")).first.inner_text()
        if "Open now" in pra:
            problems.append(f"{cid}: after resuming at 16:00, Café Prana still says open")
        page.clock.set_fixed_time("2026-11-01T21:30:00+01:00")  # Sunday 21:30: Senza's kitchen closed at 21:00
        page.reload()
        page.wait_for_selector("#cityList .row")
        sen = page.locator("#cityList .row", has=page.locator(".nm", has_text="Trattoria Senza")).first.inner_text()
        if "Open now" in sen:
            problems.append(f"{cid}: Trattoria Senza says open at 21:30, after its kitchen closes")
        print("final review checks: search milks, cannoli, staff card detail, branch hours, resume, kitchen times")
        ctx.close()

        # Add a menu without a key: a way for anyone to send photos, and a real link for the owner's key
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        page.goto(base + "#starbucks-uk")
        page.wait_for_selector("#list .row")
        tips = page.locator("#tips > div")
        if tips.count() != tips.locator("b").count():
            problems.append(f"starbucks-uk: {tips.count() - tips.locator('b').count()} tips have no bold lead-in")
        page.goto(base + "#knoops-uk")
        page.wait_for_selector("#list .row")
        if "latest" not in page.locator("#stale").inner_text():
            problems.append("knoops-uk: the out-of-date banner doesn't say whether a newer guide exists")
        page.locator("#infoBtn").click()
        page.locator("#openUpload").click()
        page.wait_for_selector("#upload[open]")
        if not page.locator("#shareSend").is_visible():
            problems.append("Add a menu: no way to send a menu without the owner's key")
        page.locator("#shareSend").click()
        if "Pick" not in page.locator("#shareStatus").inner_text():
            problems.append("Add a menu: sending with no files gives no guidance")
        if not page.locator('#upload a[href="https://github.com/settings/personal-access-tokens/new"]').count():
            problems.append("Add a menu: the GitHub key address isn't a link")
        print("add a menu: send without a key, key link; tips bold; Knoops banner")
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

        # food safety: a part of a dish or an ingredient listed on its own isn't something to order. No green row
        # may share a name with an Avoid row, and neither kind gets a staff card (Five Guys' sausage was "Hot Dog")
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        for rid in ids:
            built = json.loads((SITE / "data" / "r" / f"{rid}.json").read_text(encoding="utf-8"))
            page.goto(base + f"#{rid}")
            page.wait_for_selector("#list .row")
            rows = page.evaluate(ROWS_JS)
            avoid = {" ".join(a["name"].lower().split()) for a in built["avoid"]}
            for row in rows:
                if row["green"] and " ".join(row["name"].lower().split()) in avoid:
                    problems.append(f"{rid}: {row['name']!r} shows with no gluten ingredients, but an item of the same name is on the Avoid list")
            for i in (i for i in built["items"] if i.get("role")):
                for row in (r for r in rows if r["name"] == i["name"]):
                    if row["staff"]:
                        problems.append(f"{rid}: {i['name']!r} ({i['role']}) has a Show staff card")
                    if "No changes needed" in row["detail"]:
                        problems.append(f"{rid}: {i['name']!r} ({i['role']}) says 'No changes needed', as if it were a dish")
                    if i["role"] == "ingredient" and (row["green"] or row["tag"] != "Ingredient"):
                        problems.append(f"{rid}: ingredient {i['name']!r} is tagged {row['tag']!r}, not 'Ingredient'")
                    if i["role"] == "part" and "Part of a dish" not in row["small"]:
                        problems.append(f"{rid}: {i['name']!r} doesn't say it's part of a dish")
        # the two found by the capability review, named here so they can't pass just by having no role
        page.goto(base + "#five-guys-uk")
        page.wait_for_selector("#list .row")
        sausage = {r["name"]: r for r in page.evaluate(ROWS_JS)}.get("Hot dog sausage")
        if not sausage or sausage["staff"] or "Part of a dish" not in sausage["small"]:
            problems.append(f"five-guys-uk: the sausage isn't listed as 'Hot dog sausage', part of a dish, with no staff card ({sausage})")
        page.goto(base + "#blank-street-uk")
        page.wait_for_selector("#list .row")
        coconut = {r["name"]: r for r in page.evaluate(ROWS_JS)}.get("Coconut Drink")
        if not coconut or coconut["green"] or coconut["tag"] != "Ingredient" or coconut["staff"]:
            problems.append(f"blank-street-uk: Coconut Drink isn't tagged as an ingredient with no staff card ({coconut})")
        print("food safety: no green row named like an Avoid row; parts and ingredients have no staff card")
        ctx.close()

        # wording: the app never calls anything gluten free in its own voice (CLAUDE.md), on any page, sheet or list
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
        page = ctx.new_page()
        found = set()
        for url in [""] + [f"#{rid}" for rid in ids] + [f"#{c}" for c in cities]:
            page.goto(base + url)
            page.wait_for_selector("#cityList .row" if url[1:] in cities else "#list .row")
            if not url:  # the warnings and the chooser are only filled in once opened
                page.locator("#openWarnings").click()
                page.wait_for_selector("#warnings[open]")
                page.keyboard.press("Escape")
                page.locator("#pickBtn").click()
                page.wait_for_selector("#picker[open]")
                page.keyboard.press("Escape")
            found |= set(page.evaluate(WORDING_JS))
        problems += [f"calls something gluten free in the app's own voice: {s!r}" for s in sorted(found)]
        print(f"wording: {len(found)} sentences say gluten free without saying whose claim it is")
        ctx.close()

        # U1, content first: a page's first visit shows its tips and the certified-or-not card in full; after that they
        # fold into one line, the menu starts in the top half of the screen with at least four items showing (an
        # out-of-date banner, kept in full, may push it down by its own height), and every folded word is in the sheet
        half = IPHONE["viewport"]["height"] / 2
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
        page = ctx.new_page()
        found = set()
        norm_ws = lambda s: " ".join(s.split())
        for url in [""] + [f"#{rid}" for rid in ids] + [f"#{c}" for c in cities]:
            where = url[1:] or "all restaurants"
            in_city = url[1:] in cities
            page.goto(base + url)
            page.wait_for_selector("#cityList .row" if in_city else "#list .row")
            if not in_city:
                if not page.locator("#certNote").is_visible() or page.locator("#openStrip").is_visible():
                    problems.append(f"{where}: the first visit doesn't show the full certified-or-not card")
                page.reload()  # the second visit: folded
                page.wait_for_selector("#list .row")
                if page.locator("#certNote").is_visible() or page.locator("#tips").is_visible() or not page.locator("#openStrip").is_visible():
                    problems.append(f"{where}: on a second visit the tips and card don't fold into one line")
            page.wait_for_timeout(300)
            m = page.evaluate(FIRST_SCREEN_JS, "#cityList" if in_city else "#list")
            # and again in a wide font: the iPhone's font isn't the test machine's, so the layout needs room to spare
            wide = page.add_style_tag(content='* { font-family: Verdana, "DejaVu Sans", sans-serif !important; }')
            page.wait_for_timeout(200)
            mw = page.evaluate(FIRST_SCREEN_JS, "#cityList" if in_city else "#list")
            wide.evaluate("el => el.remove()")
            for label, mm in (("", m), (" in a wide font", mw)):
                if mm["top"] > half + mm["stale"] or mm["rows"] < 4:
                    problems.append(f"{where}{label}: the menu starts at {mm['top']}pt with {mm['rows']} items on the first screen "
                                    f"(wanted the top half, {half:.0f}pt{' plus the out-of-date banner' if mm['stale'] else ''}, and 4 or more)")
            found |= set(page.evaluate(WORDING_JS))
            if in_city:
                if not page.locator("#chips [data-card]").count():
                    problems.append(f"{where}: no coeliac card chip")
                page.locator(".city-intro .more summary").last.click()
                if not page.locator("#cityTips").is_visible() or not page.locator("#cityTips > div").count():
                    problems.append(f"{where}: Before you go doesn't open to the tips")
                continue
            built = json.loads((SITE / "data" / "r" / f"{url[1:]}.json").read_text(encoding="utf-8")) if url else None
            strip = page.locator("#openStrip").inner_text()
            if built and built.get("headline") and built["headline"] not in strip:
                problems.append(f"{where}: the folded line {strip!r} doesn't lead with its headline {built['headline']!r}")
            page.locator("#openStrip").click()
            page.wait_for_selector("#warnings[open]")
            sheet = norm_ws(page.locator("#warnBody").inner_text())
            missing = [t for t in (built or {}).get("tips", []) if norm_ws(t) not in sheet]
            if missing or "No gluten ingredients" not in sheet:
                problems.append(f"{where}: the Tips and warnings sheet is missing {missing or 'the certified-or-not wording'}")
            page.keyboard.press("Escape")
        problems += [f"calls something gluten free in the app's own voice (folded pages): {s!r}" for s in sorted(found)]
        # "Got it" folds the card straight away on a first visit
        page.goto(base + f"#{ids[0]}")
        page.wait_for_selector("#list .row")
        page.evaluate("localStorage.removeItem('gf-intro-seen')")  # forget every visit, so the reload is a first visit
        page.reload()
        page.wait_for_selector("#list .row")
        page.locator("#introDone").click()
        if page.locator("#certNote").is_visible() or not page.locator("#openStrip").is_visible():
            problems.append(f"{ids[0]}: Got it doesn't fold the card")
        print(f"content first: pages fold after their first visit, menus start in the top half ({half:.0f}pt), sheet has every tip")
        ctx.close()

        # U14: an item the app decided for itself (the guide wasn't plain) says how, on the item and in the sheet;
        # Help has no separate list of notes
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        shown = 0
        for rid in ids:
            built = json.loads((SITE / "data" / "r" / f"{rid}.json").read_text(encoding="utf-8"))
            noted = [(i, "#list") for i in built["items"] if i.get("decided")] + [(a, "#avoid") for a in built["avoid"] if a.get("decided")]
            if not noted:
                continue
            page.goto(base + f"#{rid}")
            page.wait_for_selector("#list .row")
            for i, where in noted:
                page.locator("#q").fill(i["name"])
                page.wait_for_timeout(200)
                row = page.locator(f"{where} .row", has=page.locator(".nm", has_text=i["name"])).first
                if not row.count():
                    problems.append(f"{rid}: {i['name']!r} (noted) isn't listed")
                    continue
                row.locator("summary").click()
                if norm_ws(i["decided"]) not in norm_ws(row.locator(".detail").inner_text()):
                    problems.append(f"{rid}: {i['name']!r} doesn't say how the app decided it")
                shown += 1
            page.locator("#q").fill("")
            page.evaluate("window.scrollTo(0, 0)")
            page.locator("#openStrip:visible, #openWarnings:visible").first.click()  # folded or not
            page.wait_for_selector("#warnings[open]")
            if "How the app decided some items" not in page.locator("#warnBody").text_content():  # not inner_text: h4s are in capitals
                problems.append(f"{rid}: the sheet doesn't list how the app decided some items")
            page.keyboard.press("Escape")
        page.locator("#infoBtn").click()
        page.wait_for_selector("#info[open]")
        if re.search(r"classified from ingredients|Notes from the last update", page.locator("#info").inner_text()):
            problems.append("Help still has the separate list of reading notes")
        print(f"how items were decided: {shown} items say so on the item and in the sheet; none left in Help")
        ctx.close()

        # U2 and U3: each tag is on its own line under the name and never wraps, and the three status buttons are one even row
        tags_js = """(sel) => [...document.querySelectorAll(sel)].filter((t) => t.offsetParent).map((t) => {
            const nm = t.closest('.nm'), r = t.getBoundingClientRect(), n = nm.getBoundingClientRect();
            const lh = parseFloat(getComputedStyle(t).lineHeight) || 16;
            return { text: t.textContent, lines: Math.round((r.height - 6) / lh), under: t.parentElement === nm && r.top >= n.top + 10, wide: r.right > n.right + 1 };
        })"""
        status_js = """() => [...document.querySelectorAll('#status button')].map((b) => {
            const r = b.getBoundingClientRect(), d = b.querySelector('.dot').getBoundingClientRect(), c = b.querySelector('.cnt').getBoundingClientRect();
            return { h: Math.round(r.height), dot: Math.round(d.top), cnt: Math.round(c.top) };
        })"""
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
        page = ctx.new_page()
        checked_tags = 0
        for url in [""] + [f"#{rid}" for rid in ids]:
            where = url[1:] or "all restaurants"
            page.goto(base + url)
            page.wait_for_selector("#list .row")
            page.evaluate("document.getElementById('avoidWrap').open = true")  # the Avoid list is folded until wanted
            for label, css in (("", None), (" in a wide font", '* { font-family: Verdana, "DejaVu Sans", sans-serif !important; }')):
                style = page.add_style_tag(content=css) if css else None
                page.wait_for_timeout(150)
                found = page.evaluate(tags_js, "#list .tag, #avoid .tag")
                checked_tags += len(found)
                bad = [t for t in found if t["lines"] > 1 or not t["under"] or t["wide"]]
                if bad:
                    problems.append(f"{where}{label}: {len(bad)} tags wrap or aren't under the name, such as {bad[0]['text']!r}")
                buttons = page.evaluate(status_js)
                hs, dots, cnts = [b["h"] for b in buttons], {b["dot"] for b in buttons}, {b["cnt"] for b in buttons}
                if len(buttons) != 3 or max(hs) - min(hs) > 1 or max(hs) > 64 or len(dots) > 1 or len(cnts) > 1:
                    problems.append(f"{where}{label}: the status buttons aren't one even row (heights {hs}, dots at {sorted(dots)}, counts at {sorted(cnts)})")
                if style:
                    style.evaluate("el => el.remove()")
        print(f"tags and status buttons: {checked_tags} tags each on one line under their name; status buttons even")
        ctx.close()

        # U4 and U5: on All an out-of-date guide is one line pointing to its page (the full banner stays there), and the
        # header is lighter: the UK / Berlin switch is in the title row, the search box has the full width, share is in
        # the chooser and refresh in Help beside when it last worked
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        ctx.add_init_script("localStorage.setItem('gf-selected', 'all'); Object.defineProperty(navigator, 'share', { value: undefined })")  # no share sheet: the link is copied
        page = ctx.new_page()
        page.goto(base)
        page.wait_for_selector("#list .row")
        stale_text = page.locator("#stale").inner_text() if page.locator("#stale").is_visible() else ""
        wide_style = page.add_style_tag(content='* { font-family: Verdana, "DejaVu Sans", sans-serif !important; }')  # the test machine's fonts differ from the phone's
        page.wait_for_timeout(150)
        wide_height = page.locator("#stale").bounding_box()["height"] if page.locator("#stale").is_visible() else 0
        wide_style.evaluate("el => el.remove()")
        if not stale_text or max(page.locator("#stale").bounding_box()["height"], wide_height) > 70 or "may be out of date" not in stale_text:
            problems.append(f"all restaurants: the out-of-date guides aren't one short line ({stale_text!r}, {wide_height:.0f}pt in a wide font)")
        else:
            page.locator("#stale [data-gotorest]").first.click()
            page.wait_for_selector("#list .row")
            if "It covered up to" not in page.locator("#stale").inner_text():
                problems.append("the out-of-date line on All doesn't lead to the restaurant's full banner")
        page.goto(base)
        page.wait_for_selector("#list .row")
        if page.locator("#shareBtn").is_visible() or page.locator("#refreshBtn").is_visible():
            problems.append("the header still has share or refresh buttons")
        if not page.locator(".titlebar #region").count():
            problems.append("the UK / Berlin switch isn't in the title row")
        search = page.locator(".search").bounding_box()
        if search["width"] < IPHONE["viewport"]["width"] - 40:
            problems.append(f"the search box is {search['width']:.0f}pt wide, not the full width")
        page.locator("#pickBtn").click()
        page.wait_for_selector("#picker[open]")
        if not page.locator("#shareBtn").is_visible():
            problems.append("the chooser has no Share button")
        else:
            page.locator("#shareBtn").click()
            page.wait_for_selector("#toast:not([hidden])")  # no share sheet in the test browser: the link is copied or shown
        page.keyboard.press("Escape")
        page.locator("#infoBtn").click()
        page.wait_for_selector("#info[open]")
        page.locator("#info summary", has_text="Staying up to date").click()
        page.locator("#refreshBtn").click()
        page.wait_for_selector("#refreshBtn:not([disabled])")
        if not page.locator("#lastChecked").inner_text().startswith("Last checked today at"):
            problems.append(f"Help: after Check for new menus it says {page.locator('#lastChecked').inner_text()!r}")
        print(f"header: switch in the title row, search {search['width']:.0f}pt wide; All's stale line one line; share in the chooser; refresh in Help")
        ctx.close()

        # U6: Help puts Warnings and Add a menu first, then the tags; the rest folds; the install steps go once it's on the Home Screen
        for standalone in (False, True):
            ctx = browser.new_context(color_scheme="light", **IPHONE)
            ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
            if standalone:
                ctx.add_init_script("Object.defineProperty(navigator, 'standalone', { get: () => true })")
            page = ctx.new_page()
            page.goto(base)
            page.wait_for_selector("#list .row")
            page.locator("#infoBtn").click()
            page.wait_for_selector("#info[open]")
            heads = page.locator("#info > form > h3").all_text_contents()
            folds = page.locator("#info details.more > summary").all_text_contents()
            if heads[:3] != ["Warnings", "Add a menu", "Reading the tags"] or len(folds) < 7:
                problems.append(f"Help: sections are {heads} with folds {folds}")
            if page.locator("#installHelp").is_visible() == standalone:
                problems.append(f"Help: the install steps are {'shown' if standalone else 'missing'} when the app is {'on the Home Screen' if standalone else 'in the browser'}")
            ctx.close()
        print("help: warnings and add a menu first, the rest folded, install steps hidden on the Home Screen")

        # U8: the guide's own warnings come cross-contact first, and every quote is still there word for word
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        page.goto(base + "#starbucks-uk")
        page.wait_for_selector("#list .row")
        page.locator("#openStrip:visible, #openWarnings:visible").first.click()
        page.wait_for_selector("#warnings[open]")
        labels = page.locator("#warnBody .w-label").all_text_contents()
        sb = json.loads((SITE / "data" / "r" / "starbucks-uk.json").read_text(encoding="utf-8"))
        sheet = norm_ws(page.locator("#warnBody").text_content())
        if "Cross-contact" not in labels or "Other allergen updates" not in labels or labels.index("Cross-contact") > labels.index("Other allergen updates"):
            problems.append(f"Starbucks warnings aren't cross-contact first: {labels}")
        lost = [n["text"] for n in sb["notices"] if norm_ws(n["text"]) not in sheet]
        if lost:
            problems.append(f"Starbucks warnings lost or changed quotes: {lost[:2]}")
        print(f"warnings order: {labels[:3]}; {len(sb['notices'])} quotes intact")
        ctx.close()

        # U9: the chooser lists the last used restaurant first, then those with favourites, then A to Z; guide dates are month and year
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        ctx.add_init_script("localStorage.setItem('gf-selected', 'all'); localStorage.setItem('gf-last-restaurant', 'pret-uk'); "
                            "localStorage.setItem('gf-favourites', JSON.stringify(['starbucks-uk|S|N']))")
        page = ctx.new_page()
        page.goto(base)
        page.wait_for_selector("#list .row")
        page.locator("#pickBtn").click()
        page.wait_for_selector("#picker[open]")
        order = page.evaluate("[...document.querySelectorAll('#pickList [data-r]')].map((b) => b.dataset.r)")
        names = {r["id"]: r["name"] for r in index["restaurants"]}
        rest = sorted((i for i in ids if i not in ("pret-uk", "starbucks-uk")), key=lambda i: names[i])
        if order != ["all", "pret-uk", "starbucks-uk"] + rest:
            problems.append(f"chooser order is {order}, expected last used, then favourites, then A to Z")
        lines = page.locator("#pickList .po-main span").all_text_contents()
        if any(re.search(r"\b\d{1,2} [A-Z][a-z]{2} \d{4}\b", t) for t in lines):
            problems.append(f"chooser: a guide date still has the day in it: {[t for t in lines if re.search(r'[0-9] [A-Z][a-z]{2} [0-9]{4}', t)]}")
        if not any("Last used" in t for t in lines):
            problems.append("chooser: the last used restaurant isn't marked")
        print(f"chooser order: {order[:3]}, dates are month and year")
        ctx.close()

        # U10: Add a menu has one big photo button instead of the browser's file box, with a preview of each pick
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        page.goto(base + "#knoops-uk")
        page.wait_for_selector("#list .row")
        page.locator("#infoBtn").click()
        page.locator("#openUpload").click()
        page.wait_for_selector("#upload[open]")
        btn = page.locator("#keySetup .photo-btn")
        if not btn.is_visible() or btn.bounding_box()["height"] < 56 or "Take photos or choose a PDF" not in btn.inner_text():
            problems.append("Add a menu: no big 'Take photos or choose a PDF' button")
        if page.locator("#shareFiles").bounding_box()["width"] > 2:
            problems.append("Add a menu: the browser's own file box still shows")
        page.set_input_files("#shareFiles", files=[{"name": "page.png", "mimeType": "image/png", "buffer": PNG},
                                                   {"name": "menu.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4"}])
        if page.locator("#shareThumbs .thumb").count() != 2 or page.locator("#shareThumbs img").count() != 1 or "2 files chosen" not in page.locator("#shareThumbs").inner_text():
            problems.append(f"Add a menu: the previews are {page.locator('#shareThumbs').inner_text()!r} with {page.locator('#shareThumbs .thumb').count()} thumbnails")
        print("add a menu: photo button, 2 previews")
        ctx.close()

        # U11: the Avoid list is folded until it's wanted, and repeated names say which one is which
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
        page = ctx.new_page()
        page.goto(base + "#blank-street-uk")
        page.wait_for_selector("#list .row")
        bs = json.loads((SITE / "data" / "r" / "blank-street-uk.json").read_text(encoding="utf-8"))
        if page.locator("#avoidWrap").evaluate("el => el.open") or page.locator("#avoid .row").first.is_visible():
            problems.append("Blank Street: the Avoid list is open before it's wanted")
        if f"({len(bs['avoid'])})" not in page.locator("#avoidTitle").inner_text():
            problems.append(f"Blank Street: the Avoid heading {page.locator('#avoidTitle').inner_text()!r} doesn't count {len(bs['avoid'])}")
        page.locator("#avoidWrap > summary").click()
        if not page.locator("#avoid .row").first.is_visible():
            problems.append("Blank Street: tapping the Avoid heading doesn't open it")
        small = [t for t in page.evaluate("[...document.querySelectorAll('#avoid .row')].filter((r) => r.querySelector('.nm').childNodes[0].textContent.trim() === 'Almond Croissant').map((r) => r.querySelector('.nm small')?.textContent || '')")]
        if len(small) < 2 or len(set(small)) != len(small) or "" in small:
            problems.append(f"Blank Street: repeated 'Almond Croissant' rows don't say which is which: {small}")
        page.locator("#avoidWrap > summary").click()
        page.locator("#q").fill("croissant")
        if not page.locator("#avoid .row").first.is_visible():
            problems.append("Blank Street: searching 'croissant' doesn't open the matches on the Avoid list")
        page.locator("#q").fill("")
        if page.locator("#avoidWrap").evaluate("el => el.open"):
            problems.append("Blank Street: the Avoid list stays open after the search is cleared")
        page.evaluate("window.scrollTo(0, 0)")
        page.locator('#status [data-k="gluten"]').click()
        if not page.locator("#avoid .row").first.is_visible():
            problems.append("Blank Street: choosing the Avoid button doesn't open the Avoid list")
        print(f"avoid list: folded, counts {len(bs['avoid'])}, opens on a tap, a search and the Avoid button; repeats say which: {small[:2]}")
        ctx.close()

        # U12: the first run's chooser says what the app is, what the colours mean and that nothing is certified,
        # with Berlin still on the first screen; once left, it doesn't come back
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        page.goto(base)
        page.wait_for_selector("#picker[open]")
        welcome = norm_ws(page.locator("#pickWelcome").inner_text()) if page.locator("#pickWelcome").is_visible() else ""
        if not all(w in welcome for w in ("Green", "Amber", "Red", "Nothing here is certified gluten free")):
            problems.append(f"first run: the welcome is {welcome!r}")
        for s in page.evaluate(WORDING_JS):
            problems.append(f"first run welcome calls something gluten free in the app's own voice: {s!r}")
        berlin = page.locator(f'#pickList [data-region="{cid}"]').bounding_box()
        sheet_box = page.locator("#picker").bounding_box()
        if berlin["y"] + berlin["height"] > min(sheet_box["y"] + sheet_box["height"], IPHONE["viewport"]["height"]):
            problems.append(f"first run: Berlin sits at {berlin['y'] + berlin['height']:.0f}pt, below the first screen of the chooser")
        page.locator(f"#pickList [data-r=\"{ids[0]}\"]").click()
        page.wait_for_selector("#list .row")
        page.locator("#pickBtn").click()
        page.wait_for_selector("#picker[open]")
        if page.locator("#pickWelcome").is_visible():
            problems.append("the welcome shows again once a restaurant has been chosen")
        print(f"first run: welcome says what green, amber and red mean; Berlin ends at {berlin['y'] + berlin['height']:.0f}pt")
        ctx.close()

        # U13: amber only for items that need a change; banners and notes are neutral. Contrast of the tags, buttons and
        # notes is checked in all five themes
        contrast_js = r"""(sel) => {
            const rgba = (s) => s.match(/[\d.]+/g).map(Number);
            const lum = ([r, g, b]) => [r, g, b].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
                .reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0);
            const bgOf = (el) => { for (let e = el; e; e = e.parentElement) { const c = getComputedStyle(e).backgroundColor, v = rgba(c); if (v.length < 4 || v[3] > 0.99) return v; } return [255, 255, 255]; };
            let worst = 21, who = '';
            for (const el of document.querySelectorAll(sel)) {
                if (!el.offsetParent && el !== document.body) continue;
                const bg = bgOf(el), fg = rgba(getComputedStyle(el).color), a = fg[3] ?? 1;
                const mix = [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a));
                const [hi, lo] = [lum(mix), lum(bg)].sort((x, y) => y - x);
                const ratio = (hi + 0.05) / (lo + 0.05);
                if (ratio < worst) { worst = ratio; who = el.tagName.toLowerCase() + '.' + el.className + ' ' + JSON.stringify(el.textContent.trim().slice(0, 24)); }
            }
            return { worst, who };
        }"""
        amber_js = """() => {
            const probe = document.createElement('i'); probe.style.background = 'var(--swap-bg)'; document.body.appendChild(probe);
            const swap = getComputedStyle(probe).backgroundColor; probe.remove();
            return ['#stale', '#searchNote', '#openWarnings', '#openStrip'].filter((s) => getComputedStyle(document.querySelector(s)).backgroundColor === swap);
        }"""
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        for theme in ("auto", "light", "dark", "pink-light", "pink-dark"):
            looks = [("#starbucks-uk", ".tag, .pill-warn, .fav-btn, .certnote p, .status button, .detail, .more summary, .group-h small", True),
                     ("#knoops-uk", ".stale, .stale a, .strip, .stale-line .link-btn", False),
                     ("#blank-street-uk", ".tag", False)]
            for url, sel, open_row in looks:
                page.goto(base + url)
                page.wait_for_selector("#list .row")
                page.evaluate("(t) => (t === 'auto' ? document.documentElement.removeAttribute('data-theme') : document.documentElement.setAttribute('data-theme', t))", theme)
                if open_row:
                    page.locator("#list .row").first.locator("summary").click()
                    page.locator("#list .row").first.locator(".fav-btn").click()  # also checks the saved look
                    page.evaluate("document.getElementById('avoidWrap').open = true")
                if url == "#starbucks-uk":
                    page.locator("#q").fill("oat milk latte")
                    page.wait_for_timeout(250)
                    sel += ", .search-note, .t-bad"
                got = page.evaluate(contrast_js, sel)
                if got["worst"] < 4.5:
                    problems.append(f"{theme} theme, {url[1:]}: contrast {got['worst']:.2f}:1 on {got['who']}")
                amber = page.evaluate(amber_js)
                if amber:
                    problems.append(f"{theme} theme, {url[1:]}: {amber} are amber, which is for items that need a change")
                page.evaluate("localStorage.clear()")
        page.goto(base + f"#{cid}")
        page.wait_for_selector("#cityList .row")
        for theme in ("auto", "light", "dark", "pink-light", "pink-dark"):
            page.evaluate("(t) => (t === 'auto' ? document.documentElement.removeAttribute('data-theme') : document.documentElement.setAttribute('data-theme', t))", theme)
            got = page.evaluate(contrast_js, ".tag, .city-intro p, .more summary, .stale, .chg")
            if got["worst"] < 4.5:
                problems.append(f"{theme} theme, {cid}: contrast {got['worst']:.2f}:1 on {got['who']}")
        print("contrast and amber: tags, buttons and notes in all five themes")
        ctx.close()

        # X5: a restaurant's own name at the start of a search in All restaurants narrows to it
        # ("pret latte" means lattes at Pret), and an everyday word finds the menu's own word ("chips" -> "fries")
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
        page = ctx.new_page()
        page.goto(base)
        page.wait_for_selector("#list .row")
        for q, want_restaurant, want_name in (("pret latte", "Pret A Manger", "latte"), ("five guys fries", "Five Guys", "fries")):
            page.locator("#q").fill(q)
            page.wait_for_timeout(300)
            heads = page.locator("#list .rest-h").all_inner_texts()
            if any(want_restaurant not in h for h in heads) or not heads:
                problems.append(f"search {q!r}: restaurant headings are {heads}, expected only {want_restaurant!r}")
            names = [r["name"] for r in page.evaluate(ROWS_JS)]
            if not any(want_name in n.lower() for n in names):
                problems.append(f"search {q!r}: no row named like {want_name!r} ({names})")
        page.locator("#q").fill("chips")
        page.wait_for_timeout(300)
        names = [r["name"] for r in page.evaluate(ROWS_JS)]
        if not any("fries" in n.lower() for n in names):
            problems.append(f"search 'chips': no Fries found, the everyday-word alias isn't matching ({names})")
        # a short word or the start of a food word isn't a restaurant: "a latte" is everyone's lattes, not Pret A Manger's,
        # and "str" (typing "strawberry") isn't Blank Street
        for q in ("a latte", "str"):
            page.locator("#q").fill(q)
            page.wait_for_timeout(300)
            heads = page.locator("#list .rest-h").all_inner_texts()
            if len(heads) < 2:
                problems.append(f"search {q!r}: narrowed to {heads}, as if it named a restaurant")
        page.locator("#q").fill("")
        if "autumn beverages and autumn food guides" not in page.locator("#sources").inner_text():
            problems.append("footer: Starbucks' guide name leaves out its food guide")
        page.locator("#q").fill("")
        print("search: a restaurant's own name narrows results, and 'chips' finds 'fries'")
        ctx.close()

        # X6: a saved favourite that's changed shows in full on its own restaurant's page and on All,
        # but elsewhere only a short line points to where it is
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        ctx.add_init_script("localStorage.setItem('gf-favourites', JSON.stringify("
                             "['pret-uk|Hot drinks|Gone From Pret','starbucks-uk|Hot drinks|Gone From Starbucks']))")
        page = ctx.new_page()
        page.goto(base + "#five-guys-uk")
        page.wait_for_selector("#list .row")
        alert = page.locator("#favAlert")
        if alert.is_hidden():
            problems.append("favourites changed elsewhere: the alert doesn't show on an unrelated restaurant's page")
        text = alert.inner_text()
        if "saved item" not in text or "Pret" not in text or "Starbucks" not in text:
            problems.append(f"favourites changed elsewhere: short line is {text!r}, expected to name both restaurants")
        if "Gone From Pret" in text:
            problems.append("favourites changed elsewhere: the full warning shows on an unrelated restaurant's page")
        page.locator("[data-gotorest]").first.click()
        page.wait_for_selector("#list .row")
        if "pret-uk" not in page.url or "Gone From Pret" not in page.locator("#favAlert").inner_text():
            problems.append(f"favourites changed: following the line (url {page.url!r}) doesn't show Pret's full warning")
        page.locator("#pickBtn").click()
        page.locator('#pickList [data-r="all"]').click()
        page.wait_for_selector("#list .row")
        allt = page.locator("#favAlert").inner_text()
        if "Gone From Pret" not in allt or "Gone From Starbucks" not in allt:
            problems.append(f"favourites changed: All doesn't show both full warnings ({allt!r})")
        print("favourites changed: short line elsewhere, full detail on its own page and on All")
        ctx.close()

        # X3: "What changed" stays reopenable from Warnings and from Help, even once the dismissable news banner is gone
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        page.goto(base + "#starbucks-uk")
        page.wait_for_selector("#list .row")
        if page.locator("#news").is_visible():
            page.locator("#news [data-seen]").click()
        page.locator("#openWarnings").click()
        page.wait_for_selector("#warnings[open]")
        link = page.locator("#warnBody [data-whatchanged]")
        if not link.count():
            problems.append("starbucks-uk: no 'What changed' link in Warnings once the news banner is dismissed")
        else:
            link.first.click()
            page.wait_for_selector("#changes[open]")
            if not page.locator("#changesBody").inner_text().strip():
                problems.append("starbucks-uk: 'What changed' from Warnings opened an empty dialog")
            page.keyboard.press("Escape")
        page.keyboard.press("Escape")
        page.locator("#infoBtn").click()
        page.wait_for_selector("#info[open]")
        if not page.locator("#infoSources [data-whatchanged]").count():
            problems.append("starbucks-uk: no 'What changed' link in Help, 'Menus in this app'")
        print("what changed: reopenable from Warnings and Help once the news banner is dismissed")
        ctx.close()

        # X9: the out-of-date banner hides while searching, like the other tips and notices
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        page.goto(base + "#knoops-uk")
        page.wait_for_selector("#list .row")
        if not page.locator("#stale").is_visible():
            problems.append("knoops-uk: the out-of-date banner isn't showing, so hiding it can't be checked")
        page.locator("#q").fill("latte")
        page.wait_for_timeout(200)
        if page.locator("#stale").is_visible():
            problems.append("knoops-uk: the out-of-date banner still shows while searching")
        page.locator("#q").fill("")
        print("Knoops banner: hides while searching")
        ctx.close()

        # X11: the toast sits within both edges and doesn't need a tall oval for a two-restaurant message
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        page.goto(base + "#five-guys-uk")
        page.wait_for_selector("#list .row")
        page.evaluate("document.getElementById('toast').textContent = 'New guides: Pret, Starbucks';"
                       "document.getElementById('toast').hidden = false;")
        box = page.locator("#toast").bounding_box()
        vw = IPHONE["viewport"]["width"]
        if box["x"] < 8 or box["x"] + box["width"] > vw - 8:
            problems.append(f"toast: box {box} isn't within the screen's edges (viewport {vw}px wide)")
        if box["height"] > 50:
            problems.append(f"toast: 'New guides: Pret, Starbucks' is {box['height']:.0f}px tall, more than one line")
        print(f"toast: 'New guides: Pret, Starbucks' fits in {box['width']:.0f}x{box['height']:.0f}")
        ctx.close()

        # X12: the Send button doesn't touch the field above it
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        page.goto(base + "#knoops-uk")
        page.wait_for_selector("#list .row")
        page.locator("#infoBtn").click()
        page.locator("#openUpload").click()
        page.wait_for_selector("#upload[open]")
        field_box = page.locator("label.field", has=page.locator("#shareName")).bounding_box()
        btn_box = page.locator("#shareSend").bounding_box()
        gap = btn_box["y"] - (field_box["y"] + field_box["height"])
        if gap < 8:
            problems.append(f"Add a menu: the Send button sits {gap:.0f}px from the field above it")
        print(f"Add a menu: Send button is {gap:.0f}px below the field above it")
        ctx.close()

        # Add a menu with the owner's key: one commit per upload, retries, rate limits and expired keys
        problems += upload_checks(browser, base, "Chromium")

        # F3: the app asks the phone to keep its storage, and says the answer in Help
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        page.goto(base + "#knoops-uk")
        page.wait_for_selector("#list .row")
        page.wait_for_timeout(300)
        page.locator("#infoBtn").click()
        page.wait_for_selector("#info[open]")
        state = page.locator("#storageState")
        if state.is_hidden():
            problems.append("Help: the storage line doesn't show (navigator.storage should be available in Chromium)")
        elif not state.inner_text().strip():
            problems.append("Help: the storage line is empty")
        print(f"storage: {'hidden' if state.is_hidden() else state.inner_text()!r}")
        ctx.close()

        # O6: a content security policy is in place
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        page = ctx.new_page()
        page.goto(base)
        csp = page.evaluate("document.querySelector('meta[http-equiv=\"Content-Security-Policy\"]')?.content || ''")
        for want in ("script-src 'self'", "connect-src 'self' https://api.github.com", "object-src 'none'"):
            if want not in csp:
                problems.append(f"content security policy is missing {want!r} ({csp!r})")
        print(f"content security policy: {csp!r}")
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

        # the iPhone runs WebKit, not Chromium: every page, the sheets and uploads again in Safari's engine
        problems += webkit_checks(p, base, ids, cid)
    httpd.shutdown()

    if problems:
        print("\nUI CHECK FAILED:")
        for pr in problems:
            print(" -", pr)
        sys.exit(1)
    print("UI checks passed")


if __name__ == "__main__":
    main()
