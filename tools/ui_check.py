#!/usr/bin/env python3
"""
Open the built app in a real browser at iPhone size, in light and dark, and
fail if anything is wrong. Run after build.py (needs site/data/).

For every restaurant page and the "All restaurants" page it checks:
  * no JavaScript errors or console errors
  * nothing wider than the screen (no sideways scrolling)
  * the list shows items
the same for each city page in cities.json (every place shown and opened), then
the three sections above the title (Chains, UK cities, Abroad):
UK -> International (search, coeliac card, reload) -> UK, each section's
chooser listing its own cities, each section remembering its city; each UK city
listing the chains with branches there, a row opening the menu; the order builder (parts
tickable, Avoid items blocked, dropped items named, one card with the chain's
cross-contact warning); each chain's logo in the chooser; Berlin on a
Sunday evening (open today, near me, saving); the staff card, German card and
offline header; the tags under item names, even status buttons, the lighter header, Help in sections, the
cross-contact-first warnings, the chooser's order and first-run welcome, the photo button, the folded Avoid
list and amber used only for items needing a change (contrast in all five themes); accessibility (Larger Text, 44pt taps, contrast, VoiceOver
labels); the first visit; search staying above the keyboard; and on one
restaurant it taps through: opening an item, the Show staff card, a status
button and saving a favourite.

Each check is one function registered in CHECKS, so one can be run on its own while working on it. What a check
expects comes from the built menus and cities.json where it can (which place is open when, which name repeats),
so routine upkeep of a menu or a city list doesn't break an unrelated check.

Usage:
  pip install -r tools/requirements-dev.txt && python -m playwright install chromium webkit
  python tools/ui_check.py [--shots DIR]   # everything; --shots saves a screenshot of each page
  python tools/ui_check.py --only f13      # one check (its name from --list), without the WebKit pass
"""
import argparse
import base64
import functools
import hashlib
import json
import math
import re
import shutil
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import changes as py_changes  # noqa: E402

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
# lowest text contrast among the matching elements, against the first painted background behind each (opacity
# included), and which element it is
CONTRAST_JS = r"""(sel) => {
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


# ---------- what the checks share ----------
SHARE_MOCK = "window.__shared = null; Object.defineProperty(navigator, 'share', { value: async (d) => { window.__shared = d; } });"
ALEX = {"latitude": 52.5219, "longitude": 13.4132}  # Alexanderplatz, Berlin
WIDE_FONT = '* { font-family: Verdana, "DejaVu Sans", sans-serif !important; }'  # the test machine's fonts differ from the phone's
norm_ws = lambda s: " ".join(s.split())  # noqa: E731


@functools.lru_cache(maxsize=None)
def menu_of(rid):
    """A restaurant's built menu (site/data/r/<id>.json), read once."""
    return json.loads((SITE / "data" / "r" / f"{rid}.json").read_text(encoding="utf-8"))


def visit(browser, url, *, scheme="light", init="", wait="#list .row", shots=None):
    """A fresh phone-sized page at url, with its errors collected: returns (ctx, page, errors). Close the ctx after."""
    ctx = browser.new_context(color_scheme=scheme, **IPHONE)
    if init:
        ctx.add_init_script(init)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    page.on("console", lambda m: errors.append(f"console {m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.goto(url)
    if wait:
        page.wait_for_selector(wait, timeout=15000)
    return ctx, page, errors


class Css:
    """A stylesheet added to the page through the CSSOM (the content security policy allows no inline styles)."""

    def __init__(self, page, css):
        self.page = page
        self.id = page.evaluate("(css) => { const s = new CSSStyleSheet(); s.replaceSync(css); document.adoptedStyleSheets = [...document.adoptedStyleSheets, s];"
                                " window.__css = window.__css || []; window.__css.push(s); return window.__css.length - 1; }", css)

    def remove(self):
        self.page.evaluate("(n) => { const s = window.__css[n]; document.adoptedStyleSheets = document.adoptedStyleSheets.filter((x) => x !== s); }", self.id)


add_css = Css


# ---------- the app's reading of cities.json, in Python, so what a place's row says can be checked against its data ----------
def km_to(l, at):
    """The app's own distance (site/app.js kmTo): near enough for nearest-first within a city."""
    return math.hypot((l["lat"] - at["lat"]) * 111.2, (l["lon"] - at["lon"]) * 111.2 * math.cos(math.radians(at["lat"])))


def here(geo):
    """Playwright's geolocation as the app's point."""
    return {"lat": geo["latitude"], "lon": geo["longitude"]}


def nearest_places(c, geo):
    """The city's places, nearest first to a Playwright geolocation, as Near me lists them."""
    return sorted(c["places"], key=lambda pl: min(km_to(l, here(geo)) for l in pl["locations"]))


def closes(h):
    """When an "HH:MM–HH:MM" span closes, in minutes; 0 for closed or unknown."""
    found = re.findall(r"(\d{1,2}):(\d{2})", h or "")
    return int(found[-1][0]) * 60 + int(found[-1][1]) if found else 0


def sunday(pl):
    return [(l.get("hours") or [""] * 7)[6] for l in pl["locations"]]


def span(h):
    m = re.match(r"(\d{1,2}):(\d{2})\s*[–-]\s*(\d{1,2}):(\d{2})", h or "")
    return (int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])) if m else None


def spans(h):
    """Every range in a day's hours ("12:00–14:30, 17:00–21:30" has a break), as site/app.js spans() reads them."""
    return [(int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])) for m in re.finditer(r"(\d{1,2}):(\d{2})\s*[–-]\s*(\d{1,2}):(\d{2})", h or "")]


def branch_today(l, day, minute):
    """The range that matters at that minute (site/app.js branchToday): open now, else the next today, else the last."""
    hours = l.get("hours")
    if not hours or hours[day] is None:
        return {"unknown": True}
    ss = spans(hours[day])
    if not ss:
        return {"closed": True}
    s = next((x for x in ss if x[0] <= minute < x[1]), None) or next((x for x in ss if x[0] > minute), None) or ss[-1]
    kitchen = span("00:00–" + (l.get("kitchenCloses") or "24:00"))
    return {"open": s[0], "close": min(s[1], kitchen[1]), "kitchen": bool(l.get("kitchenCloses")) and kitchen[1] < s[1], "door": s[1]}


def expected_today(pl, day, minute, geo=None):
    """How a place's row should start at that moment (site/app.js todayLine): "Open now", "Opens at", "Kitchen closed",
    "Closed now", "Closed today", or nothing when its hours aren't known. With geo, only its nearest branch counts."""
    ls = [min(pl["locations"], key=lambda l: km_to(l, here(geo)))] if geo else pl["locations"]
    bs = [branch_today(l, day, minute) for l in ls]
    if all(b.get("unknown") for b in bs):
        return ""
    if any("open" in b and b["open"] <= minute < b["close"] for b in bs):
        return "Open now"
    if any("open" in b and b["open"] > minute for b in bs):
        return "Opens at"
    if any("open" in b and b["kitchen"] and minute < b["door"] for b in bs):
        return "Kitchen closed"
    if any("open" in b for b in bs):
        return "Closed now"
    return "" if any(b.get("unknown") for b in bs) else "Closed today"


def place_text(pl):
    """What the app searches for a place (site/app.js placeText): what and where it is, not its street names."""
    says = pl.get("says") or {}
    return " ".join(x for x in [pl["name"], pl.get("type"), pl.get("listed"), pl.get("flag"), pl.get("caution"), says.get("text"), says.get("en"),
                                " ".join(l["area"] for l in pl["locations"])] if x).lower()


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


def stand_in_branches(site):
    """One branch per chain, in a line north of King's Cross: enough for the app to have a list in any check."""
    index = json.loads((site / "data" / "restaurants.json").read_text(encoding="utf-8"))
    ids = [r["id"] for r in index["restaurants"] if r.get("osm")]
    return {"fetched": "2026-10-20", "chains": ids, "b": [[n, round(51.5308 + n * 0.002, 5), -0.1238, "", ""] for n in range(len(ids))]}


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        # a weak signal: every answer but the service worker's own file takes this long
        if self.server.lag["s"] and not self.path.startswith("/sw.js"):
            time.sleep(self.server.lag["s"])
        # the branch list is written by the publish job only (tools/fetch_branches.py), so a pull request's check has
        # none: answer a small stand-in rather than a 404 the app's quiet download would log (never written to disk,
        # where a publish could pick it up). The near-me and map checks serve their own through with_branches().
        if self.path.split("?")[0] == "/data/branches.json" and not (Path(self.directory) / "data" / "branches.json").exists():
            body = json.dumps(stand_in_branches(Path(self.directory))).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_request(self, code="-", size="-"):
        self.server.answered.append((self.path, int(code) if str(code).isdigit() else code))


def serve(root=SITE, lag=None):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(root)))
    httpd.lag, httpd.answered = lag if lag is not None else {"s": 0}, []
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"



def check_every_page(env):
    base, ids, browser, args = env.base, env.ids, env.browser, env.args
    problems = []
    # every restaurant page and All: no errors, nothing wider than the screen, items listed (the colour scheme makes no
    # difference to any of that; the themes are checked by u13)
    for rid in [None] + ids:
        where = rid or "all restaurants"
        ctx, page, errors = visit(browser, base + (f"#{rid}" if rid else ""), init="" if rid else "localStorage.setItem('gf-selected', 'all')",
                                  wait="#list .row, #list .empty")
        page.wait_for_timeout(300)
        rows = page.locator("#list .row").count()
        wide = page.evaluate(WIDE_JS)
        problems += [f"{where}: {e}" for e in errors]
        problems += [f"{where}: too wide: {w}" for w in wide]
        if not rows:
            problems.append(f"{where}: no items listed")
        if args.shots:
            page.screenshot(path=str(args.shots / f"{rid or 'all'}.png"))
        print(f"{where}: {rows} rows, {len(errors)} errors, {len(wide)} too wide")
        ctx.close()
    return problems


def want_sections(cities):
    """The header's sections (site/app.js SECTIONS): UK franchises always, then each city group that has a city."""
    groups = {c.get("group") for c in cities.values()}
    return ["Chains"] + ["UK cities"] * ("uk" in groups) + ["Abroad"] * (any(g != "uk" for g in groups))


def served_branches():
    """The branch list the test server answers: the site's own when the publish wrote one, else the stand-in."""
    f = SITE / "data" / "branches.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else stand_in_branches(SITE)


def check_uk_cities(env):
    """A UK city lists, under its places, the app's chains with branches inside its bounds (the branch list), one row
    per chain with its count; a row opens that chain's menu under UK franchises. A UK city has no coeliac card chip."""
    base, cities, browser, index = env.base, env.cities, env.browser, env.index
    problems = []
    names = {r["id"]: r["name"] for r in index["restaurants"]}
    branches = served_branches()
    done = 0
    for cid, c in cities.items():
        if c.get("group") != "uk":
            continue
        (s, n), (w, e) = c["bounds"]["lat"], c["bounds"]["lon"]
        want = {}
        for x in branches["b"]:
            rid = branches["chains"][x[0]]
            if rid in names and s < x[1] < n and w < x[2] < e:
                want[rid] = want.get(rid, 0) + 1
        ctx, page, errors = visit(browser, base + f"#{cid}", wait="#cityList .row")
        if want:
            page.wait_for_selector(".chains-here [data-chain]")
        else:
            page.wait_for_timeout(500)
        got = page.evaluate("[...document.querySelectorAll('.chains-here [data-chain]')].map((b) => [b.dataset.chain, b.querySelector('.po-main span').textContent])")
        if sorted(g[0] for g in got) != sorted(want):
            problems.append(f"{cid}: chains listed {sorted(g[0] for g in got)}, expected {sorted(want)}")
        for rid, text in got:
            if rid in want and not text.startswith(f"{want[rid]} branch"):
                problems.append(f"{cid}: {rid} reads {text!r}, expected {want[rid]} branches")
        if page.locator("#chips [data-card]").count():
            problems.append(f"{cid}: a UK city shows a coeliac card chip")
        problems += [f"{cid}: {x}" for x in errors]
        if got:  # a chain's row opens its menu, under UK franchises
            page.locator(f'.chains-here [data-chain="{got[0][0]}"]').click()
            page.wait_for_selector("#list .row")
            pressed = page.evaluate("[...document.querySelectorAll('#region [aria-pressed=\"true\"]')].map((b) => b.dataset.region)")
            if pressed != ["uk"] or page.evaluate("location.hash") != "#" + got[0][0]:
                problems.append(f"{cid}: the {got[0][0]} row went to {page.evaluate('location.hash')!r} with {pressed} pressed")
        done += 1
        ctx.close()
    print(f"uk cities: {done} cities, each listing its chains with their counts, a row opening the chain's menu")
    return problems


def check_the_berlin_page_in_light(env):
    base, cid, cities, index, browser, args = env.base, env.cid, env.cities, env.index, env.browser, env.args
    problems = []
    # each city page, in light and dark, then switching to it and back
    for scheme in ("light", "dark"):
        for cid, c in cities.items():
            where = f"{cid} ({scheme})"
            ctx, page, errors = visit(browser, base + f"#{cid}", scheme=scheme, wait="#cityList .row")
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
    intl = [c for c, city in cities.items() if city.get("group") != "uk"]
    ukc = [c for c, city in cities.items() if city.get("group") == "uk"]
    # the sections sit on their own row above the title (the chooser) and the search box, in this order
    labels = [b.strip() for b in page.locator("#region button").all_inner_texts()]
    if labels != want_sections(cities):
        problems.append(f"the sections read {labels}")
    order = page.evaluate("[...document.querySelector('.top').children].map((el) => el.id || el.className)")
    if order[:3] != ["region", "titlebar", "search"]:
        problems.append(f"the header's rows are {order[:3]}, expected the sections, then the title, then the search box")
    cid = intl[0]
    page.locator('#region [data-region="intl"]').click()  # International: the first city, nothing having been looked at yet
    page.wait_for_selector("#cityList .row")
    if page.locator("#pickName").inner_text().strip() != cities[cid]["name"]:
        problems.append(f"International went to {page.locator('#pickName').inner_text()!r}, expected the first city, {cities[cid]['name']}")
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
    # UK franchises' chooser lists the restaurants only; each city section's chooser lists its own cities
    page.locator("#pickBtn").click()
    page.wait_for_selector("#picker[open]")
    if page.locator("#pickList [data-region]").count():
        problems.append("UK franchises' chooser lists cities too")
    page.locator("#picker .sheet-head .link-btn").click()
    for section, ids in (("intl", intl), ("ukcity", ukc)):
        if not ids:
            continue
        page.locator(f'#region [data-region="{section}"]').click()
        page.wait_for_selector("#cityList .row")
        page.locator("#pickBtn").click()
        page.wait_for_selector("#picker[open]")
        listed = page.evaluate("[...document.querySelectorAll('#pickList [data-region]')].map((b) => b.dataset.region)")
        if listed != ids:
            problems.append(f"the {section} chooser lists {listed}, expected {ids}")
        for c in ids:  # International by its country, a UK city by its name
            want = cities[c]["name"] if section == "ukcity" else cities[c]["country"]
            if want not in page.locator(f'#pickList [data-region="{c}"] b').inner_text():
                problems.append(f"the {section} chooser doesn't name {c} as {want}")
        page.locator(f'#pickList [data-region="{ids[-1]}"]').click()  # each section then remembers its own city
        page.wait_for_selector("#cityList .row")
    for section, ids in (("intl", intl), ("ukcity", ukc)):
        if not ids:
            continue
        page.locator('#region [data-region="uk"]').click()
        page.wait_for_selector("#list .row")
        page.locator(f'#region [data-region="{section}"]').click()
        page.wait_for_selector("#cityList .row")
        if page.locator("#pickName").inner_text().strip() != cities[ids[-1]]["name"]:
            problems.append(f"{section} went to {page.locator('#pickName').inner_text()!r}, not the city last looked at there ({cities[ids[-1]]['name']})")
        pressed = page.evaluate("[...document.querySelectorAll('#region [aria-pressed=\"true\"]')].map((b) => b.dataset.region)")
        if pressed != [section]:
            problems.append(f"on {ids[-1]} the pressed section is {pressed}, expected {section}")
    print(f"switch: three sections above the title; UK -> {cid} (search, card, reload) -> UK; each chooser lists its own section; each section remembers its city")
    ctx.close()
    return problems


def check_berlin_on_a_sunday_evening(env):
    base, cid, cities, browser = env.base, env.cid, env.cities, env.browser
    problems = []
    # the first city on a Sunday evening at a fixed spot (Alexanderplatz): open today, nearest first, saving a place
    alex = ALEX
    ctx = browser.new_context(color_scheme="light", geolocation=alex, permissions=["geolocation"], **IPHONE)
    page = ctx.new_page()
    page.clock.set_fixed_time("2026-11-01T19:00:00+01:00")  # Sunday 1 November, 19:00 in Berlin
    page.goto(base + f"#{cid}")
    page.wait_for_selector("#cityList .row")
    shown = lambda: [n.split("\n")[0].strip().lstrip("★").strip() for n in page.locator("#cityList .row .nm").all_inner_texts()]
    # at 19:00 on Sunday, "still open today" means open now or opening later, not already shut for the day
    for pl in cities[cid]["places"]:
        row = page.locator("#cityList .row", has=page.locator(".nm", has_text=pl["name"])).first.inner_text()
        hrs = [h for h in sunday(pl) if h]
        if hrs and max(closes(h) for h in hrs) > 19 * 60 and "Open now" not in row:
            problems.append(f"{cid} Sunday 19:00: {pl['name']} ({hrs}) doesn't say Open now")
        if hrs and max(closes(h) for h in hrs) <= 19 * 60 and "Closed now" not in row:
            problems.append(f"{cid} Sunday 19:00: {pl['name']} ({hrs}) doesn't say Closed now")
    # Open near me: what's still open today, nearest first, in one chip
    page.locator("#chips [data-nearopen]").click()
    page.wait_for_selector('#chips [data-nearopen][aria-pressed="true"]')
    want = sorted(pl["name"] for pl in cities[cid]["places"] if any(closes(h) > 19 * 60 for h in sunday(pl)))
    if sorted(shown()) != want:
        problems.append(f"{cid} still open today (Sunday 19:00): shows {sorted(shown())}, expected {want}")
    nearest = [pl for pl in nearest_places(cities[cid], alex) if pl["name"] in want]
    if shown()[:3] != [pl["name"] for pl in nearest[:3]]:
        problems.append(f"{cid} open near me: starts {shown()[:3]}, expected {[pl['name'] for pl in nearest[:3]]}")
    page.locator("#chips [data-nearopen]").click()
    # the row: the language card first, then All, Open near me, Favourites; no separate Near me or Still open today
    order = page.evaluate("[...document.querySelectorAll('#chips button')].map((b) => b.dataset.card !== undefined ? 'card' : b.dataset.nearopen !== undefined ? 'nearopen' : b.dataset.map !== undefined ? 'map' : b.dataset.kind || '?')")
    if order[:4] != ["card", "all", "nearopen", "fav"] or order[-1] != "map" or "open" in order or page.locator("#chips [data-near]").count():
        problems.append(f"{cid}: the chips run {order}, expected the card, All, Open near me, Favourites, then sections, Map last")
    # a street name isn't a day: searching a weekday finds only places whose own words hold it, never one by its address
    for day in ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag", "maandag", "zondag"):
        page.locator("#q").fill(day)
        allowed = {pl["name"] for pl in cities[cid]["places"] if day.lower() in place_text(pl)}
        if set(shown()) - allowed:
            problems.append(f"{cid}: searching {day!r} finds {sorted(set(shown()) - allowed)}, which don't say it (a street name?)")
    page.locator("#q").fill("")
    first = page.locator("#cityList .row").first
    first.locator("summary").click()
    first.locator(".fav-btn").click()
    page.reload()
    page.wait_for_selector("#cityList .row")
    page.evaluate("window.scrollTo(0, 0)")  # the reload keeps the scroll position, with the header folded away
    page.wait_for_selector(".top:not(.collapsed)")
    page.locator('#chips [data-kind="fav"]').click()
    if page.locator("#cityList .row").count() != 1:
        problems.append(f"{cid}: after saving one place and reloading, Saved shows {page.locator('#cityList .row').count()}")
    print(f"{cid}: open on Sunday {len(want)}, nearest to Alexanderplatz {shown()[:1] and nearest[0]['name']}, saving works")
    ctx.close()
    return problems


def check_final_review(env):
    base, ids, cid, cities, browser = env.base, env.ids, env.cid, env.cities, env.browser
    problems = []
    # final review: allowed-milk search, the app's own doubts, which dish a staff card means, and every place's open
    # line at fixed moments. The items and places come from the data, so upkeep of a menu or a city doesn't break this.
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    page = ctx.new_page()
    # a milk that's allowed can be searched for ("soya latte" finds the lattes fine with soya)
    milky = next((rid for rid in ids if any("soya" in (i.get("ok") or []) for i in menu_of(rid)["items"])), None)
    if milky:
        item = next(i for i in menu_of(milky)["items"] if "soya" in (i.get("ok") or []))
        page.goto(base + f"#{milky}")
        page.wait_for_selector("#list .row")
        for q in (f"soya {item['name'].split()[0]}", f"soya milk {item['name'].split()[0]}"):
            page.locator("#q").fill(q)
            if not page.locator("#list .row").count():
                problems.append(f"{milky}: searching {q!r} finds nothing, though {item['name']!r} is fine with soya")
    # the app's own doubt about an item (a hand-kept menu's "doubt" row) puts it on the Avoid list as Check in store
    doubted = next(((rid, a) for rid in ids for a in menu_of(rid)["avoid"] if a.get("tag") == "Check in store"), None)
    if doubted:
        rid, a = doubted
        page.goto(base + f"#{rid}")
        page.wait_for_selector("#list .row")
        page.locator("#q").fill(a["name"])
        if page.locator("#list .row").count():
            problems.append(f"{rid}: {a['name']!r} is still listed with no gluten ingredients despite the app's caution")
        if "Check in store" not in page.locator("#avoid").inner_text():
            problems.append(f"{rid}: {a['name']!r} isn't on the Avoid list marked 'Check in store'")
        page.locator("#q").fill("")
    # a name used by several dishes (Pho's "Chicken"): the staff card says which one
    shared = next(((rid, n) for rid in ids for n, c in __import__("collections").Counter(i["name"] for i in menu_of(rid)["items"] if not i.get("role")).items() if c > 1), None)
    if shared:
        rid, name = shared
        page.goto(base + f"#{rid}")
        page.wait_for_selector("#list .row")
        page.locator("#q").fill(name.lower())
        row = page.locator("#list .row").nth([r["name"] for r in page.evaluate(ROWS_JS)].index(name))
        row.locator("summary").click()
        row.locator(".staff-btn").click()
        page.wait_for_selector("#staff[open]")
        sec = page.locator("#staff .staff-sec").inner_text().strip() if page.locator("#staff .staff-sec").count() else ""
        if not sec or sec == name:
            problems.append(f"{rid}: the staff card for {name!r} doesn't say which dish ({sec!r})")
        page.locator("#staff .link-btn").click()
    page.goto(base)
    page.wait_for_selector("#list .row")
    page.locator("#pickBtn").click()
    page.locator('#pickList [data-r="all"]').click()
    if page.locator("#cardLaunch").is_visible():
        problems.append("UK all restaurants: shows a coeliac card button")
    ctx.close()

    # every place's open line, at fixed moments, against the app's own reading of its hours (expected_today): with Near me
    # on (only the nearest branch counts), on a Monday, a Tuesday, after coming back to the app later, and late on a Sunday
    geo = {"latitude": 52.50936, "longitude": 13.29682}
    c = cities[cid]
    ctx = browser.new_context(color_scheme="light", geolocation=geo, permissions=["geolocation"], **IPHONE)
    page = ctx.new_page()
    lines_now = lambda: {r["name"]: r["today"] for r in page.evaluate(  # noqa: E731
        "[...document.querySelectorAll('#cityList .row')].map((r) => ({ name: r.dataset.place, today: (r.querySelector('.today') || {}).textContent || '' }))")}

    def expect(label, day, minute, at=None, shown_only=False):
        got = lines_now()
        for pl in c["places"]:
            if shown_only and pl["name"] not in got:  # Open near me shows only what's still open
                continue
            want = expected_today(pl, day, minute, at)
            if not got.get(pl["name"], "").startswith(want):
                problems.append(f"{cid} {label}: {pl['name']} says {got.get(pl['name'])!r}, expected {want!r} from its hours")
    page.clock.set_fixed_time("2026-11-03T15:00:00+01:00")  # Tuesday 15:00
    page.goto(base + f"#{cid}")
    page.wait_for_selector("#cityList .row")
    page.locator("#chips [data-nearopen]").click()
    page.wait_for_timeout(500)
    expect("Tuesday 15:00 with Open near me", 1, 15 * 60, geo, shown_only=True)
    page.evaluate("window.scrollTo(0, 0)")
    top = page.locator("#cityList .row").first.bounding_box()["y"] if page.locator("#cityList .row").count() else 0
    if top > 450:
        problems.append(f"{cid}: after choosing a filter the first result is at y={top:.0f}, below the fold")
    page.locator("#chips [data-nearopen]").click()
    page.clock.set_fixed_time("2026-11-02T13:00:00+01:00")
    page.reload()
    page.wait_for_selector("#cityList .row")
    expect("Monday 13:00", 0, 13 * 60)
    page.clock.set_fixed_time("2026-11-03T13:00:00+01:00")
    page.reload()
    page.wait_for_selector("#cityList .row")
    expect("Tuesday 13:00", 1, 13 * 60)
    page.clock.set_fixed_time("2026-11-03T16:00:00+01:00")  # back in the app three hours later: the lines move on
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_timeout(800)
    expect("after coming back at 16:00", 1, 16 * 60)
    page.clock.set_fixed_time("2026-11-01T21:30:00+01:00")  # a kitchen that closes before the door
    page.reload()
    page.wait_for_selector("#cityList .row")
    expect("Sunday 21:30", 6, 21 * 60 + 30)
    print(f"final review checks: milk search, the app's doubts, which dish a card means; every {cid} place's open line at five moments matches its hours")
    ctx.close()
    return problems


def check_add_a_menu_without_a(env):
    base, browser = env.base, env.browser
    problems = []
    # Add a menu without a key: a way for anyone to send photos, and a real link for the owner's key
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    page = ctx.new_page()
    page.goto(base + "#starbucks-uk")
    page.wait_for_selector("#list .row")
    tips = page.locator("#tips > div")
    if tips.count() != tips.locator("b").count():
        problems.append(f"starbucks-uk: {tips.count() - tips.locator('b').count()} tips have no bold lead-in")
    # an out-of-date guide whose owner has looked for a newer one (latestGuide in restaurant.json): the banner says so
    today = time.strftime("%Y-%m-%d")
    noted = next((r["id"] for r in env.index["restaurants"] if menu_of(r["id"]).get("latestGuide") and (r.get("guide") or {}).get("validUntil", "9") < today), None)
    if noted:
        page.goto(base + f"#{noted}")
        page.wait_for_selector("#list .row")
        if menu_of(noted)["latestGuide"]["note"] not in page.locator("#stale").inner_text():
            problems.append(f"{noted}: the out-of-date banner doesn't say whether a newer guide exists")
    else:
        page.goto(base + f"#{env.ids[0]}")
        page.wait_for_selector("#list .row")
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
    return problems


def check_staff_card_wording_the_german(env):
    base, browser = env.base, env.browser
    problems = []
    # staff card wording, the German card, and saying when it's offline
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    page = ctx.new_page()
    page.goto(base + "#starbucks-uk")
    page.wait_for_selector("#list .row")
    sb = menu_of("starbucks-uk")
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
    return problems


def check_accessibility(env):
    base, cid, browser = env.base, env.cid, env.browser
    problems = []
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
            ratio = page.evaluate(CONTRAST_JS, '#status button[aria-pressed="false"]')["worst"]
            if ratio < 4.5:
                problems.append(f"{url}: unselected status buttons have contrast {ratio:.2f}:1, under 4.5:1")
            label = page.locator("#pickBtn").get_attribute("aria-label") or ""
            if "Starbucks" not in label:
                problems.append(f"{url}: the title button's VoiceOver label {label!r} doesn't say which restaurant")
            if page.locator(".milk.no").count() and "not" not in page.locator(".milk.no").first.text_content():
                problems.append(f"{url}: a crossed-out milk isn't read as 'not' by VoiceOver")
        before = page.evaluate(f"parseFloat(getComputedStyle(document.querySelector('{rows} .nm')).fontSize)")
        add_css(page, "html { font-size: 22px !important; }")  # iPhone Larger Text
        page.wait_for_timeout(300)
        after = page.evaluate(f"parseFloat(getComputedStyle(document.querySelector('{rows} .nm')).fontSize)")
        if after <= before:
            problems.append(f"{url}: text doesn't grow with Larger Text ({before}px -> {after}px)")
        problems += [f"{url} with Larger Text: too wide: {w}" for w in page.evaluate(WIDE_JS)]
        print(f"accessibility {url}: {len(small)} small tap targets, text {before}px -> {after}px with Larger Text")
        ctx.close()
    return problems


def check_first_visit(env):
    base, ids, cid, browser = env.base, env.ids, env.cid, env.browser
    problems = []
    # first visit: no "what changed" banner (nothing has changed for a new user); the chooser lists the restaurants and
    # its welcome points to the sections switch, which reaches the cities
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#picker[open]")
    if page.locator("#news").is_visible():
        problems.append("first visit: the 'what changed' banner shows for a new user")
    if page.locator("#pickList [data-region]").count() or "UK cities" not in page.locator("#pickWelcome").inner_text():
        problems.append("first visit: the chooser lists cities, or its welcome doesn't point to UK cities")
    page.locator("#picker .sheet-head .link-btn").click()
    page.locator('#region [data-region="intl"]').click()
    page.wait_for_selector("#cityList .row")
    if page.locator("#picker[open]").count():
        problems.append("first visit: International left the chooser open")
    page.locator("#pickBtn").click()
    page.wait_for_selector("#picker[open]")
    if page.locator(f'#pickList [data-region="{cid}"]').get_attribute("aria-pressed") != "true":
        problems.append("from Berlin, the chooser doesn't show Berlin as chosen")
    page.locator("#picker .sheet-head .link-btn").click()
    page.locator('#region [data-region="uk"]').click()
    page.wait_for_selector("#list .row")
    page.locator("#pickBtn").click()
    page.locator(f"#pickList [data-r=\"{ids[0]}\"]").click()
    page.wait_for_selector("#list .row")
    # wording: the guides do call some (avoided) items gluten free, so don't say they never use the words
    if "don't claim their food is gluten free" in (page.locator("#certText").text_content() or ""):
        problems.append("certified note says the restaurants don't claim their food is gluten free")
    # the first visit to the menus: the restaurant chosen from the welcome has the card in full, though All was
    # drawn behind the chooser first
    if not page.locator("#certNote").is_visible():
        problems.append("first visit: the restaurant chosen first doesn't show the certified-or-not card in full")
        page.locator("#openStrip").click()
    else:
        page.locator("#openWarnings").click()
    page.wait_for_selector("#warnings[open]")
    if "none of these guides use" in page.locator("#warnBody").inner_text():
        problems.append("warnings intro says none of the guides use the words gluten free")
    print("first visit: the chooser's welcome points to the sections, International then Berlin, no changes banner; wording checked")
    ctx.close()
    return problems


def check_search(env):
    base, ids, cid, browser = env.base, env.ids, env.cid, env.browser
    problems = []
    # search: the first result sits above the iPhone keyboard (about 340pt tall), and a ruled-out milk is explained
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    page = ctx.new_page()
    word = next(w for i in menu_of(ids[1])["items"] for w in i["name"].split() if len(w) > 3 and w.isalpha())  # a real search on a real menu
    for url, query, rows in ((f"#{ids[0]}", "a", "#list .row"), (f"#{ids[1]}", word.lower(), "#list .row"), (f"#{cid}", "café", "#cityList .row")):
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
    return problems


def check_food_safety(env):
    base, ids, browser = env.base, env.ids, env.browser
    problems = []
    # food safety: a part of a dish or an ingredient listed on its own isn't something to order. No green row
    # may share a name with an Avoid row, and neither kind gets a staff card (Five Guys' sausage was "Hot Dog")
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    page = ctx.new_page()
    for rid in ids:
        built = menu_of(rid)
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
    return problems


def check_f13_build_an_order(env):
    base, browser = env.base, env.browser
    problems = []
    # F13, build an order: dishes and parts can be ticked (ingredients listed on their own can't), the Avoid list is
    # shown but can't be added, the card lists what was ticked with how to order each and the chain's own cross-contact
    # warning, and a saved order naming an Avoid item or an unknown one (a new guide, or a tampered phone) loses it and says so
    for rid in ("five-guys-uk", "pho-uk"):
        built = menu_of(rid)
        key = lambda i: f"{rid}|{i['section']}|{i['name']}"
        tickable = [i for i in built["items"] if i.get("role") != "ingredient"]
        avoid_names = {a["name"] for a in built["avoid"]}
        saved = [key(tickable[0]), key(built["avoid"][0]), f"{rid}|Nowhere|Nothing of the sort"]
        ctx = browser.new_context(color_scheme="light", **IPHONE)
        ctx.add_init_script(f"localStorage.setItem('gf-order', {json.dumps(json.dumps({rid: saved}))})")
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e, errors=errors: errors.append(f"page error: {e}"))
        page.goto(base + f"#{rid}")
        page.wait_for_selector("#list .row")
        launch = page.locator("#chips [data-order-open]")
        launch_text = launch.inner_text() if launch.count() else ""
        if "Your order (1)" not in launch_text:
            problems.append(f"{rid}: the order pill says {launch_text!r}, expected 'Your order (1)' once the Avoid item and the unknown one are dropped")
        launch.click()
        page.wait_for_selector("#order[open]")
        keys = page.evaluate("[...document.querySelectorAll('#orderBody input[data-key]')].map((b) => b.dataset.key)")
        if sorted(keys) != sorted(key(i) for i in tickable):
            problems.append(f"{rid}: the builder offers {len(keys)} items, expected the {len(tickable)} with no gluten ingredients (parts in, ingredients out)")
        if key(built["avoid"][0]) in keys or page.locator("#orderBody input:checked").count() != 1:
            problems.append(f"{rid}: an Avoid item can be ticked, or a dropped item is still ticked")
        note = page.locator("#orderBody .chg-note").inner_text() if page.locator("#orderBody .chg-note").count() else ""
        if built["avoid"][0]["name"] not in note or "Nothing of the sort" not in note or "Avoid list" not in note:
            problems.append(f"{rid}: the builder doesn't say what was taken out of the order ({note!r})")
        blocked = page.locator("#orderBody .o-avoid .o-row").count()
        if blocked != len(built["avoid"]):
            problems.append(f"{rid}: {blocked} Avoid items shown as blocked, expected {len(built['avoid'])}")
        change = next((i for i in tickable if i["order"] == "modify"), None)
        picks = [tickable[1]] + ([change] if change else [])
        tick = "(k) => [...document.querySelectorAll('#orderBody input[data-key]')].find((x) => x.dataset.key === k).click()"
        for i in picks:
            page.evaluate(tick, key(i))
        if f"{1 + len(picks)} items" not in page.locator("#orderCount").inner_text():
            problems.append(f"{rid}: after ticking, the builder says {page.locator('#orderCount').inner_text()!r}, expected {1 + len(picks)} items")
        page.locator("#orderCard").click()
        page.wait_for_selector("#staff[open]")
        listed = [t.strip() for t in page.locator("#staffBody .staff-list li b").all_inner_texts()]
        want = [i["name"] for i in [tickable[0]] + picks]
        if sorted(listed) != sorted(want):
            problems.append(f"{rid}: the order card lists {listed}, expected {want}")
        if set(listed) & avoid_names:
            problems.append(f"{rid}: the order card lists something from the Avoid list: {sorted(set(listed) & avoid_names)}")
        card = page.locator("#staffBody").inner_text()
        if change and change["note"] not in card:
            problems.append(f"{rid}: the order card doesn't say how to order {change['name']!r} ({change['note']!r})")
        cc = [n["text"] for n in built["notices"] if n["kind"] == "cross-contact"]
        if not any(t in card for t in cc):
            problems.append(f"{rid}: the order card doesn't quote the chain's own cross-contact warning")
        if rid == "five-guys-uk" and "no bun" not in card.lower():
            problems.append("five-guys-uk: the order card doesn't ask for no bun")
        if "coeliac disease" not in card:
            problems.append(f"{rid}: the order card doesn't say the person has coeliac disease")
        page.locator("#staff .link-btn").click()
        page.locator("#orderClear").click()
        if page.locator("#orderBody input:checked").count() or not page.locator("#orderCard").is_disabled():
            problems.append(f"{rid}: Clear left items ticked, or Show staff enabled with nothing ticked")
        page.keyboard.press("Escape")
        # the button in an opened item adds it, and the pill follows
        row = page.locator("#list .row", has=page.locator(f'.order-btn[data-order="{key(tickable[0])}"]')).first
        row.locator("summary").click()
        row.locator(".order-btn").click()
        page.wait_for_timeout(100)
        if row.locator(".order-btn").get_attribute("aria-pressed") != "true" or "Your order (1)" not in page.locator("#chips [data-order-open]").inner_text():
            problems.append(f"{rid}: Add to order in an opened item didn't add it ({row.locator('.order-btn').inner_text()!r}, pill {page.locator('#chips [data-order-open]').inner_text()!r})")
        problems += [f"{rid} order: {e}" for e in errors]
        print(f"{rid}: order builder offers {len(keys)}, blocks {blocked}; dropped items named; card lists {len(listed)} with the cross-contact warning")
        ctx.close()
    return problems


def check_logos(env):
    base, index, browser = env.base, env.index, env.browser
    problems = []
    # logos: each restaurant's own mark in the chooser and the title, a lettered badge where there's none
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#list .row")
    page.locator("#pickBtn").click()
    page.wait_for_selector("#picker[open]")
    page.wait_for_timeout(500)
    marks = page.evaluate("""() => [...document.querySelectorAll('#pickList [data-r]')].map((b) => {
        const w = b.querySelector('.logo-wrap'), img = w && w.querySelector('img');
        return { id: b.dataset.r, wrap: !!w, img: !!img, loaded: !!img && img.complete && img.naturalWidth > 0, badge: w && w.querySelector('.mono') && getComputedStyle(w.querySelector('.mono')).display !== 'none' };
    })""")
    with_logo = {r["id"] for r in index["restaurants"] if r.get("logo")}
    for m in marks:
        if not m["wrap"]:
            problems.append(f"chooser: {m['id']} has no mark")
        elif m["id"] in with_logo and not m["loaded"]:
            problems.append(f"chooser: {m['id']}'s logo didn't load")
        elif m["id"] not in with_logo and m["id"] != "all" and not m["badge"]:
            problems.append(f"chooser: {m['id']} has no logo and no lettered badge")
    page.keyboard.press("Escape")
    page.goto(base + f"#{sorted(with_logo)[0]}")
    page.wait_for_selector("#list .row")
    if not page.evaluate("(() => { const i = document.querySelector('#pickName .logo-wrap img'); return i && i.complete && i.naturalWidth > 0; })()"):
        problems.append("the title doesn't show the chosen restaurant's logo")
    print(f"logos: {len(with_logo)} restaurants with their own mark, {len(marks) - 1 - len(with_logo)} with a lettered badge; title shows the logo")
    ctx.close()
    return problems


def check_wording(env):
    base, ids, cities, browser = env.base, env.ids, env.cities, env.browser
    problems = []
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
        elif url[1:] in ids:  # the order builder too, with its own words for this restaurant
            page.locator("#chips [data-order-open]").click()
            page.wait_for_selector("#order[open]")
            page.keyboard.press("Escape")
        found |= set(page.evaluate(WORDING_JS))
    problems += [f"calls something gluten free in the app's own voice: {s!r}" for s in sorted(found)]
    print(f"wording: {len(found)} sentences say gluten free without saying whose claim it is")
    ctx.close()
    return problems


def check_u1_content_first(env):
    base, ids, cities, browser = env.base, env.ids, env.cities, env.browser
    problems = []
    # U1, content first: the first menu page ever opened shows the certified-or-not card (and the first tip) in full;
    # after that, and on every other restaurant's first visit, it's one line, the menu starts in the top half of the
    # screen with at least four items showing (an out-of-date banner, kept in full on its own restaurant's page, may
    # push it down by its own height), and every folded word is in the sheet
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
        if in_city:
            page.reload()  # a hash change keeps the last city's folds open
        page.wait_for_selector("#cityList .row" if in_city else "#list .row")
        if not in_city:
            if not url:  # the first menu page ever: the card in full, with at most one tip above it
                if not page.locator("#certNote").is_visible() or page.locator("#openStrip").is_visible() or page.locator("#tips > div").count() > 1:
                    problems.append(f"{where}: the first menu page doesn't show the full card with at most one tip")
                page.reload()  # the second visit: folded
                page.wait_for_selector("#list .row")
            if page.locator("#certNote").is_visible() or page.locator("#tips").is_visible() or not page.locator("#openStrip").is_visible():
                problems.append(f"{where}: the card and tips don't fold into one line (on a restaurant's first visit too)")
            if not url and page.locator("#stale").is_visible():
                problems.append("all restaurants: an out-of-date guide shows as a banner, not in the folded line")
        page.wait_for_timeout(300)
        m = page.evaluate(FIRST_SCREEN_JS, "#cityList" if in_city else "#list")
        # and again in a wide font: the iPhone's font isn't the test machine's, so the layout needs room to spare
        wide = add_css(page, '* { font-family: Verdana, "DejaVu Sans", sans-serif !important; }')
        page.wait_for_timeout(200)
        mw = page.evaluate(FIRST_SCREEN_JS, "#cityList" if in_city else "#list")
        wide.remove()
        for label, mm in (("", m), (" in a wide font", mw)):
            want = min(4, len(cities[url[1:]]["places"])) if in_city else 4  # a city may list fewer places
            if mm["top"] > half + mm["stale"] or mm["rows"] < want:
                problems.append(f"{where}{label}: the menu starts at {mm['top']}pt with {mm['rows']} items on the first screen "
                                f"(wanted the top half, {half:.0f}pt{' plus the out-of-date banner' if mm['stale'] else ''}, and 4 or more)")
        found |= set(page.evaluate(WORDING_JS))
        if in_city:
            if cities[url[1:]].get("group") != "uk" and not page.locator("#chips [data-card]").count():  # a UK city needs no card
                problems.append(f"{where}: no coeliac card chip")
            if page.locator("#cityStrip").is_visible():  # after the first visit the introduction is folded (E11): open it
                page.locator("#cityStrip").click()
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
    return problems


def check_u14(env):
    base, ids, browser = env.base, env.ids, env.browser
    problems = []
    # U14: an item the app decided for itself (the guide wasn't plain) says how, on the item and in the sheet;
    # Help has no separate list of notes
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    page = ctx.new_page()
    shown = 0
    for rid in ids:
        built = menu_of(rid)
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
    return problems


def check_u2_and_u3(env):
    base, ids, browser = env.base, env.ids, env.browser
    problems = []
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
            style = add_css(page, css) if css else None
            page.wait_for_timeout(150)
            found = page.evaluate(tags_js, "#list .tag, #avoid .tag")
            checked_tags += len(found)
            bad = [t for t in found if t["lines"] > 1 or not t["under"] or t["wide"]]
            if bad:
                problems.append(f"{where}{label}: {len(bad)} tags wrap or aren't under the name, such as {bad[0]['text']!r}")
            buttons = page.evaluate(status_js)
            hs, dots, cnts = [b["h"] for b in buttons], {b["dot"] for b in buttons}, {b["cnt"] for b in buttons}
            # two when "Needs a change" has nothing in it (it isn't shown); the dot sits beside the count, each in a line
            if len(buttons) not in (2, 3) or max(hs) - min(hs) > 1 or max(hs) > 64 or len(dots) > 1 or len(cnts) > 1:
                problems.append(f"{where}{label}: the status buttons aren't one even row (heights {hs}, dots at {sorted(dots)}, counts at {sorted(cnts)})")
            if style:
                style.remove()
    print(f"tags and status buttons: {checked_tags} tags each on one line under their name; status buttons even")
    ctx.close()
    return problems


def check_u4_and_u5(env):
    base, browser = env.base, env.browser
    problems = []
    # U4 and U5: on All an out-of-date guide is the chooser's tag and a few words in the folded line (the full banner stays on its page), and the
    # header is lighter: the UK / Berlin switch is in the title row, the search box has the full width, share is in
    # the chooser and refresh in Help beside when it last worked
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script("localStorage.setItem('gf-selected', 'all'); Object.defineProperty(navigator, 'share', { value: undefined })")  # no share sheet: the link is copied
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#list .row")
    # an out-of-date guide isn't a banner on All: it's the chooser's Out of date tag, a few words in the folded line,
    # and the full banner on its own page
    page.reload()  # the second visit: the card folded into its line
    page.wait_for_selector("#list .row")
    page.locator("#pickBtn").click()
    page.wait_for_selector("#picker[open]")
    stale_ids = page.evaluate("[...document.querySelectorAll('#pickList .pick-opt[data-r]')].filter((b) => /Out of date/.test(b.textContent)).map((b) => b.dataset.r)")
    page.keyboard.press("Escape")
    if stale_ids:
        if page.locator("#stale").is_visible():
            problems.append("all restaurants: an out-of-date guide shows as a banner")
        if "may be out of date" not in page.locator("#stripText").inner_text():
            problems.append("all restaurants: the folded line doesn't say a guide may be out of date")
        page.goto(base + "#" + stale_ids[0])
        page.wait_for_selector("#list .row")
        if "It covered up to" not in page.locator("#stale").inner_text():
            problems.append(f"{stale_ids[0]}: its own page doesn't have the full out-of-date banner")
    stale_text = ", ".join(stale_ids)
    page.goto(base)
    page.wait_for_selector("#list .row")
    if page.locator("#shareBtn").is_visible() or page.locator("#refreshBtn").is_visible():
        problems.append("the header still has share or refresh buttons")
    if page.locator(".titlebar #region").count() or not page.locator(".top > #region").count():
        problems.append("the sections aren't a row of their own above the title")
    if [b.strip() for b in page.locator("#region button").all_inner_texts()] != want_sections(env.cities):
        problems.append(f"the sections read {page.locator('#region button').all_inner_texts()}, expected {want_sections(env.cities)}")
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
    print(f"header: the sections on a row above the title, search {search['width']:.0f}pt wide; out-of-date guides tagged in the chooser and named in All's folded line; share in the chooser; refresh in Help")
    ctx.close()
    return problems


def check_u6(env):
    base, browser = env.base, env.browser
    problems = []
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
    return problems


def check_u8(env):
    base, index, browser = env.base, env.index, env.browser
    problems = []
    # U8: the guide's own warnings come cross-contact first, and every quote is still there word for word
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    page = ctx.new_page()
    page.goto(base + "#starbucks-uk")
    page.wait_for_selector("#list .row")
    page.locator("#openStrip:visible, #openWarnings:visible").first.click()
    page.wait_for_selector("#warnings[open]")
    labels = page.locator("#warnBody .w-label").all_text_contents()
    sb = menu_of("starbucks-uk")
    sheet = norm_ws(page.locator("#warnBody").text_content())
    if "Cross-contact" not in labels or "Other allergen updates" not in labels or labels.index("Cross-contact") > labels.index("Other allergen updates"):
        problems.append(f"Starbucks warnings aren't cross-contact first: {labels}")
    lost = [n["text"] for n in sb["notices"] if norm_ws(n["text"]) not in sheet]
    if lost:
        problems.append(f"Starbucks warnings lost or changed quotes: {lost[:2]}")
    print(f"warnings order: {labels[:3]}; {len(sb['notices'])} quotes intact")
    ctx.close()
    return problems


def check_u9(env):
    base, ids, index, browser = env.base, env.ids, env.index, env.browser
    problems = []
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
    return problems


def check_u10(env):
    base, browser = env.base, env.browser
    problems = []
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
    return problems


def check_u11(env):
    base, ids, browser = env.base, env.ids, env.browser
    problems = []
    # U11: the Avoid list is folded until it's wanted, and repeated names say which one is which. The restaurant is
    # whichever one has a name twice on its Avoid list (Blank Street's croissants, one per city list)
    import collections
    repeat = next(((rid, n) for rid in ids for n, c in collections.Counter(a["name"] for a in menu_of(rid)["avoid"]).items() if c > 1), (ids[0], None))
    rid, name = repeat
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
    page = ctx.new_page()
    page.goto(base + f"#{rid}")
    page.wait_for_selector("#list .row")
    bs = menu_of(rid)
    if page.locator("#avoidWrap").evaluate("el => el.open") or page.locator("#avoid .row").first.is_visible():
        problems.append(f"{rid}: the Avoid list is open before it's wanted")
    if f"({len(bs['avoid'])})" not in page.locator("#avoidTitle").inner_text():
        problems.append(f"{rid}: the Avoid heading {page.locator('#avoidTitle').inner_text()!r} doesn't count {len(bs['avoid'])}")
    page.locator("#avoidWrap > summary").click()
    if not page.locator("#avoid .row").first.is_visible():
        problems.append(f"{rid}: tapping the Avoid heading doesn't open it")
    small = []
    if name:
        small = page.evaluate("(name) => [...document.querySelectorAll('#avoid .row')].filter((r) => r.querySelector('.nm').childNodes[0].textContent.trim() === name)"
                              ".map((r) => r.querySelector('.nm small')?.textContent || '')", name)
        if len(small) < 2 or len(set(small)) != len(small) or "" in small:
            problems.append(f"{rid}: repeated {name!r} rows don't say which is which: {small}")
    page.locator("#avoidWrap > summary").click()
    page.locator("#q").fill((name or bs["avoid"][0]["name"]).split()[-1].lower())
    if not page.locator("#avoid .row").first.is_visible():
        problems.append(f"{rid}: searching for an Avoid item doesn't open the matches on the Avoid list")
    page.locator("#q").fill("")
    if page.locator("#avoidWrap").evaluate("el => el.open"):
        problems.append(f"{rid}: the Avoid list stays open after the search is cleared")
    page.evaluate("window.scrollTo(0, 0)")
    page.locator('#status [data-k="gluten"]').click()
    if not page.locator("#avoid .row").first.is_visible():
        problems.append(f"{rid}: choosing the Avoid button doesn't open the Avoid list")
    print(f"avoid list ({rid}): folded, counts {len(bs['avoid'])}, opens on a tap, a search and the Avoid button; repeats say which: {small[:2]}")
    ctx.close()
    return problems


def check_u12(env):
    base, ids, cid, browser = env.base, env.ids, env.cid, env.browser
    problems = []
    # U12: the first run's chooser says what the app is and that nothing is certified, in two short paragraphs (the
    # colours are on the count buttons and in Help), with its pointer to the sections switch (the way to the cities)
    # and All restaurants on the first screen; once left, it doesn't come back
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#picker[open]")
    welcome = norm_ws(page.locator("#pickWelcome").inner_text()) if page.locator("#pickWelcome").is_visible() else ""
    if "Nothing here is certified gluten free" not in welcome or page.locator("#pickWelcome p").count() > 2:
        problems.append(f"first run: the welcome is {welcome!r}")
    all_opt = page.locator('#pickList [data-r="all"]').bounding_box()
    if all_opt["y"] + all_opt["height"] > IPHONE["viewport"]["height"]:
        problems.append(f"first run: All restaurants ends at {all_opt['y'] + all_opt['height']:.0f}pt, below the first screen")
    for s in page.evaluate(WORDING_JS):
        problems.append(f"first run welcome calls something gluten free in the app's own voice: {s!r}")
    berlin = page.locator("#pickWelcome p").last.bounding_box()  # the line about UK cities and International
    sheet_box = page.locator("#picker").bounding_box()
    if berlin["y"] + berlin["height"] > min(sheet_box["y"] + sheet_box["height"], IPHONE["viewport"]["height"]):
        problems.append(f"first run: the line about the cities sits at {berlin['y'] + berlin['height']:.0f}pt, below the first screen of the chooser")
    page.locator(f"#pickList [data-r=\"{ids[0]}\"]").click()
    page.wait_for_selector("#list .row")
    page.locator("#pickBtn").click()
    page.wait_for_selector("#picker[open]")
    if page.locator("#pickWelcome").is_visible():
        problems.append("the welcome shows again once a restaurant has been chosen")
    print(f"first run: a two-paragraph welcome, its line about the cities ending at {berlin['y'] + berlin['height']:.0f}pt, All restaurants on the first screen")
    ctx.close()
    return problems


def check_u13(env):
    base, cid, browser, p = env.base, env.cid, env.browser, env.p
    problems = []
    # U13: amber only for items that need a change; banners and notes are neutral. Contrast of the tags, buttons and
    # notes is checked in all five themes
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
            got = page.evaluate(CONTRAST_JS, sel)
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
        got = page.evaluate(CONTRAST_JS, ".tag, .city-intro p, .more summary, .stale, .chg")
        if got["worst"] < 4.5:
            problems.append(f"{theme} theme, {cid}: contrast {got['worst']:.2f}:1 on {got['who']}")
    print("contrast and amber: tags, buttons and notes in all five themes")
    ctx.close()
    return problems


def check_s1(env):
    base, browser = env.base, env.browser
    problems = []
    # S1: saved favourites come first as "Your usuals" (grouped by restaurant on All), not while searching or on a section chip
    def usual(rid, n):
        built = menu_of(rid)
        return [(f"{rid}|{i['section']}|{i['name']}", i["name"]) for i in built["items"] if not i.get("role")][n:n + 2]
    favs = usual("starbucks-uk", 3) + usual("pret-uk", 5)
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script("localStorage.setItem('gf-selected', 'all'); localStorage.setItem('gf-intro-seen', JSON.stringify(['all', 'starbucks-uk']));"
                        f"localStorage.setItem('gf-favourites', JSON.stringify({json.dumps([k for k, _ in favs])}))")
    page = ctx.new_page()
    page.goto(base + "#starbucks-uk")
    page.wait_for_selector("#list .row")
    heads = page.locator("#list .group-h").all_inner_texts()
    first_rows = page.evaluate("[...document.querySelector('#list .card').querySelectorAll('.row .nm')].map((n) => n.childNodes[1]?.textContent || n.childNodes[0].textContent)")
    want = [n for k, n in favs if k.startswith("starbucks-uk")]
    if not heads or not heads[0].startswith("Your usuals") or [x.strip() for x in first_rows] != want:
        problems.append(f"Starbucks: Your usuals is {heads[:1]} with {first_rows}, expected {want}")
    page.locator("#list .card").first.locator(".fav-btn").first.evaluate("el => el.closest('.row').open = true")
    page.locator("#q").fill(want[0][:6])
    if any(h.startswith("Your usuals") for h in page.locator("#list .group-h").all_inner_texts()):
        problems.append("Starbucks: Your usuals still shows while searching")
    page.locator("#q").fill("")
    page.locator("#chips [data-kind]").nth(2).click()  # a section chip
    if any(h.startswith("Your usuals") for h in page.locator("#list .group-h").all_inner_texts()):
        problems.append("Starbucks: Your usuals shows on a section chip")
    page.goto(base)
    page.reload()
    page.wait_for_selector("#list .row")
    subs = page.evaluate("[...document.querySelectorAll('#list > *')].slice(0, 5).map((e) => e.className + ':' + e.textContent.slice(0, 14))")
    names = page.evaluate("[...document.querySelectorAll('#list > .sub-h')].slice(0, 2).map((e) => e.textContent)")
    if not page.locator("#list .group-h").first.inner_text().startswith("Your usuals") or names != ["Pret A Manger", "Starbucks"]:
        problems.append(f"All: Your usuals should list favourites first, grouped by restaurant ({names}, {subs})")
    print(f"your usuals: {len(favs)} favourites first on a restaurant and on All, hidden while searching")
    ctx.close()
    return problems


def check_f1(env):
    base, browser = env.base, env.browser
    problems = []
    # F1: the screen stays lit while a staff or coeliac card is open, comes back after the phone let go of it, and the card is in large type
    wake_mock = ("window.__wl = { requests: 0, released: 0, last: null };"
                 "Object.defineProperty(navigator, 'wakeLock', { value: { request: async () => { const ls = [];"
                 " const s = { addEventListener: (t, f) => ls.push(f), release: async () => { window.__wl.released++; ls.forEach((f) => f()); } };"
                 " window.__wl.requests++; window.__wl.last = s; return s; } } });")
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script(wake_mock + "localStorage.setItem('gf-selected', 'all');")
    page = ctx.new_page()
    page.goto(base + "#knoops-uk")
    page.wait_for_selector("#list .row")
    row = page.locator("#list .row").first
    row.locator("summary").click()
    row.locator(".staff-btn").click()
    page.wait_for_selector("#staff[open]")
    wl = lambda: page.evaluate("({ requests: window.__wl.requests, released: window.__wl.released })")
    if wl()["requests"] != 1:
        problems.append(f"Show staff: the screen isn't kept on ({wl()})")
    size = page.evaluate("parseFloat(getComputedStyle(document.querySelector('#staff .staff-name')).fontSize)")
    over = page.evaluate("(() => { const d = document.getElementById('staff'); return d.scrollWidth - d.clientWidth; })()")
    if size < 36 or over > 1:
        problems.append(f"Show staff: the card's type is {size}px and {over}px too wide")
    page.evaluate("window.__wl.last.release()")  # the phone lets go when the app is hidden
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_timeout(200)
    if wl()["requests"] != 2:
        problems.append(f"Show staff: the screen isn't kept on again on coming back ({wl()})")
    page.locator("#staff .link-btn").click()
    page.wait_for_timeout(100)
    if wl()["released"] != 2:
        problems.append(f"Show staff: the screen lock isn't let go of when the card closes ({wl()})")
    page.evaluate("window.scrollTo(0, 0)")  # opening the item scrolled the page, which folds the sections away
    page.wait_for_selector(".top:not(.collapsed)")
    page.locator('#region [data-region="intl"]').click()
    page.wait_for_selector("#cityList .row")
    page.locator("#chips [data-card]").click()
    page.wait_for_selector("#gfcard[open]")
    if wl()["requests"] != 3:
        problems.append(f"Coeliac card: the screen isn't kept on ({wl()})")
    page.locator("#gfcard .link-btn").click()
    page.wait_for_timeout(100)
    if wl()["released"] != 3:
        problems.append(f"Coeliac card: the screen lock isn't let go of ({wl()})")
    print("wake lock: kept on for the staff card and the coeliac card, again on returning, let go on Done; staff card type", size)
    ctx.close()
    return problems


def check_f4(env):
    base, cid, browser = env.base, env.cid, env.browser
    problems = []
    # F4: "Something wrong?" on an item and a place opens a ready message (and, for the owner, a GitHub issue)
    SHARE_MOCK = "window.__shared = null; Object.defineProperty(navigator, 'share', { value: async (d) => { window.__shared = d; } });"
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script(SHARE_MOCK + "localStorage.setItem('gf-selected', 'all');")
    page = ctx.new_page()
    page.goto(base + "#knoops-uk")
    page.wait_for_selector("#list .row")
    row = page.locator("#list .row").first
    item_name = page.evaluate(ROWS_JS)[0]["name"]
    row.locator("summary").click()
    row.locator("[data-wrong]").click()
    page.wait_for_selector("#report[open]")
    msg = page.locator("#reportText").input_value()
    if not all(w in msg for w in ("Restaurant: Knoops", f"Item: {item_name}", "The app shows:", "Guide: ", "Link: ")) or not msg.endswith("What happened: "):
        problems.append(f"Something wrong?: the message is {msg!r}")
    if page.locator("#reportIssue").is_visible():
        problems.append("Something wrong?: the GitHub issue button shows without the owner's key")
    page.locator("#reportText").press("End")
    page.keyboard.type("It has changed")
    page.locator("#reportSend").click()
    page.wait_for_timeout(200)
    shared = page.evaluate("window.__shared")
    if not shared or "It has changed" not in shared["text"] or page.locator("#report[open]").count():
        problems.append(f"Something wrong?: sending shared {shared}")
    page.goto(base + f"#{cid}")
    page.wait_for_selector("#cityList .row")
    place = page.locator("#cityList .row").first
    place.locator("summary").click()
    place.locator("[data-wrong-place]").click()
    page.wait_for_selector("#report[open]")
    msg = page.locator("#reportText").input_value()
    if "Place: " not in msg or "List checked: " not in msg or "Link: " not in msg:
        problems.append(f"Something wrong?: the place message is {msg!r}")
    ctx.close()
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script("localStorage.setItem('gf-github-key', 'k'); localStorage.setItem('gf-selected', 'all');")
    page = ctx.new_page()
    page.goto(base + "#knoops-uk")
    page.wait_for_selector("#list .row")
    page.locator("#list .row").first.locator("summary").click()
    page.locator("#list .row").first.locator("[data-wrong]").click()
    page.wait_for_selector("#report[open]")
    if not page.locator("#reportIssue").is_visible():
        problems.append("Something wrong?: the owner has no GitHub issue button")
    print("something wrong: a ready message for an item and a place, sent through the share sheet; the owner also gets a GitHub issue")
    ctx.close()
    return problems


def check_f6(env):
    base, ids, browser = env.base, env.ids, env.browser
    problems = []
    # F6: a link to one item opens its restaurant, scrolls to it and opens it; every item in a guide has its own link;
    # a link to an item that has changed lands on the restaurant with a note
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script(SHARE_MOCK)
    page = ctx.new_page()
    for rid in ids:
        page.goto(base + f"#{rid}")
        page.wait_for_selector("#list .row")
        page.evaluate("document.getElementById('avoidWrap').open = true")
        slugs = page.evaluate("[...document.querySelectorAll('#list .row, #avoid .row')].map((d) => d.dataset.slug)")
        if len(slugs) != len(set(slugs)) or "" in slugs or None in slugs:
            dupes = sorted({x for x in slugs if slugs.count(x) > 1})
            problems.append(f"{rid}: {len(dupes)} item links are shared by more than one item, such as {dupes[:2]}")
    page.goto(base + "#starbucks-uk")
    page.wait_for_selector("#list .row")
    want = page.evaluate("document.querySelectorAll('#list .row')[5].dataset.slug")
    avoid_slug = page.evaluate("(() => { document.getElementById('avoidWrap').open = true; return document.querySelector('#avoid .row').dataset.slug; })()")
    ctx.close()
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script(SHARE_MOCK)
    page = ctx.new_page()
    for target, where in ((want, "#list"), (avoid_slug, "#avoid")):
        page.goto(base + f"#starbucks-uk/{target}")  # a fresh visit: the menus load before the link is followed
        page.wait_for_selector(f'{where} .row[data-slug="{target}"]', state="attached")
        page.wait_for_timeout(300)
        row = page.locator(f'{where} .row[data-slug="{target}"]').first
        box = row.bounding_box()
        if not row.evaluate("el => el.open") or box is None or not (0 <= box["y"] < IPHONE["viewport"]["height"]):
            problems.append(f"the link to {target!r} doesn't open the item on screen (box {box})")
        if where == "#avoid" and not page.locator("#avoidWrap").evaluate("el => el.open"):
            problems.append("the link to an Avoid item leaves the Avoid list folded")
    row.locator("[data-share-item]").click()
    page.wait_for_timeout(150)
    shared = page.evaluate("window.__shared")
    if not shared or not shared["url"].endswith(f"#starbucks-uk/{avoid_slug}"):
        problems.append(f"Share this item shared {shared}")
    page.goto(base + "#starbucks-uk/no-such-drink-any-more")
    page.wait_for_selector("#toast:not([hidden])")
    if "changed" not in page.locator("#toast").inner_text() or "Starbucks" not in page.locator("#pickName").inner_text():
        problems.append("a link to an item that has changed doesn't land on its restaurant with a note")
    print(f"item links: unique within every guide, open and scroll to the item, Avoid items too, shared from the row ({want})")
    ctx.close()
    return problems


def check_s2(env):
    base, cid, browser = env.base, env.cid, env.browser
    problems = []
    # S2: on Berlin time the app offers Berlin once; on UK time again, it offers the way back
    def tz_ctx(zone, init=""):
        c = browser.new_context(color_scheme="light", timezone_id=zone, **IPHONE)
        c.add_init_script("localStorage.setItem('gf-selected', 'all');" + init)
        return c
    ctx = tz_ctx("Europe/Berlin")
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#tzOffer:not([hidden])")
    if "You're on Berlin time" not in page.locator("#tzOffer").inner_text():
        problems.append(f"Berlin time: the offer says {page.locator('#tzOffer').inner_text()!r}")
    page.locator('#tzOffer [data-tz="yes"]').click()
    page.wait_for_selector("#cityList .row")
    page.reload()
    page.wait_for_selector("#cityList .row")
    page.wait_for_timeout(300)
    if page.locator("#tzOffer").is_visible():
        problems.append("Berlin time: the offer comes back after it was accepted")
    ctx.close()
    ctx = tz_ctx("Europe/Berlin")
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#tzOffer:not([hidden])")
    page.locator('#tzOffer [data-tz="no"]').click()
    page.reload()
    page.wait_for_selector("#list .row")
    page.wait_for_timeout(300)
    if page.locator("#tzOffer").is_visible() or page.locator("#ukView").is_hidden():
        problems.append("Berlin time: after Not now the offer returns, or the UK menus went")
    ctx.close()
    ctx = tz_ctx("Europe/London", f"localStorage.setItem('gf-region', '{cid}'); localStorage.setItem('gf-tz-asked', 'Europe/Berlin');")
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#tzOffer:not([hidden])")
    if "back on UK time" not in page.locator("#tzOffer").inner_text():
        problems.append(f"UK time again: the offer says {page.locator('#tzOffer').inner_text()!r}")
    page.locator('#tzOffer [data-tz="yes"]').click()
    page.wait_for_selector("#list .row")
    if page.locator("#cityView").is_visible():
        problems.append("UK time again: accepting didn't go back to the UK menus")
    ctx.close()
    ctx = tz_ctx("Europe/London")
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#list .row")
    page.wait_for_timeout(300)
    if page.locator("#tzOffer").is_visible():
        problems.append("UK time: the app offers Berlin though the phone is on UK time")
    print("time zone: Berlin offered once on Berlin time (yes or not now), UK offered again on returning, nothing on UK time")
    ctx.close()
    return problems


def check_s3(env):
    base, cid, cities, browser = env.base, env.cid, env.cities, env.browser
    problems = []
    # S3: "Open near me" does both in one tap, and a second tap turns both off
    alex, nearest = ALEX, nearest_places(cities[cid], ALEX)
    ctx = browser.new_context(color_scheme="light", geolocation=alex, permissions=["geolocation"], **IPHONE)
    page = ctx.new_page()
    page.clock.set_fixed_time("2026-11-01T19:00:00+01:00")
    page.goto(base + f"#{cid}")
    page.wait_for_selector("#cityList .row")
    listed = lambda: [n.split(chr(10))[0].strip().lstrip("★").strip() for n in page.locator("#cityList .row .nm").all_inner_texts()]
    pressed = lambda sel: page.locator(f"#chips {sel}").get_attribute("aria-pressed")
    page.locator("#chips [data-nearopen]").click()
    page.wait_for_selector('#chips [data-nearopen][aria-pressed="true"]')
    open_nearest = [pl["name"] for pl in nearest if any(closes(h) > 19 * 60 for h in sunday(pl))]
    states = {"all": pressed("[data-kind='all']")}
    if listed() != open_nearest or states != {"all": "false"}:
        problems.append(f"Open near me: shows {listed()}, expected {open_nearest}; chips pressed: {states}")
    page.locator("#chips [data-nearopen]").click()
    if pressed("[data-nearopen]") != "false" or pressed('[data-kind="all"]') != "true":
        problems.append("Open near me: a second tap doesn't turn it off")
    # the distance order doesn't follow you to another city (a small one has no chip to turn it off), and All clears it
    page.locator("#chips [data-nearopen]").click()
    page.wait_for_selector('#chips [data-nearopen][aria-pressed="true"]')
    small = next((c for c, city in cities.items() if len(city["places"]) < 4), None)
    if small:
        page.goto(base + f"#{small}")
        page.wait_for_selector("#cityList .row")
        if page.evaluate("document.body.classList.contains('searching')"):
            problems.append(f"Open near me in {cid} left {small} sorted by distance, its introduction hidden, with no chip to undo it")
        page.goto(base + f"#{cid}")
        page.wait_for_selector("#cityList .row")
    page.locator("#chips [data-nearopen]").click()
    page.wait_for_selector('#chips [data-nearopen][aria-pressed="true"]')
    page.locator('#chips [data-kind="all"]').click()
    if page.evaluate("document.body.classList.contains('searching')") or pressed('[data-kind="all"]') != "true":
        problems.append("Open near me: All doesn't clear its distance order")
    ctx.close()
    # with location refused it shows what's open today, pressed, and a second tap turns it off
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    page = ctx.new_page()
    page.clock.set_fixed_time("2026-11-01T19:00:00+01:00")
    page.goto(base + f"#{cid}")
    page.wait_for_selector("#cityList .row")
    page.locator("#chips [data-nearopen]").click()
    page.wait_for_selector('#chips [data-nearopen][aria-pressed="true"]')
    if sorted(listed()) != sorted(open_nearest):
        problems.append(f"Open near me without location: shows {sorted(listed())}, expected what's open today {sorted(open_nearest)}")
    page.locator("#chips [data-nearopen]").click()
    if pressed("[data-nearopen]") != "false" or pressed('[data-kind="all"]') != "true":
        problems.append("Open near me without location: a second tap doesn't turn it off")
    print(f"open near me: {len(open_nearest)} places open on Sunday evening, nearest first, one tap on, one tap off; "
          "not carried to another city, cleared by All; without location, what's open today, pressed")
    ctx.close()
    return problems


def check_s4_and_s5(env):
    base, cid, cities, browser = env.base, env.cid, env.cities, env.browser
    problems = []
    # S4 and S5: a search that finds nothing here shows matches elsewhere, and a way to send a menu
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
    page = ctx.new_page()
    page.goto(base + "#knoops-uk")
    page.wait_for_selector("#list .row")
    page.locator("#q").fill("burger")
    page.wait_for_selector("#list .empty")
    link = page.locator('#list [data-elsewhere="all"]')
    if not re.match(r"\d+ match(es)? at (another restaurant|other restaurants)", link.inner_text()):
        problems.append(f"empty search at Knoops: the link to other restaurants says {link.inner_text() if link.count() else None!r}")
    else:
        link.click()
        page.wait_for_selector("#list .rest-h")
        if page.locator("#q").input_value() != "burger" or "Five Guys" not in " ".join(page.locator("#list .rest-h").all_inner_texts()):
            problems.append("empty search at Knoops: the link doesn't open All with the same search")
    place = cities[cid]["places"][0]["name"]
    page.goto(base + "#starbucks-uk")
    page.wait_for_selector("#list .row")
    page.locator("#q").fill(place.split()[0])
    page.wait_for_selector("#list .empty")
    if not page.locator(f'#list [data-elsewhere="{cid}"]').count():
        problems.append(f"empty search for a Berlin place ({place}): no link to the Berlin places")
    else:
        page.locator(f'#list [data-elsewhere="{cid}"]').click()
        page.wait_for_selector("#cityList .row")
        if place not in page.locator("#cityList").inner_text() or page.locator("#q").input_value() != place.split()[0]:
            problems.append("empty search: the link to Berlin doesn't keep the search")
    page.locator("#q").fill("burger")
    page.wait_for_selector("#cityList .empty")
    if not page.locator('#cityList [data-elsewhere="uk"]').count():
        problems.append("empty search in Berlin: no link to matches on the UK menus")
    else:
        page.locator('#cityList [data-elsewhere="uk"]').click()
        page.wait_for_selector("#list .row")
        if page.locator("#q").input_value() != "burger" or page.locator("#ukView").is_hidden():
            problems.append("empty search in Berlin: the link doesn't open the UK menus with the same search")
    page.locator("#q").fill("zzzzzz")
    page.wait_for_selector("#list .empty")
    page.locator("#list [data-addmenu]").click()
    page.wait_for_selector("#upload[open]")
    page.locator("#uploadClose").click()
    page.locator("#pickBtn").click()
    page.wait_for_selector("#picker[open]")
    page.locator("#pickList [data-addmenu]").click()
    page.wait_for_selector("#upload[open]")
    if page.locator("#picker[open]").count():
        problems.append("Add a menu from the chooser leaves the chooser open")
    print("empty searches: matches at other restaurants, in Berlin and on the UK menus; Add a menu from the chooser and under an empty search")
    ctx.close()
    return problems


def check_f2(env):
    base, cid, cities, browser = env.base, env.cid, env.cities, env.browser
    problems = []
    # F2: favourites travel in a link. The link holds exactly what's saved; opening it on another phone sorts each one
    # against the menus as they are now: new ones are added, saved ones skipped, a renamed section followed, and
    # anything now on the Avoid list or gone is listed but not added
    sb = menu_of("starbucks-uk")
    pret = menu_of("pret-uk")
    dishes = [i for i in sb["items"] if not i.get("role")]
    key = lambda rid, i: f"{rid}|{i['section']}|{i['name']}"
    moved = next(i for i in pret["items"] if not i.get("role") and sum(" ".join(x["name"].lower().split()) == " ".join(i["name"].lower().split()) for x in pret["items"]) == 1)
    place = cities[cid]["places"][0]["name"]
    mine = [key("starbucks-uk", dishes[0]), key("starbucks-uk", dishes[1]), f"city:{cid}|{place}"]
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script(SHARE_MOCK + "localStorage.setItem('gf-selected', 'all');"
                        f"localStorage.setItem('gf-favourites', JSON.stringify({json.dumps(mine)}))")
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#list .row")
    page.locator('#chips [data-kind="fav"]').click()
    page.locator("#list [data-sharefavs]").click()
    page.wait_for_timeout(150)
    url = (page.evaluate("window.__shared") or {}).get("url", "")
    code = url.split("#favs=", 1)[-1]
    try:
        carried = json.loads(base64.urlsafe_b64decode(code + "=" * (-len(code) % 4)))["f"]
    except Exception:
        carried = None
    if "#favs=" not in url or sorted(carried or []) != sorted(mine):
        problems.append(f"Share my favourites: the link {url[:60]!r} holds {carried}, expected {mine}")
    ctx.close()
    link_keys = [key("starbucks-uk", dishes[0]),                         # new on this phone: added
                 key("starbucks-uk", dishes[1]),                         # already saved here: skipped
                 f"pret-uk|An old section name|{moved['name']}",         # its section was renamed: follows its name
                 key("starbucks-uk", sb["avoid"][0]),                    # now on the Avoid list: not added
                 "knoops-uk|Hot chocolate|A drink that has gone",        # gone: not added
                 f"city:{cid}|{place}"]                                  # a Berlin place: added
    code = base64.urlsafe_b64encode(json.dumps({"v": 1, "f": link_keys}).encode()).decode().rstrip("=")
    ctx = browser.new_context(color_scheme="light", **IPHONE)  # a new phone: no restaurant chosen yet
    ctx.add_init_script(f"if (!sessionStorage.getItem('seeded')) {{ sessionStorage.setItem('seeded', '1'); "
                        f"localStorage.setItem('gf-favourites', JSON.stringify({json.dumps([link_keys[1]])})); }}")
    page = ctx.new_page()
    page.goto(base + "#favs=" + code)
    page.wait_for_selector("#favImport[open]")
    body = norm_ws(page.locator("#favImportBody").inner_text())
    for want in ("To add (3)", "1 is already saved", "Not added (2)", "is now on the Avoid list", "is no longer in the guide"):
        if want not in body:
            problems.append(f"favourites link: the sheet doesn't say {want!r} ({body[:200]!r})")
    if page.locator("#picker[open]").count() or "favs=" in page.url:
        problems.append("favourites link: the chooser opened over it, or the link stays in the address")
    page.locator("#favImportAdd").click()
    saved = set(page.evaluate("JSON.parse(localStorage.getItem('gf-favourites'))"))
    want = {link_keys[0], link_keys[1], key("pret-uk", moved), link_keys[5]}
    if saved != want:
        problems.append(f"favourites link: saved {sorted(saved)}, expected {sorted(want)}")
    page.reload()
    page.wait_for_selector("#list .row")
    page.wait_for_timeout(300)
    if page.locator("#favImport[open]").count():
        problems.append("favourites link: reloading asks again")
    page.goto(base + "#favs=not-a-real-link")
    page.wait_for_selector("#toast:not([hidden])")
    if "damaged" not in page.locator("#toast").inner_text():
        problems.append("favourites link: a damaged link doesn't say so")
    # V7: a note that comes with a link is shown in full before anything is added, and a note on an Avoid row is left out
    avoid_key = key("starbucks-uk", sb["avoid"][0])
    code = base64.urlsafe_b64encode(json.dumps({"v": 2, "f": [link_keys[0]], "n": {link_keys[0]: "ask for a clean jug", avoid_key: "staff said it is fine"}}).encode()).decode().rstrip("=")
    page.goto(base + "#favs=" + code)
    page.wait_for_selector("#favImport[open]")
    body = norm_ws(page.locator("#favImportBody").inner_text())
    if "Notes in the link (1)" not in body or "ask for a clean jug" not in body or "staff said it is fine" in body:
        problems.append(f"favourites link: the notes aren't shown before adding, or a note on an Avoid row got through ({body[:200]!r})")
    print(f"favourites link: round trip of {len(mine)}; opening one adds 3, skips 1 already saved, follows a renamed section, leaves out 2; notes shown first")
    ctx.close()
    return problems


def check_o5(env):
    browser = env.browser
    problems = []
    # O5: a new release loads without restarting the app. The first service worker doesn't reload the page; a newer one
    # reloads it by itself when nothing is open, and otherwise offers "Updated. Tap to reload"
    tmp = Path(tempfile.mkdtemp()) / "site"
    shutil.copytree(SITE, tmp)
    httpd2, base2 = serve(tmp)
    v = int(re.search(r"const APP_VERSION = (\d+);", (SITE / "app.js").read_text(encoding="utf-8")).group(1))

    def release(n):
        for name, old, new in (("app.js", r"const APP_VERSION = \d+;", f"const APP_VERSION = {n};"),
                               ("sw.js", r'const CACHE = "gf-menus-v\d+"', f'const CACHE = "gf-menus-v{n}"')):
            f = tmp / name
            f.write_text(re.sub(old, new, f.read_text(encoding="utf-8")), encoding="utf-8")

    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
    page = ctx.new_page()
    page.goto(base2)
    page.wait_for_selector("#list .row")
    page.evaluate("navigator.serviceWorker.ready")
    for _ in range(50):
        if page.evaluate("!!navigator.serviceWorker.controller"):
            break
        page.wait_for_timeout(100)
    page.wait_for_timeout(500)
    version = lambda: page.evaluate("document.documentElement.dataset.version")
    if page.evaluate("performance.getEntriesByType('navigation')[0].type") == "reload" or version() != str(v):
        problems.append("new release: the first visit reloaded itself")
    release(v + 1)
    try:
        with page.expect_navigation(timeout=20000):
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_selector("#list .row")
    except Exception as e:
        problems.append(f"new release: coming back to the app didn't load it ({e.__class__.__name__})")
    if version() != str(v + 1):
        problems.append(f"new release: the app is on {version()} after an idle update, expected {v + 1}")
    release(v + 2)
    page.locator("#list .row").first.locator("summary").click()  # reading an item: don't pull the page away
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    try:
        page.wait_for_selector("#updateBar:not([hidden])", timeout=20000)
        if version() != str(v + 1):
            problems.append("new release: the app reloaded while an item was open")
        with page.expect_navigation(timeout=20000):
            page.locator("#updateBar").click()
        page.wait_for_selector("#list .row")
        if version() != str(v + 2):
            problems.append(f"new release: tapping Updated loaded {version()}, expected {v + 2}")
    except Exception as e:
        problems.append(f"new release: with an item open there's no 'Updated. Tap to reload' ({e.__class__.__name__})")
    print(f"new release: first visit stays put; {v} -> {v + 1} reloads quietly; {v + 1} -> {v + 2} waits for a tap while an item is open")
    ctx.close()
    httpd2.shutdown()
    shutil.rmtree(tmp.parent, ignore_errors=True)
    return problems


def check_o8(env):
    ids, index, browser = env.ids, env.index, env.browser
    problems = []
    # O8: a quick start on a weak signal. The app's own files come from the phone at once and the menus saved on the
    # phone show straight away; newer menus replace them when they arrive ("Menus updated"). Unchanged menus are
    # checked rather than downloaded again, and a signal too weak to answer in time still says it's the saved copy
    tmp = Path(tempfile.mkdtemp()) / "site"
    shutil.copytree(SITE, tmp)
    lag = {"s": 0}
    httpd3, base3 = serve(tmp, lag)
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
    page = ctx.new_page()
    page.goto(base3)
    page.wait_for_selector("#list .row")
    page.evaluate("navigator.serviceWorker.ready")
    for _ in range(50):
        if page.evaluate("!!navigator.serviceWorker.controller"):
            break
        page.wait_for_timeout(100)
    page.reload()  # controlled now, so the menus go through the service worker
    page.wait_for_selector("#list .row")
    page.wait_for_timeout(1000)
    # 1. menus that haven't changed come back "not modified"
    httpd3.answered.clear()
    page.reload()
    page.wait_for_selector("#list .row")
    page.wait_for_timeout(1000)
    codes = [c for path, c in httpd3.answered if path.startswith("/data/restaurants.json")]
    if 304 not in codes:
        problems.append(f"weak signal: unchanged menus were downloaded again (answers {codes}, expected 304 not modified)")
    # 2. a slow signal: the app is on screen before anything arrives, then the newer menus replace the saved ones
    rf = tmp / "data" / "r" / f"{ids[0]}.json"
    d = json.loads(rf.read_text(encoding="utf-8"))
    d["tips"] = d.get("tips", []) + ["Weak signal check: a newer menu."]
    d["hash"] = "newer-" + d.get("hash", "")  # as the build would: a changed menu gets a new fingerprint
    rf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    ix = json.loads((tmp / "data" / "restaurants.json").read_text(encoding="utf-8"))
    ix["built"] = "2099-01-01T00:00:00Z"
    next(r for r in ix["restaurants"] if r["id"] == ids[0])["hash"] = d["hash"]
    (tmp / "data" / "restaurants.json").write_text(json.dumps(ix, ensure_ascii=False), encoding="utf-8")
    # 1.2s a file: slower than the app may take to appear, but every menu still answers within the 4s wait,
    # even though the browser fetches only six at a time
    lag["s"] = 1.2
    t0 = time.monotonic()
    page.reload(wait_until="commit")
    page.wait_for_selector("#list .row", timeout=15000)
    shown = time.monotonic() - t0
    if shown > 0.8:
        problems.append(f"weak signal: the app took {shown:.1f}s to appear, waiting on a network that takes 1.2s")
    try:
        page.locator("#toast", has_text="Menus updated").wait_for(state="visible", timeout=15000)
    except Exception:
        problems.append(f"weak signal: no 'Menus updated' when the newer menus arrived (toast: {page.locator('#toast').inner_text()!r})")
    if "Weak signal check" not in (page.evaluate("localStorage.getItem('gf-data-v2')") or ""):
        problems.append("weak signal: the newer menus weren't kept on the phone")
    if "offline" in page.locator("#guideLine").inner_text().lower():
        problems.append("weak signal: a slow answer that came in time was called offline")
    # 3. too slow to answer in time: still on screen at once, and the header says these are the saved menus
    lag["s"] = 6
    t0 = time.monotonic()
    page.reload(wait_until="commit")
    page.wait_for_selector("#list .row", timeout=15000)
    shown2 = time.monotonic() - t0
    page.wait_for_timeout(9000)  # the index, then each menu, waits up to 4s for the network before using the saved copy
    line = page.locator("#guideLine").inner_text()
    if shown2 > 1.5 or "offline" not in line.lower():
        problems.append(f"very weak signal: the app took {shown2:.1f}s to appear and the header says {line!r}")
    lag["s"] = 0
    print(f"weak signal: unchanged menus answered {sorted(set(codes))}; on screen in {shown:.1f}s with a 1.2s network, then "
          f"'Menus updated'; in {shown2:.1f}s with a 6s one, then {line!r}")
    ctx.close()
    httpd3.shutdown()
    shutil.rmtree(tmp.parent, ignore_errors=True)
    return problems


def check_o4(env):
    base, browser = env.base, env.browser
    problems = []
    # O4: a simple error log. The last 20 errors stay on the phone, and Help copies them with the app version and menu date
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=base.rstrip("/"))
    ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
    page = ctx.new_page()  # no pageerror handler here: the errors are on purpose
    page.goto(base)
    page.wait_for_selector("#list .row")
    v = re.search(r"const APP_VERSION = (\d+);", (SITE / "app.js").read_text(encoding="utf-8")).group(1)
    page.evaluate("setTimeout(() => { throw new Error('Test error one'); })")
    page.evaluate("void Promise.reject(new Error('Test rejection two'))")
    page.wait_for_timeout(300)
    logged = json.loads(page.evaluate("localStorage.getItem('gf-errors')"))
    if [e["msg"] for e in logged] != ["Uncaught Error: Test error one", "Unhandled: Test rejection two"] or any(e["v"] != int(v) for e in logged):
        problems.append(f"error log: recorded {[e['msg'] for e in logged]}")
    for n in range(25):
        page.evaluate(f"setTimeout(() => {{ throw new Error('Burst {n}'); }})")
    page.wait_for_timeout(500)
    logged = json.loads(page.evaluate("localStorage.getItem('gf-errors')"))
    if len(logged) != 20 or logged[-1]["msg"] != "Uncaught Error: Burst 24" or logged[0]["msg"] != "Uncaught Error: Burst 5":
        problems.append(f"error log: kept {len(logged)} errors, from {logged[0]['msg']!r} to {logged[-1]['msg']!r}; expected the last 20")
    page.reload()
    page.wait_for_selector("#list .row")
    page.locator("#infoBtn").click()
    page.wait_for_selector("#info[open]")
    if "20 errors recorded" not in page.locator("#errorCount").inner_text():
        problems.append(f"error log: Help says {page.locator('#errorCount').inner_text()!r} after a reload, expected 20 errors")
    page.locator("#copyDetails").click()
    page.wait_for_timeout(300)
    copied = page.evaluate("navigator.clipboard.readText()")
    built = json.loads((SITE / "data" / "restaurants.json").read_text(encoding="utf-8"))["built"]
    for want in (f"app version {v}", f"Menus built: {built}", "Last 20 errors:", "Burst 24", "(v" + v + ")"):
        if want not in copied:
            problems.append(f"error log: the copied details don't include {want!r}")
    if re.search(r"Burst [0-4](?!\d)", copied):
        problems.append("error log: the copied details include an error older than the last 20")
    print(f"error log: {len(logged)} kept of 30, survives a reload, copied with version {v} and menu date")
    ctx.close()
    return problems


def check_f12(env):
    base, ids, browser = env.base, env.ids, env.browser
    problems = []
    # F12: what changed since you last looked. The phone keeps each restaurant's menu as you last saw it and compares
    # the newest with that, so a guide you never saw (two out between visits) can't hide an item that now contains gluten
    sb_now = menu_of("starbucks-uk")
    trim = lambda d: {"source": d["source"], "guide": {k: d["guide"][k] for k in ("title", "version") if d["guide"].get(k)},
                      "items": [{k: i[k] for k in ("name", "section", "order", "ok", "not", "note") if k in i} for i in d["items"]],
                      "avoid": [{k: a[k] for k in ("name", "section", "gluten") if k in a} for a in d["avoid"]]}
    COUNT_LABELS = (("nowAvoid", "now contain gluten"), ("nowOk", "no longer to avoid"), ("changed", "ordered differently"),
                    ("added", "new"), ("removed", "gone"))
    count_text = lambda c: ", ".join(f"{len(c[k])} {label}" for k, label in COUNT_LABELS if c[k])

    def looked_ctx(baseline, extra=""):
        c = browser.new_context(color_scheme="light", **IPHONE)
        c.add_init_script("if (!sessionStorage.getItem('seeded')) { sessionStorage.setItem('seeded', '1');"
                          "localStorage.setItem('gf-selected', 'all'); localStorage.setItem('gf-changes-seen', '[]');"
                          f"localStorage.setItem('gf-looked', JSON.stringify({{'starbucks-uk': {json.dumps(baseline)}}})); {extra} }}")
        return c

    # 1. you last looked at the real summer drinks guide; two guides have come out since
    summer = json.loads((SITE.parent / "tests" / "fixtures" / "changes" / "starbucks-drinks-summer-2026.json").read_text(encoding="utf-8"))
    want = py_changes.compare(summer, trim(sb_now))
    ctx = looked_ctx(summer)
    page = ctx.new_page()
    page.goto(base + "#starbucks-uk")
    page.wait_for_selector("#list .row")
    news = norm_ws(page.locator("#news").inner_text()) if page.locator("#news").is_visible() else ""
    if "has new guides" not in news or f"Since the {want['since']} guide you last looked at" not in news or count_text(want) not in news:
        problems.append(f"since you last looked (summer guide): the note says {news!r}, expected {count_text(want)!r} since {want['since']}")
    page.locator("#news [data-news]").click()
    page.wait_for_selector("#changes[open]")
    parts = page.locator("#changesBody h4").all_text_contents()
    if parts != ["Since you last looked", "This guide's own list"]:
        problems.append(f"since you last looked: What changed shows {parts}, expected both lists")
    page.keyboard.press("Escape")
    ctx.close()

    # 2. a drink that had no gluten ingredients when you last looked is now on the Avoid list, and one is ordered differently
    gone_bad = sb_now["avoid"][0]
    moved = next(i for i in sb_now["items"] if i.get("order") in ("any", "except") and not i.get("role"))
    base_menu = trim(sb_now)
    base_menu["source"], base_menu["guide"] = "an-older-guide.pdf", {"title": "Spring Beverages"}
    base_menu["avoid"] = [a for a in base_menu["avoid"] if a["name"] != gone_bad["name"]]
    base_menu["items"].append({"name": gone_bad["name"], "section": gone_bad["section"], "order": "asis"})
    for i in base_menu["items"]:
        if i["name"] == moved["name"] and i["section"] == moved["section"]:
            i.update(order="asis", ok=[], **{"not": []})
    want = py_changes.compare(base_menu, trim(sb_now))
    ctx = looked_ctx(base_menu)
    page = ctx.new_page()
    page.goto(base + "#starbucks-uk")
    page.wait_for_selector("#list .row")
    row = page.locator("#news .news-row").first
    if not row.count() or "bad" not in (row.get_attribute("class") or "") or "1 now contain gluten" not in row.inner_text():
        problems.append(f"since you last looked: no red note for the drink that now contains gluten ({row.inner_text() if row.count() else None!r})")
    page.locator("#q").fill(gone_bad["name"])
    avoid_row = page.locator("#avoid .row", has=page.locator(".nm", has_text=gone_bad["name"])).first
    if not avoid_row.count() or "Now contains gluten" not in avoid_row.inner_text():
        problems.append(f"since you last looked: {gone_bad['name']!r} on the Avoid list isn't marked 'Now contains gluten'")
    else:
        avoid_row.locator("summary").click()
        if "you last looked at" not in avoid_row.locator(".detail").inner_text():
            problems.append("since you last looked: the item's note doesn't say it's since the guide you last looked at")
    page.locator("#q").fill(moved["name"])
    mrow = page.locator("#list .row", has=page.locator(".nm", has_text=moved["name"])).first
    if not mrow.count() or "Order changed" not in mrow.inner_text():
        problems.append(f"since you last looked: {moved['name']!r} isn't marked 'Order changed'")
    page.locator("#q").fill("")
    page.locator("#news [data-news]").first.click()
    page.wait_for_selector("#changes[open]")
    body = page.locator("#changesBody").inner_text()
    if gone_bad["name"] not in body or "Now contain gluten (1)" not in body.replace("NOW CONTAIN", "Now contain"):
        problems.append(f"since you last looked: What changed doesn't list {gone_bad['name']!r} as now containing gluten")
    page.keyboard.press("Escape")
    # 3. Dismiss: that's looked at; the note doesn't come back, and the next comparison starts from here
    page.locator("#news [data-seen]").first.click()
    page.reload()
    page.wait_for_selector("#list .row")
    base_now = page.evaluate("JSON.parse(localStorage.getItem('gf-looked'))['starbucks-uk'].source")
    if page.locator("#news").is_visible() or base_now != sb_now["source"]:
        problems.append(f"since you last looked: after Dismiss the note is {'still there' if page.locator('#news').is_visible() else 'gone'}, and the phone's copy is {base_now!r}")
    ctx.close()

    # 4. updating from an older app: the menus already on the phone become what you last looked at, with no false alarm
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
    page = ctx.new_page()
    page.goto(base + "#starbucks-uk")
    page.wait_for_selector("#list .row")
    page.evaluate("localStorage.removeItem('gf-looked'); localStorage.setItem('gf-changes-seen', JSON.stringify(JSON.parse(localStorage.getItem('gf-data-v2')).restaurants.map((r) => r.id + '@' + r.source)))")
    page.reload()
    page.wait_for_selector("#list .row")
    kept = page.evaluate("Object.keys(JSON.parse(localStorage.getItem('gf-looked') || '{}')).length")
    if kept != len(ids) or page.locator("#news").is_visible():
        problems.append(f"updating the app: {kept} restaurants remembered (expected {len(ids)}), note showing: {page.locator('#news').is_visible()}")
    ctx.close()

    # 5. when you last looked at exactly the guide the build compared with, the two lists agree and only one shows
    theirs = sb_now.get("changes") or {}
    if theirs.get("added"):
        added = {(x["section"], x["name"]) for x in theirs["added"]}
        prior = trim(sb_now)
        prior["source"], prior["guide"] = theirs["sinceSource"], {"title": theirs["since"]}
        prior["items"] = [i for i in prior["items"] if (i["section"], i["name"]) not in added]
        for k in ("removed", "nowOk", "changed", "nowAvoid"):
            if theirs.get(k):
                prior = None
                break
        if prior:
            ctx = looked_ctx(prior)
            page = ctx.new_page()
            page.goto(base + "#starbucks-uk")
            page.wait_for_selector("#list .row")
            news = page.locator("#news").inner_text() if page.locator("#news").is_visible() else ""
            if "has a new guide" not in news:
                problems.append(f"since you last looked (same as the guide's list): the note says {news!r}")
            page.locator("#news [data-news]").first.click()
            page.wait_for_selector("#changes[open]")
            if page.locator("#changesBody h4").count():
                problems.append("since you last looked: the two lists agree but What changed shows both")
            ctx.close()
    print("since you last looked: a missed guide, a drink now on the Avoid list and a changed order are all shown and marked; "
          "Dismiss moves the starting point; updating the app raises no false alarm; agreeing lists show once")
    return problems


def check_x5(env):
    base, index, browser = env.base, env.index, env.browser
    problems = []
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
    # a restaurant built from two guides (Starbucks: drinks and food) names both in the footer, by their own titles
    two = next((r for r in index["restaurants"] if len(menu_of(r["id"]).get("guides") or []) > 1), None)
    if two:
        titles = [g["title"].lower() for g in menu_of(two["id"])["guides"] if g.get("title") and g["title"] != "Allergen guide"]
        want = " and ".join([", ".join(titles[:-1]), titles[-1]]) + " guides" if len(titles) > 1 else None
        if want and want not in page.locator("#sources").inner_text():
            problems.append(f"footer: {two['name']}'s guide name doesn't name both guides ({want!r})")
    page.locator("#q").fill("")
    print("search: a restaurant's own name narrows results, and 'chips' finds 'fries'")
    ctx.close()
    return problems


def check_x6(env):
    base, browser = env.base, env.browser
    problems = []
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
    return problems


def check_x3(env):
    base, browser = env.base, env.browser
    problems = []
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
    return problems


def check_x9(env):
    base, browser = env.base, env.browser
    problems = []
    # X9: the out-of-date banner hides while searching, like the other tips and notices
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    page = ctx.new_page()
    stale_id = next((r["id"] for r in env.index["restaurants"] if (r.get("guide") or {}).get("validUntil", "9") < time.strftime("%Y-%m-%d")), None)
    if not stale_id:
        print("Knoops banner: no guide is out of date today, so hiding the banner can't be checked")
        return problems
    page.goto(base + f"#{stale_id}")
    page.wait_for_selector("#list .row")
    if not page.locator("#stale").is_visible():
        problems.append(f"{stale_id}: the out-of-date banner isn't showing, so hiding it can't be checked")
    page.locator("#q").fill(menu_of(stale_id)["items"][0]["name"].split()[0].lower())
    page.wait_for_timeout(200)
    if page.locator("#stale").is_visible():
        problems.append(f"{stale_id}: the out-of-date banner still shows while searching")
    page.locator("#q").fill("")
    print("Knoops banner: hides while searching")
    ctx.close()
    return problems


def check_x11(env):
    base, browser = env.base, env.browser
    problems = []
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
    return problems


def check_x12(env):
    base, browser = env.base, env.browser
    problems = []
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
    return problems


def check_add_a_menu_with_the(env):
    base, browser = env.base, env.browser
    problems = []
    # Add a menu with the owner's key: one commit per upload, retries, rate limits and expired keys
    problems += upload_checks(browser, base, "Chromium")
    return problems


def check_f3(env):
    base, browser = env.base, env.browser
    problems = []
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
    return problems


def check_o6(env):
    base, browser = env.base, env.browser
    problems = []
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
    return problems


def check_tap_through_one_restaurant(env):
    base, ids, browser, args = env.base, env.ids, env.browser, env.args
    problems = []
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
    # Avoid: always shown (Needs a change isn't, on a menu with nothing in it, such as this one may be)
    page.locator('#status [data-k="gluten"]').click()
    after = page.locator("#list .row").count()
    if after > before:
        problems.append(f"Status button: list grew from {before} to {after} rows")
    page.reload()
    page.wait_for_selector("#list .row, #list .empty")
    if page.locator('#status [data-k="gluten"]').get_attribute("aria-pressed") != "true":
        problems.append("Status button choice wasn't remembered after reloading")
    problems += [f"tap-through: {e}" for e in errors]
    print(f"tap-through on {ids[0]}: staff card for {name!r}, status filter {before} -> {after} rows")
    ctx.close()
    return problems


def check_f7_map(env):
    base, browser, cities, cid = env.base, env.browser, env.cities, env.cid
    problems = []
    # F7: the Map chip on a city page draws one pin per location, a pin's Open opens that place's row, and the map
    # goes away when the chip is tapped again. OpenStreetMap's tiles are answered here with a blank tile, so the
    # check neither needs signal nor fetches from their server.
    c = cities[cid]
    ctx, page, errors = visit(browser, base + f"#{cid}", wait="#cityList .row")
    page.route("https://tile.openstreetmap.org/**", lambda route: route.fulfill(status=200, content_type="image/png", body=PNG))
    page.locator("#chips [data-map]").click()
    page.wait_for_selector("#cityMap .leaflet-interactive", timeout=15000)
    page.wait_for_timeout(500)
    want = sum(len(p["locations"]) for p in c["places"])
    pins = page.locator("#cityMap path.leaflet-interactive").count()
    if pins != want:
        problems.append(f"map: {pins} pins for {want} locations in {cid}")
    if page.locator("#chips [data-map]").get_attribute("aria-pressed") != "true":
        problems.append("map: the Map chip isn't shown as pressed while the map is open")
    if "OpenStreetMap" not in page.locator("#cityMap .leaflet-control-attribution").inner_text():
        problems.append("map: no OpenStreetMap attribution")
    # a pin's popup opens the place's row
    page.locator("#cityMap path.leaflet-interactive").first.click(force=True)
    page.wait_for_selector("#cityMap .leaflet-popup [data-place-open]", timeout=5000)
    name = page.locator("#cityMap .leaflet-popup [data-place-open]").get_attribute("data-place-open")
    page.locator("#cityMap .leaflet-popup [data-place-open]").click()
    page.wait_for_timeout(300)
    opened = page.locator(f'#cityList details.row[open][data-place="{name}"]').count()
    if not opened:
        problems.append(f"map: Open on {name!r}'s pin didn't open its row")
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_selector(".top:not(.collapsed)")
    page.wait_for_timeout(300)
    page.locator("#chips [data-map]").click()
    page.wait_for_timeout(300)
    if page.locator("#cityMap").count():
        problems.append("map: still there after the chip was tapped again")
    problems += [f"map: {e}" for e in errors]
    print(f"map: {pins} pins in {cid}, a pin opens {name!r}, chip toggles it off")
    ctx.close()
    return problems


def branch_list(index, at, rows):
    """A data/branches.json for the checks: rows are (restaurant id, km due north of at, street, opening_hours)."""
    ids = [r["id"] for r in index["restaurants"] if r.get("osm")]
    dlat = 1 / 111.2
    return {"fetched": "2026-10-20", "chains": ids,
            "b": sorted([ids.index(rid), round(at["latitude"] + km * dlat, 5), at["longitude"], street, hours] for rid, km, street, hours in rows)}


def with_branches(browser, at, listing, init="", **kw):
    """A phone at `at` whose app gets `listing` as its branch list (None: the list is missing), with every request
    that leaves the app's own server recorded. The service worker is blocked, so the list isn't served from its cache."""
    ctx = browser.new_context(color_scheme="light", geolocation=at, permissions=["geolocation"], service_workers="block", **IPHONE, **kw)
    ctx.add_init_script("localStorage.setItem('gf-selected', 'all');" + init)
    out = []
    ctx.on("request", lambda r: out.append(r.url) if not r.url.startswith("http://127.0.0.1") else None)
    ctx.route("**/data/branches.json", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(listing))
              if listing is not None else route.fulfill(status=404, body=""))
    ctx.route("https://tile.openstreetmap.org/**", lambda route: route.fulfill(status=200, content_type="image/png", body=PNG))
    return ctx, out


def check_f8_near_me(env):
    base, browser, index = env.base, env.browser, env.index
    problems = []
    # F8: Near me on All restaurants finds the app's chains within a kilometre in the branch list (data/branches.json,
    # fetched weekly by the publish job), lists them nearest first with their menu and directions, and keeps the answer.
    # Nothing about where you are leaves the phone. Without a list it shows the last answer and says why.
    chains = [r for r in index["restaurants"] if r.get("osm")]
    pret = next((r for r in chains if r["id"] == "pret-uk"), chains[0])
    other = next((r for r in chains if r["id"] != pret["id"]), None)
    at = {"latitude": 51.5308, "longitude": -0.1238}  # King's Cross
    rows_in = [(pret["id"], 0.3, "Euston Road", ""), (pret["id"], 0.8, "Euston Road", ""), (pret["id"], 5, "Far Away Road", "")]
    if other:
        rows_in.append((other["id"], 0.8, "", ""))
    listing = branch_list(index, at, rows_in)
    ctx, outside = with_branches(browser, at, listing)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    page.on("console", lambda m: errors.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
    page.goto(base)
    page.wait_for_selector("#list .row")
    page.locator("#chips [data-near-uk]").click()
    page.wait_for_selector("#near[open] .near-list li", timeout=15000)
    rows = [norm_ws(t) for t in page.locator("#near .near-list li .nm").all_inner_texts()]
    want_first = f"{pret['name']} 300 m · Euston Road · 2 within 1 km"  # the branch 5 km away isn't counted
    if not rows or rows[0] != want_first:
        problems.append(f"near me: first row {rows[0] if rows else None!r}, expected {want_first!r}")
    if other and (len(rows) != 2 or not rows[1].startswith(f"{other['name']} 800 m")):
        problems.append(f"near me: rows {rows}, expected {other['name']} second at 800 m")
    if "list from 20 Oct" not in norm_ws(page.locator("#nearBody").inner_text()):
        problems.append("near me: doesn't say how old the branch list is")
    if outside:
        problems.append(f"near me: requests left the phone: {outside[:3]}")
    href = page.locator("#near .near-list li").first.locator("a").get_attribute("href")
    if not href.startswith("https://maps.apple.com/?ll="):
        problems.append(f"near me: directions link {href!r}")
    page.locator("#near .near-list li").first.locator("[data-gonear]").click()
    page.wait_for_timeout(300)
    if page.locator("#near[open]").count() or pret["name"] not in page.locator("#pickName").inner_text():
        problems.append("near me: Menu didn't open the restaurant's page")
    if norm_ws(page.locator("#chips [data-near-uk]").inner_text()) != "Near me":  # on every page now, plain until the look-around is on
        problems.append("near me: the chip isn't on the restaurant's page, or isn't plain without the look-around")
    saved = page.evaluate("localStorage.getItem('gf-near')")
    ctx.close()
    # no list on this phone yet: the last answer, with a note saying so
    ctx, _ = with_branches(browser, at, None, "localStorage.setItem('gf-near', " + json.dumps(saved) + ")")
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#list .row")
    page.locator("#chips [data-near-uk]").click()
    page.wait_for_selector("#near[open] .near-list li", timeout=15000)
    body = norm_ws(page.locator("#nearBody").inner_text())
    if "last answer" not in body or "today at" not in body or pret["name"] not in body or "isn't on this phone yet" not in body:
        problems.append(f"near me without the list: {body[:160]!r}")
    ctx.close()
    problems += [f"near me: {e}" for e in errors]
    # E1: the look around when the app opens. Switched on, permission granted: the chip reads off the nearest chain with
    # its hours, the chooser gets a Near you group, a reload keeps it, and the chain's own page says Here
    listing = branch_list(index, at, [(pret["id"], 0.3, "Euston Road", "24/7")] + rows_in[1:])
    chip = lambda: norm_ws(page.locator("#chips [data-near-uk]").inner_text())  # noqa: E731

    def settled():  # the look-around runs after the menus load: give it up to ten seconds to write the chip
        for _ in range(40):
            if "›" in chip():
                break
            page.wait_for_timeout(250)
        return chip()
    ctx, outside = with_branches(browser, at, listing, "localStorage.setItem('gf-near-auto', 'on')")
    page = ctx.new_page()
    # a call to anywhere the policy forbids is blocked before it's a request, so it shows only as a console error
    page.on("console", lambda m: problems.append(f"look around console {m.type}: {m.text}") if m.type == "error" else None)
    page.goto(base)
    page.wait_for_selector("#list .row")
    settled()
    want_chip = f"{pret['name']} 300 m · open now ›"
    if chip() != want_chip:
        problems.append(f"look around: the chip reads {chip()!r}, expected {want_chip!r}")
    page.locator("#pickBtn").click()
    page.wait_for_selector("#picker[open]")
    heads = [norm_ws(t).lower() for t in page.locator("#pickList .sub-h").all_inner_texts()]  # the headings are set in capitals
    first = norm_ws(page.locator("#pickList .pick-opt").first.inner_text())
    if heads[:1] != ["near you"] or pret["name"] not in first or "300 m" not in first or "open now" not in first:
        problems.append(f"look around: the chooser's Near you group is {heads[:1]}, first {first[:80]!r}")
    page.locator("#picker .link-btn[value=close]").click()
    page.reload()
    page.wait_for_selector("#list .row")
    settled()
    if chip() != want_chip:
        problems.append(f"look around: after a reload the chip reads {chip()!r}")
    page.goto(base + f"#{pret['id']}")
    page.wait_for_selector("#list .row")
    page.wait_for_timeout(300)
    if chip() != "Here: 300 m · open now ›":  # the chain's own page: no name, so the section chips stay within reach
        problems.append(f"look around: on {pret['name']}'s page the chip reads {chip()!r}")
    if outside:
        problems.append(f"look around: requests left the phone: {outside[:3]}")
    ctx.close()
    # abroad (Alexanderplatz): the position is taken, but there's no UK chain to name
    ctx, _ = with_branches(browser, ALEX, listing, "localStorage.setItem('gf-near-auto', 'on')")
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#list .row")
    page.wait_for_timeout(1200)
    if chip() != "Near me":
        problems.append(f"look around: in Berlin the chip reads {chip()!r}")
    if page.evaluate("localStorage.getItem('gf-near-granted')") != "1":  # it did run: the position was read
        problems.append("look around: in Berlin it never read the position")
    ctx.close()
    # not switched on: nothing on opening; the first answer to a tap offers the choice, and Keep checking switches it on
    ctx, _ = with_branches(browser, at, listing)
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#list .row")
    page.wait_for_timeout(1200)
    if chip() != "Near me" or page.evaluate("localStorage.getItem('gf-near-granted')") is not None:
        problems.append(f"look around: it ran on opening without being switched on (chip {chip()!r})")
    page.locator("#chips [data-near-uk]").click()
    page.wait_for_selector("#near[open] .near-list li", timeout=15000)
    if not page.locator("#near [data-near-ask]").count():
        problems.append("look around: the first answer doesn't offer Keep checking")
    page.locator('#near [data-near-auto="on"]').click()
    page.wait_for_timeout(300)
    if page.evaluate("localStorage.getItem('gf-near-auto')") != "on" or page.locator("#near [data-near-ask]").count():
        problems.append("look around: Keep checking didn't switch it on")
    ctx.close()
    print(f"near me: {rows}; nothing leaves the phone; without the list the last answer; the look around on opening: the chip, Near you, nothing abroad, the opt-in")
    return problems


def check_f16_live_map(env):
    base, browser, index, cities = env.base, env.browser, env.index, env.cities
    problems = []
    # F16: the globe by the title opens the map page. It follows the phone, draws the chains' branches from the branch
    # list for the part of the map on screen (none when zoomed out past a town), pins every city list's place, and a pin's
    # Menu or Open goes to the page or the row. Nothing but the map's tiles leaves the phone. Closing it takes the map down.
    chains = [r for r in index["restaurants"] if r.get("osm")]
    pret = next((r for r in chains if r["id"] == "pret-uk"), chains[0])
    at = {"latitude": 51.5308, "longitude": -0.1238}  # King's Cross
    dlat = 1 / 111.2
    listing = branch_list(index, at, [(pret["id"], 0.3, "Euston Road", "24/7"), (pret["id"], -0.6, "", ""), (pret["id"], 30, "", "")])

    def opened(ctx):
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
        page.on("console", lambda m: errors.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
        page.goto(base)
        page.wait_for_selector("#list .row")
        page.locator("#mapBtn").click()
        page.wait_for_selector("#mapPage[open] #liveMap .leaflet-pane", state="attached", timeout=15000)
        return page, errors

    def until(page, test, ms=8000):
        for _ in range(ms // 100):
            if test():
                return True
            page.wait_for_timeout(100)
        return False

    status = lambda page: norm_ws(page.locator("#mapStatus").inner_text())  # noqa: E731
    dot = lambda page: page.locator("#liveMap path.you-dot").bounding_box()  # noqa: E731
    pin = lambda page: page.locator("#liveMap path.pin-branch").first.bounding_box()  # noqa: E731
    ctx, outside = with_branches(browser, at, listing)
    page, errors = opened(ctx)
    until(page, lambda: "branches" in status(page))
    want = "2 branches of the app's chains within 1.5 km of you. From OpenStreetMap's list of 20 Oct, which misses some; its hours may be out of date."
    if status(page) != want:
        problems.append(f"live map: the status reads {status(page)!r}, expected {want!r}")
    if not page.locator("#liveMap path.you-dot").count():
        problems.append("live map: no dot for where you are")
    branches = page.locator("#liveMap path.pin-branch").count()
    if branches != 2:
        problems.append(f"live map: {branches} branch pins on screen, expected 2 (the one 30 km away isn't)")
    places = page.locator("#liveMap path.pin-place").count()
    want_places = sum(1 for c in cities.values() for p in c["places"] for l in p["locations"] if l.get("lat") is not None)
    if places != want_places:
        problems.append(f"live map: {places} pins for the city lists' places, expected {want_places}")
    if "OpenStreetMap" not in page.locator("#liveMap .leaflet-control-attribution").inner_text():
        problems.append("live map: no OpenStreetMap attribution")
    # moving: the map follows (the pins move under a dot that stays put)
    before_dot, before_pin = dot(page), pin(page)
    ctx.set_geolocation({"latitude": at["latitude"] + 0.6 * dlat, "longitude": at["longitude"]})
    until(page, lambda: abs(pin(page)["y"] - before_pin["y"]) > 20, 4000)
    page.wait_for_timeout(500)
    if abs(pin(page)["y"] - before_pin["y"]) < 20 or abs(dot(page)["y"] - before_dot["y"]) > 20:
        problems.append(f"live map: after moving the dot went {before_dot['y']:.0f} -> {dot(page)['y']:.0f} and a pin {before_pin['y']:.0f} -> {pin(page)['y']:.0f}; the map didn't follow")
    # dragging the map away stops the following; zoomed out past a town the chains' pins go, with a hint saying why
    box = page.locator("#liveMap").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.1
    page.mouse.move(x, y)
    page.mouse.down()
    for step in range(1, 21):
        page.mouse.move(x, y + box["height"] * 0.04 * step)
    page.mouse.up()
    page.wait_for_timeout(800)
    if not page.locator("#mapFollow").is_visible():
        problems.append("live map: after dragging the map away, there's no button back to you")
    for _ in range(4):
        page.locator("#liveMap .leaflet-control-zoom-out").click()
        page.wait_for_timeout(400)
    if page.locator("#liveMap path.pin-branch").count() or not page.locator("#mapHint").is_visible():
        problems.append(f"live map zoomed out: {page.locator('#liveMap path.pin-branch').count()} branch pins, hint showing {page.locator('#mapHint').is_visible()}")
    page.locator("#mapFollow").click()
    page.wait_for_timeout(800)
    if page.locator("#mapFollow").is_visible() or page.locator("#mapHint").is_visible() or not page.locator("#liveMap path.pin-branch").count():
        problems.append("live map: back to you, the pins didn't come back or the buttons are still showing")
    # a branch's Menu opens the chain's page and closes the map
    page.locator("#liveMap path.pin-branch").first.click(force=True)
    page.wait_for_selector("#liveMap .leaflet-popup [data-map-menu]", timeout=5000)
    popup = norm_ws(page.locator("#liveMap .leaflet-popup-content").inner_text())
    if pret["name"] not in popup or " away" not in popup:
        problems.append(f"live map: a branch's popup reads {popup!r}")
    page.locator("#liveMap .leaflet-popup [data-map-menu]").click()
    page.wait_for_timeout(400)
    if page.locator("#mapPage[open]").count() or pret["name"] not in page.locator("#pickName").inner_text():
        problems.append("live map: Menu didn't open the chain's page")
    if page.locator("#liveMap .leaflet-pane").count():
        problems.append("live map: the map is still up after the page closed")
    off_map = [u for u in outside if not u.startswith("https://tile.openstreetmap.org/")]
    if off_map:
        problems.append(f"live map: requests left the phone other than map tiles: {off_map[:3]}")
    problems += [f"live map: {e}" for e in errors]
    ctx.close()
    # abroad: a word on why there are no chains, and a place's Open opens its row on its city's page
    ctx, _ = with_branches(browser, ALEX, listing)
    page, errors = opened(ctx)
    until(page, lambda: "Outside the UK" in status(page))
    if "Outside the UK" not in status(page):
        problems.append(f"live map abroad: status {status(page)!r}")
    for _ in range(2):  # out to the city, so some of its places are on screen
        page.locator("#liveMap .leaflet-control-zoom-out").click()
        page.wait_for_timeout(400)
    box = page.locator("#liveMap").bounding_box()
    inside = [b for b in (p.bounding_box() for p in page.locator("#liveMap path.pin-place").all())
              if b and box["x"] + 20 < b["x"] < box["x"] + box["width"] - 60 and box["y"] + 60 < b["y"] < box["y"] + box["height"] - 60]
    if not inside:
        problems.append("live map abroad: no place pins on screen around Alexanderplatz")
    else:
        page.mouse.click(inside[0]["x"] + inside[0]["width"] / 2, inside[0]["y"] + inside[0]["height"] / 2)
        page.wait_for_selector("#liveMap .leaflet-popup [data-map-place]", timeout=5000)
        b = page.locator("#liveMap .leaflet-popup [data-map-place]")
        name, cid = b.get_attribute("data-map-place"), b.get_attribute("data-city")
        b.click()
        page.wait_for_timeout(400)
        if page.locator("#mapPage[open]").count() or not page.locator(f'#cityList details.row[open][data-place="{name}"]').count():
            problems.append(f"live map abroad: Open on {name!r} didn't open its row on {cid}'s page")
    problems += [f"live map abroad: {e}" for e in errors]
    ctx.close()
    # location refused: the map still opens with every pin it can show, and says why there's no dot
    ctx = browser.new_context(color_scheme="light", service_workers="block", **IPHONE)
    ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
    ctx.route("**/data/branches.json", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(listing)))
    ctx.route("https://tile.openstreetmap.org/**", lambda route: route.fulfill(status=200, content_type="image/png", body=PNG))
    page, errors = opened(ctx)
    until(page, lambda: "Location is off" in status(page))
    if "Location is off" not in status(page) or page.locator("#liveMap path.you-dot").count():
        problems.append(f"live map without location: status {status(page)!r}")
    if page.locator("#liveMap path.pin-place").count() != want_places:
        problems.append("live map without location: the city lists' places aren't all pinned")
    problems += [f"live map without location: {e}" for e in errors]
    ctx.close()
    # no branch list on this phone yet: the map still opens, with the city lists' places, and says so
    ctx, _ = with_branches(browser, at, None)
    page, errors = opened(ctx)
    until(page, lambda: "isn't on this phone yet" in status(page), 4000)
    page.wait_for_timeout(1000)  # and a position arriving doesn't overwrite it
    if page.locator("#liveMap path.pin-branch").count() or page.locator("#liveMap path.pin-place").count() != want_places:
        problems.append("live map without the list: wrong pins")
    want = "The list of the chains' branches isn't on this phone yet: it downloads when the app has signal. Only the city lists' places show for now."
    if status(page) != want:
        problems.append(f"live map without the list: status {status(page)!r}")
    problems += [f"live map without the list: {e}" for e in errors if "404" not in e]
    ctx.close()
    print(f"live map: {branches} branches and {places} places pinned, the dot followed, zoomed out the chains go with a hint, "
          "Menu and Open, nothing but tiles left the phone, abroad, without location, without the list")
    return problems


def check_whats_new(env):
    base, browser = env.base, env.browser
    problems = []
    # What's new: the "Update N is live!" notification opens ?whatsnew (a query, so the release before reads it as
    # nothing), which shows each announced release's notes and then drops the query, so a reload doesn't open it again.
    # Help opens it too, and its words keep to the app's rule on gluten free.
    notes = json.loads((SITE / "whatsnew.json").read_text(encoding="utf-8"))
    app_v = int(re.search(r"APP_VERSION = (\d+)", (SITE / "app.js").read_text(encoding="utf-8")).group(1))
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script("localStorage.setItem('gf-selected', 'all')")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    page.goto(base + "?whatsnew")
    page.wait_for_selector("#whatsNew[open] .news-items", timeout=15000)
    body = norm_ws(page.locator("#whatsNewBody").inner_text())
    if notes[0]["title"] not in body or f"Update {notes[0]['version']}" not in body:
        problems.append(f"what's new: {body[:120]!r}")
    if notes[0]["version"] == app_v and "(this one)" not in body:
        problems.append("what's new: the release on the phone isn't marked as this one")
    if "whatsnew" in page.url:
        problems.append(f"what's new: the address still asks for it ({page.url})")
    problems += [f"what's new says gluten free in the app's own voice: {s!r}" for s in page.evaluate(WORDING_JS) if s in body]
    page.locator("#whatsNew .link-btn[value=close]").click()
    page.reload()
    page.wait_for_selector("#list .row")
    page.wait_for_timeout(500)
    if page.locator("#whatsNew[open]").count() or page.locator("#picker[open]").count():
        problems.append("what's new: a reload opened something it shouldn't")
    page.locator("#infoBtn").click()
    page.locator("#whatsNewBtn").click()
    page.wait_for_selector("#whatsNew[open] .news-items", timeout=5000)
    problems += [f"what's new: {e}" for e in errors]
    ctx.close()
    print(f"what's new: {len(notes)} releases, opened by ?whatsnew and from Help")
    return problems


def check_e_review(env):
    base, cid, cities, browser, index = env.base, env.cid, env.cities, env.browser, env.index
    problems = []
    # E3: the new-guide note says whether the favourites there survived; E4: a restaurant this phone hasn't seen gets a
    # note and a New tag until it's opened; E5: the sections' labels; E6: on All after the first visit an out-of-date
    # guide is a few words in the folded line; E8: Show staff is the filled button, on one row with its neighbours; E12:
    # the warnings count keeps its space; E9: a request's state; E7 and E11: one icon on the time-zone offer, and the
    # city introduction folds after the first visit
    changed = next((r for r in index["restaurants"] if (menu_of(r["id"]).get("changes") or {}).get("added")), None)
    newcomer = next(r["id"] for r in index["restaurants"] if not changed or r["id"] != changed["id"])
    name = next(r["name"] for r in index["restaurants"] if r["id"] == newcomer)
    known = {r["id"]: {"seen": "2026-10-01T00:00:00Z", "new": False} for r in index["restaurants"] if r["id"] != newcomer}
    stale_id = next((r["id"] for r in index["restaurants"] if (r.get("guide") or {}).get("validUntil", "9") < time.strftime("%Y-%m-%d")), None)
    seeds = ["localStorage.setItem('gf-selected', 'all')", "localStorage.setItem('gf-intro-seen', JSON.stringify(['all']))",
             "localStorage.setItem('gf-changes-seen', '[]')", f"localStorage.setItem('gf-known-restaurants', {json.dumps(json.dumps(known))})"]
    if changed:
        c = menu_of(changed["id"])["changes"]
        touched = {(x["section"], x["name"]) for k in ("added", "changed", "nowAvoid", "removed") for x in c.get(k) or []}
        steady = next(i for i in menu_of(changed["id"])["items"] if not i.get("role") and (i["section"], i["name"]) not in touched)
        seeds.append(f"localStorage.setItem('gf-favourites', {json.dumps(json.dumps([changed['id'] + '|' + steady['section'] + '|' + steady['name']]))})")
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script("; ".join(seeds))
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#list .row")
    news = norm_ws(page.locator("#news").inner_text())
    if not changed:
        print("new-guide note: no guide has changed today, so the favourites line can't be checked")
    elif "Your favourite here is unchanged." not in news:
        problems.append(f"new-guide note: no word on the favourite ({news[:160]!r})")
    if not stale_id:
        print("out-of-date line: no guide is out of date today, so its fold can't be checked")
    if f"{name} is new here." not in news:
        problems.append(f"new restaurant: no note on All ({news[:160]!r})")
    if [b.strip() for b in page.locator("#region button").all_inner_texts()] != want_sections(env.cities):
        problems.append(f"the sections read {page.locator('#region button').all_inner_texts()}, expected {want_sections(env.cities)}")
    if stale_id:
        strip = norm_ws(page.locator("#stripText").inner_text())
        if page.locator("#stale").is_visible() or "may be out of date" not in strip:
            problems.append(f"all restaurants after the first visit: the out-of-date line isn't folded into the strip ({strip!r})")
    page.locator("#pickBtn").click()
    page.wait_for_selector("#picker[open]")
    tag = page.locator(f'#pickList .pick-opt[data-r="{newcomer}"] .tag')
    if not tag.count() or norm_ws(tag.inner_text()) != "New":
        problems.append("new restaurant: no New tag in the chooser")
    page.locator("#picker .link-btn[value=close]").click()
    page.locator(f'#news [data-gotorest="{newcomer}"]').click()
    page.wait_for_selector("#list .row")
    page.wait_for_timeout(200)
    if page.locator("#news").is_visible() and f"{name} is new here" in norm_ws(page.locator("#news").inner_text()):
        problems.append("new restaurant: opening it didn't clear the note")
    page.locator("#pickBtn").click()
    page.wait_for_selector("#picker[open]")
    if page.locator(f'#pickList .pick-opt[data-r="{newcomer}"] .tag').count():
        problems.append("new restaurant: the New tag stays after opening it")
    page.locator("#picker .link-btn[value=close]").click()
    row = page.locator("#list .row", has=page.locator(".staff-btn")).first
    row.locator("summary").click()
    page.wait_for_timeout(200)
    accent = page.evaluate("() => { const b = document.createElement('button'); b.className = 'pill-btn'; document.body.appendChild(b); const c = getComputedStyle(b).backgroundColor; b.remove(); return c; }")
    if page.evaluate("(el) => getComputedStyle(el).backgroundColor", row.locator(".staff-btn").element_handle()) != accent:
        problems.append("opened item: Show staff isn't the filled button")
    # Show staff has a full-width row of its own; the others share the row under it
    boxes = {h.get_attribute("class"): h.bounding_box() for h in row.locator(".foot-btns > *").all()}
    staff_box, rest = boxes.get("staff-btn"), [b for c, b in boxes.items() if c != "staff-btn" and b]
    if not staff_box or staff_box["width"] < row.locator(".foot-btns").bounding_box()["width"] - 2:
        problems.append("opened item: Show staff doesn't have the full width")
    if rest and (len({round(b["y"]) for b in rest}) > 1 or min(b["y"] for b in rest) < staff_box["y"] + staff_box["height"]):
        problems.append("opened item: Add to order and Save aren't on one row under Show staff")
    ctx.close()
    ctx, page, errors = visit(browser, base + f"#{index['restaurants'][0]['id']}")
    if page.evaluate("parseFloat(getComputedStyle(document.querySelector('#warnCount')).marginLeft)") <= 0:
        problems.append("Read the warnings: the count has no space before it")
    ctx.close()
    old = json.dumps([{"name": "Testarossa Kitchen", "area": "London", "url": "", "at": "2026-10-01T10:00:00Z", "how": "shared"}])  # a made-up place
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script(f"localStorage.setItem('gf-selected', 'all'); localStorage.setItem('gf-requests', {json.dumps(old)})")
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#list .row")
    page.locator("#infoBtn").click()
    page.locator("#openUpload").click()
    page.wait_for_selector("#upload[open]")
    text = norm_ws(page.locator("#reqList").inner_text())
    if "not in the app yet" not in text or "ask the owner" not in text:
        problems.append(f"requests: the state line reads {text[:120]!r}")
    if "goes to the app's owner as a link" not in page.locator("#reqHow").inner_text():
        problems.append("requests: without the key the sheet doesn't say the request goes as a link")
    ctx.close()
    ctx = browser.new_context(color_scheme="light", timezone_id=cities[cid].get("timeZone", "Europe/Berlin"), **IPHONE)
    ctx.add_init_script(f"localStorage.setItem('gf-selected', 'all'); localStorage.setItem('gf-intro-seen', JSON.stringify(['all', {json.dumps(cid)}]))")
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#tzOffer:not([hidden])")
    if page.evaluate("getComputedStyle(document.querySelector('#tzOffer .tz-btns'), '::before').content") != "none":
        problems.append("time-zone offer: a second icon beside the buttons")
    page.goto(base + f"#{cid}")
    page.wait_for_selector("#cityList .row")
    if not page.locator("#cityStrip").is_visible() or page.locator("#cityIntroBox").is_visible():
        problems.append("city: the introduction doesn't fold after the first visit")
    page.locator("#cityStrip").click()
    page.wait_for_timeout(200)
    if not page.locator("#cityIntroBox").is_visible():
        problems.append("city: tapping the folded line doesn't show the introduction")
    ctx.close()
    print("experience review: the favourites line, a New tag and note, the sections, the folded out-of-date line, filled Show staff, the count's space, request state, one icon, the city fold")
    return problems


def check_f10_read_aloud(env):
    base, browser, cities, cid = env.base, env.browser, env.cities, env.cid
    problems = []
    # F10: Say it reads a phrase in the card's language with the phone's voice for it; without that voice the card
    # says so; without speech at all there are no buttons
    c = cities[cid]
    lang = c["language"]
    phrases = json.loads((SITE / "phrases.json").read_text(encoding="utf-8"))[lang]
    want_lang = {"de": "de-DE", "nl": "nl-NL"}.get(lang, lang)
    mock = ("window.__said = []; window.__voices = %s;"
            "Object.defineProperty(window, 'speechSynthesis', { value: { getVoices: () => window.__voices, cancel() {}, addEventListener() {},"
            " speak(u) { window.__said.push([u.text, u.lang, u.voice ? u.voice.name : null]); } } });"
            "window.SpeechSynthesisUtterance = function (t) { this.text = t; };")
    ctx, page, errors = visit(browser, base + f"#{cid}", init=mock % json.dumps([{"lang": want_lang, "name": "Anna"}, {"lang": "en-GB", "name": "Daniel"}]), wait="#cityList .row")
    page.locator("#chips [data-card]").click()
    page.wait_for_selector("#gfcard[open]")
    if page.locator("#gfcard .say-btn").count() != len(phrases["card"]):
        problems.append(f"read aloud: {page.locator('#gfcard .say-btn').count()} Say buttons for {len(phrases['card'])} phrases")
    page.locator("#gfcard .say-btn").nth(1).click()
    said = page.evaluate("window.__said")
    if said != [[phrases["card"][1]["text"], want_lang, "Anna"]]:
        problems.append(f"read aloud: said {said}, expected the second phrase in {want_lang} with the Anna voice")
    if page.locator("#gfcard .voice-note").inner_text().strip():
        problems.append("read aloud: a voice note shows although a voice for the language is installed")
    ctx.close()
    ctx, page, errors2 = visit(browser, base + f"#{cid}", init=mock % json.dumps([{"lang": "en-GB", "name": "Daniel"}]), wait="#cityList .row")
    page.locator("#chips [data-card]").click()
    page.wait_for_selector("#gfcard[open]")
    note = page.locator("#gfcard .voice-note").inner_text()
    if f"No {phrases['language']} voice" not in note or "Spoken Content" not in note:
        problems.append(f"read aloud: without a {phrases['language']} voice the card should say how to add one, not {note!r}")
    ctx.close()
    ctx, page, errors3 = visit(browser, base + f"#{cid}", init="Object.defineProperty(window, 'speechSynthesis', { value: undefined }); window.SpeechSynthesisUtterance = undefined;", wait="#cityList .row")
    page.locator("#chips [data-card]").click()
    page.wait_for_selector("#gfcard[open]")
    if page.locator("#gfcard .say-btn").count():
        problems.append("read aloud: Say buttons show on a phone without speech")
    ctx.close()
    problems += [f"read aloud: {e}" for e in errors + errors2 + errors3]
    print(f"read aloud: {len(phrases['card'])} phrases in {want_lang}, voice note without a voice, no buttons without speech")
    return problems


def check_f11_notes(env):
    base, browser, ids, cid = env.base, env.browser, env.ids, env.cid
    problems = []
    # F11: a note typed in an opened item is kept on the phone and marks the row; it travels in the favourites link
    # and comes back on another phone; city places take notes too
    rid = ids[0]
    ctx, page, errors = visit(browser, base + f"#{rid}", init=SHARE_MOCK + "localStorage.setItem('gf-selected', 'all');")
    row = page.locator("#list .row").first
    row.locator("summary").click()
    box = row.locator("textarea[data-note]")
    if not box.count():
        problems.append("notes: an opened item has no note box")
        ctx.close()
        return problems
    key = box.get_attribute("data-note")
    box.fill("Ask for a clean jug")
    page.wait_for_timeout(600)
    if not row.locator(".nm .note-mark").count():
        problems.append("notes: the row shows no mark after a note was typed")
    page.reload()
    page.wait_for_selector("#list .row")
    row = page.locator("#list .row").first
    if not row.locator(".nm .note-mark").count() or row.locator("textarea[data-note]").input_value() != "Ask for a clean jug":
        problems.append("notes: the note or its mark didn't survive a reload")
    row.locator("summary").click()
    row.locator("textarea[data-note]").fill("")
    page.wait_for_timeout(600)
    if row.locator(".nm .note-mark").count() or page.evaluate("JSON.parse(localStorage.getItem('gf-notes') || '{}')") != {}:
        problems.append("notes: clearing the box should remove the note and its mark")
    row.locator("textarea[data-note]").fill("Ask for a clean jug")
    page.wait_for_timeout(600)
    row.locator(".fav-btn").click()  # the link carries favourites and notes
    page.locator("#infoBtn").click()
    page.wait_for_selector("#info[open]")
    page.locator("#info details.more", has=page.locator("[data-sharefavs]")).locator("summary").click()
    page.locator("#info [data-sharefavs]").click()
    page.wait_for_timeout(300)
    url = (page.evaluate("window.__shared") or {}).get("url", "")
    code = url.split("#favs=")[-1] if "#favs=" in url else ""
    carried = json.loads(base64.urlsafe_b64decode(code + "=" * (-len(code) % 4)).decode("utf-8")) if code else {}
    if carried.get("n", {}).get(key) != "Ask for a clean jug" or key not in carried.get("f", []):
        problems.append(f"notes: the favourites link should carry the note: {carried}")
    ctx.close()
    # another phone opens the link: the favourite and its note arrive
    ctx, page, errors2 = visit(browser, base + "#favs=" + code, wait="#favImport[open]")
    body = norm_ws(page.locator("#favImportBody").inner_text())
    if "Notes in the link (1)" not in body or "Ask for a clean jug" not in body:  # shown in full before it's added (V7)
        problems.append(f"notes: the import sheet doesn't show the note: {body!r}")
    page.locator("#favImportAdd").click()
    page.wait_for_timeout(400)
    if page.evaluate("JSON.parse(localStorage.getItem('gf-notes') || '{}')") != {key: "Ask for a clean jug"}:
        problems.append("notes: the note didn't arrive with the favourite")
    ctx.close()
    # a city place
    ctx, page, errors3 = visit(browser, base + f"#{cid}", wait="#cityList .row")
    prow = page.locator("#cityList .row").first
    prow.locator("summary").click()
    if not prow.locator("textarea[data-note]").count():
        problems.append("notes: an opened city place has no note box")
    ctx.close()
    problems += [f"notes: {e}" for e in errors + errors2 + errors3]
    print(f"notes: kept and marked on {rid}, carried in the favourites link, taken on another phone, and on city places")
    return problems


def check_f14_guide_link(env):
    base, browser, ids, index = env.base, env.browser, env.ids, env.index
    problems = []
    # F14: "Guide page 7" in an opened item is a link to the published guide at that page, the guide itself is served,
    # a restaurant with two guides links each row to its own, and the footer offers the guides
    with_two = next((r["id"] for r in index["restaurants"] if len(menu_of(r["id"]).get("guideFiles") or {}) > 1), None)
    checked = []
    for rid in [i for i in ids if menu_of(i).get("guideFiles")][:2] + ([with_two] if with_two else []):
        m = menu_of(rid)
        ctx, page, errors = visit(browser, base + f"#{rid}")
        # one item from each guide (src) that cites a page
        for src in sorted({i.get("src", 0) for i in m["items"] if i.get("pages")}):
            item = next(i for i in m["items"] if i.get("pages") and i.get("src", 0) == src)
            want = (m["guideFiles"].get(m["guides"][src]["source"]) if m.get("guides") else m["guideFiles"].get(m["source"])) or ""
            page.locator("#q").fill(item["name"])
            page.wait_for_timeout(300)
            row = page.locator("#list .row, #avoid .row").filter(has_text=item["name"]).first
            row.locator("summary").click()
            link = row.locator(".guide-link")
            if not link.count():
                problems.append(f"guide link: {rid} {item['name']!r} has no link to its guide")
                continue
            href = link.get_attribute("href")
            if href != f"{want}#page={item['pages'][0]}":
                problems.append(f"guide link: {rid} {item['name']!r} links to {href!r}, expected {want!r} at page {item['pages'][0]}")
            status = page.evaluate("(h) => fetch(h.split('#')[0]).then((r) => r.status + ' ' + (r.headers.get('content-type') || ''))", href)
            if not status.startswith("200") or "pdf" not in status:
                problems.append(f"guide link: {href} isn't served as a PDF ({status})")
            checked.append(f"{rid} p{item['pages'][0]}")
            page.locator("#q").fill("")
            page.wait_for_timeout(200)
        foot = page.locator("#sources").inner_text()
        if "Open the" not in foot:
            problems.append(f"guide link: {rid}'s footer has no link to open the guide")
        problems += [f"guide link {rid}: {e}" for e in errors]
        ctx.close()
    print(f"guide links: {', '.join(checked)}; footers offer the guides")
    return problems


def check_f15_requests(env):
    base, browser, index = env.base, env.browser, env.index
    problems = []
    # F15: asking for a place by name: with the owner's key it lands as one JSON file under inbox/requests/ on the
    # uploads branch (never main); a place already in the app is pointed to instead; without the key it becomes a
    # link, which fills the form in on the owner's phone rather than filing by itself
    fake = FakeGitHub()
    ctx = browser.new_context(color_scheme="light", service_workers="block", **IPHONE)
    ctx.add_init_script("localStorage.setItem('gf-github-key', 'k'); localStorage.setItem('gf-selected', 'all')")
    page = ctx.new_page()
    page.route("https://api.github.com/**", fake.handle)
    page.goto(base)
    page.wait_for_selector("#list .row")
    page.locator("#infoBtn").click()
    page.locator("#openUpload").click()
    page.wait_for_selector("#upload[open]")
    page.locator("#reqName").fill("Wagamama")
    page.locator("#reqArea").fill("London")
    page.locator("#reqUrl").fill("wagamama.com")
    page.locator("#reqSend").click()
    page.wait_for_selector("#reqStatus.done", timeout=10000)
    files = [f for f in fake.files("uploads") if f.startswith("inbox/requests/")]
    if len(files) != 1 or not files[0].endswith("-wagamama-london.json") or fake.refs["main"] != "c0":
        problems.append(f"requests: expected one request file on uploads and main untouched; {fake.files('uploads')}, main {fake.refs['main']}")
    else:
        blob = fake.blobs[fake.trees[fake.commits[fake.refs["uploads"]]["tree"]][files[0]]]
        meta = json.loads(base64.b64decode(blob).decode("utf-8"))
        if (meta.get("name"), meta.get("area"), meta.get("url")) != ("Wagamama", "London", "https://wagamama.com"):
            problems.append(f"requests: the file says {meta}")
    listed = norm_ws(page.locator("#reqList").inner_text())
    if "Wagamama (London)" not in listed or "asked" not in listed or "not in the app yet" not in listed:  # E9's honest state line
        problems.append(f"requests: the phone's own list says {listed!r}")
    # a place that's already here
    have = index["restaurants"][0]
    page.locator("#reqName").fill(have["name"].lower())
    page.locator("#reqArea").fill("UK")
    page.locator("#reqSend").click()
    page.wait_for_timeout(300)
    said = norm_ws(page.locator("#reqStatus").inner_text())
    if "already in the app" not in said or len([f for f in fake.files("uploads") if f.startswith("inbox/requests/")]) != 1:
        problems.append(f"requests: asking for {have['name']} again said {said!r}")
    page.locator("#reqStatus [data-gotorest-req]").click()
    page.wait_for_timeout(300)
    if page.locator("#upload[open]").count() or have["name"] not in page.locator("#pickName").inner_text():
        problems.append("requests: Open it didn't open the restaurant that's already here")
    ctx.close()
    # without the key: a link to pass on
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script(SHARE_MOCK + "localStorage.setItem('gf-selected', 'all')")
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_selector("#list .row")
    page.locator("#infoBtn").click()
    page.locator("#openUpload").click()
    page.wait_for_selector("#upload[open]")
    page.locator("#reqName").fill("Honest Burgers")
    page.locator("#reqArea").fill("Brighton")
    page.locator("#reqSend").click()
    page.wait_for_selector("#reqStatus.done", timeout=10000)
    shared = page.evaluate("window.__shared") or {}
    link = shared.get("url", "")
    if "#request=" not in link or "Honest Burgers" not in shared.get("text", ""):
        problems.append(f"requests: without the key the request should be shared as a link: {shared}")
    ctx.close()
    # the owner opens the link: the form is filled in, nothing is filed until Ask for it is tapped
    fake = FakeGitHub()
    ctx = browser.new_context(color_scheme="light", service_workers="block", **IPHONE)
    ctx.add_init_script("localStorage.setItem('gf-github-key', 'k')")
    page = ctx.new_page()
    page.route("https://api.github.com/**", fake.handle)
    page.goto(link)
    page.wait_for_selector("#upload[open]")
    page.wait_for_timeout(300)
    if page.locator("#reqName").input_value() != "Honest Burgers" or page.locator("#reqArea").input_value() != "Brighton" or "uploads" in fake.refs:
        problems.append("requests: the link should fill the form in and file nothing by itself")
    page.locator("#reqSend").click()
    page.wait_for_selector("#reqStatus.done", timeout=10000)
    if not any(f.endswith("-honest-burgers-brighton.json") for f in fake.files("uploads")):
        problems.append(f"requests: Ask for it after the link didn't file the request: {fake.files('uploads')}")
    ctx.close()
    print("requests: filed as one JSON file on uploads, a known place is pointed to, a link without the key, filed from the link on tap")
    return problems


def check_city_requests(env):
    base, browser, cities = env.base, env.browser, env.cities
    problems = []
    # asking for a whole city: from a city list's "A city not here?", filed with the owner's key as one request with
    # kind "city" on the uploads branch; a city already here is pointed to; without the key it's a link that fills the
    # city form in on the owner's phone
    name = "Llanfairpwll"
    if any(c["name"] == name for c in cities.values()):
        return [f"city requests: {name} is in cities.json now; pick another made-up city for this check"]
    cid = next(iter(cities))
    fake = FakeGitHub()
    ctx = browser.new_context(color_scheme="light", service_workers="block", **IPHONE)
    ctx.add_init_script("localStorage.setItem('gf-github-key', 'k')")
    page = ctx.new_page()
    page.route("https://api.github.com/**", fake.handle)
    page.goto(base + "#" + cid)
    page.wait_for_selector("#cityList .row")
    page.locator("#pickBtn").click()
    page.wait_for_selector("#picker[open] [data-askcity]")
    page.locator("#picker [data-askcity]").click()
    page.wait_for_selector("#upload[open]")
    page.wait_for_timeout(300)
    if page.locator("#picker[open]").count() or not page.locator("#cityName").is_visible():
        problems.append("city requests: A city not here? didn't open the city form")
    page.locator("#cityName").fill(name)
    page.locator("#cityCountry").fill("UK")
    page.locator("#citySend").click()
    page.wait_for_selector("#cityStatus.done", timeout=10000)
    files = [f for f in fake.files("uploads") if f.startswith("inbox/requests/")]
    if len(files) != 1 or not files[0].endswith("-city-llanfairpwll-uk.json") or fake.refs["main"] != "c0":
        problems.append(f"city requests: expected one city request on uploads and main untouched; {fake.files('uploads')}, main {fake.refs['main']}")
    else:
        blob = fake.blobs[fake.trees[fake.commits[fake.refs["uploads"]]["tree"]][files[0]]]
        meta = json.loads(base64.b64decode(blob).decode("utf-8"))
        if (meta.get("kind"), meta.get("name"), meta.get("area")) != ("city", name, "UK"):
            problems.append(f"city requests: the file says {meta}")
    listed = norm_ws(page.locator("#reqList").inner_text())
    if f"The city of {name} (UK)" not in listed or "not in the app yet" not in listed:
        problems.append(f"city requests: the phone's own list says {listed!r}")
    # a city that's already here: pointed to, and Open it goes there
    page.locator("#cityName").fill(cities[cid]["name"].upper())
    page.locator("#cityCountry").fill(cities[cid]["country"])
    page.locator("#citySend").click()
    page.wait_for_timeout(300)
    said = norm_ws(page.locator("#cityStatus").inner_text())
    if "already in the app" not in said or len([f for f in fake.files("uploads") if f.startswith("inbox/requests/")]) != 1:
        problems.append(f"city requests: asking for {cities[cid]['name']} again said {said!r}")
    page.locator("#cityStatus [data-gotocity-req]").click()
    page.wait_for_timeout(300)
    if page.locator("#upload[open]").count() or not page.url.endswith("#" + cid):
        problems.append(f"city requests: Open it didn't open {cid}: {page.url}")
    ctx.close()
    # without the key: a link to pass on, which fills the city form in on the owner's phone and files only on a tap
    ctx = browser.new_context(color_scheme="light", **IPHONE)
    ctx.add_init_script(SHARE_MOCK)
    page = ctx.new_page()
    page.goto(base + "#" + cid)
    page.wait_for_selector("#cityList .row")
    page.locator("#pickBtn").click()
    page.locator("#picker [data-askcity]").click()
    page.wait_for_selector("#upload[open]")
    page.locator("#cityName").fill(name)
    page.locator("#cityCountry").fill("Wales")
    page.locator("#citySend").click()
    page.wait_for_selector("#cityStatus.done", timeout=10000)
    shared = page.evaluate("window.__shared") or {}
    link = shared.get("url", "")
    if "#request=" not in link or name not in shared.get("text", ""):
        problems.append(f"city requests: without the key the request should be shared as a link: {shared}")
    ctx.close()
    fake = FakeGitHub()
    ctx = browser.new_context(color_scheme="light", service_workers="block", **IPHONE)
    ctx.add_init_script("localStorage.setItem('gf-github-key', 'k')")
    page = ctx.new_page()
    page.route("https://api.github.com/**", fake.handle)
    page.goto(link)
    page.wait_for_selector("#upload[open]")
    page.wait_for_timeout(300)
    if page.locator("#cityName").input_value() != name or page.locator("#cityCountry").input_value() != "Wales" \
            or page.locator("#reqName").input_value() or "uploads" in fake.refs:
        problems.append("city requests: the link should fill the city form in and file nothing by itself")
    page.locator("#citySend").click()
    page.wait_for_selector("#cityStatus.done", timeout=10000)
    if not any(f.endswith("-city-llanfairpwll-wales.json") for f in fake.files("uploads")):
        problems.append(f"city requests: Ask for it after the link didn't file the city request: {fake.files('uploads')}")
    ctx.close()
    print("city requests: asked from a city list, filed as a city request on uploads, a known city pointed to, a link without the key, filed from the link on tap")
    return problems


def check_f5_push(env):
    base, browser = env.base, env.browser
    problems = []
    # F5: in the Home Screen app, Help offers notifications; switching them on subscribes with the app's public key
    # and shows the phone's address to send; switching off takes it back; in Safari the section doesn't show
    # (the phone's notification and push machinery is stood in for here; sending is tools/push.py's, tested in tests/)
    mock = """
      Object.defineProperty(navigator, 'standalone', { get: () => true });
      window.__sub = null; window.__opts = null;
      const fakeSub = () => ({ toJSON: () => ({ endpoint: 'https://push.example/abc', keys: { p256dh: 'k', auth: 'a' } }), unsubscribe: async () => { window.__sub = null; return true; } });
      const pm = { getSubscription: async () => window.__sub, subscribe: async (o) => { window.__opts = o; window.__sub = fakeSub(); return window.__sub; } };
      window.Notification = { permission: 'default', requestPermission: async () => { window.Notification.permission = 'granted'; return 'granted'; } };
      window.PushManager = window.PushManager || function () {};
      Object.defineProperty(navigator.serviceWorker, 'ready', { get: () => Promise.resolve({ pushManager: pm }) });
    """
    ctx, page, errors = visit(browser, base + "#knoops-uk", init=mock)
    page.locator("#infoBtn").click()
    page.wait_for_selector("#info[open]")
    if page.locator("#pushHelp").is_hidden():
        problems.append("push: Help doesn't offer notifications in the Home Screen app")
    page.locator("#pushHelp summary").click()
    page.locator("#pushOn").click()
    page.wait_for_selector("#pushBox:not([hidden])", timeout=5000)
    shown = page.locator("#pushSub").input_value()
    key_len = page.evaluate("window.__opts && window.__opts.applicationServerKey && window.__opts.applicationServerKey.length")
    if "https://push.example/abc" not in shown or key_len != 65 or not page.evaluate("window.__opts.userVisibleOnly"):
        problems.append(f"push: subscribed with key length {key_len}, shows {shown[:60]!r}")
    if "PUSH_SUBSCRIPTIONS" not in page.locator("#pushBox").inner_text():
        problems.append("push: the box doesn't say where the owner saves the address")
    page.locator("#pushOff").click()
    page.wait_for_selector("#pushOn:not([hidden])", timeout=5000)
    if page.evaluate("window.__sub") is not None or not page.locator("#pushBox").is_hidden():
        problems.append("push: Switch off didn't unsubscribe")
    problems += [f"push: {e}" for e in errors]
    ctx.close()
    ctx, page, errors = visit(browser, base + "#knoops-uk")
    page.locator("#infoBtn").click()
    page.wait_for_selector("#info[open]")
    if not page.locator("#pushHelp").is_hidden():
        problems.append("push: the notifications section shows outside the Home Screen app")
    ctx.close()
    sw = (SITE / "sw.js").read_text(encoding="utf-8")
    for want in ('addEventListener("push"', 'addEventListener("notificationclick"', "setAppBadge", "nowAvoid"):
        if want not in sw:
            problems.append(f"push: sw.js has no {want}")
    print("push: offered only in the Home Screen app; subscribe shows the address with the app's key; switch off unsubscribes")
    return problems


CHECKS = [
    ("every_page", check_every_page),
    ("e_review", check_e_review),
    ("the_berlin_page_in_light", check_the_berlin_page_in_light),
    ("uk_cities", check_uk_cities),
    ("berlin_on_a_sunday_evening", check_berlin_on_a_sunday_evening),
    ("final_review", check_final_review),
    ("add_a_menu_without_a", check_add_a_menu_without_a),
    ("staff_card_wording_the_german", check_staff_card_wording_the_german),
    ("accessibility", check_accessibility),
    ("first_visit", check_first_visit),
    ("search", check_search),
    ("food_safety", check_food_safety),
    ("f13_build_an_order", check_f13_build_an_order),
    ("logos", check_logos),
    ("wording", check_wording),
    ("u1_content_first", check_u1_content_first),
    ("u14", check_u14),
    ("u2_and_u3", check_u2_and_u3),
    ("u4_and_u5", check_u4_and_u5),
    ("u6", check_u6),
    ("u8", check_u8),
    ("u9", check_u9),
    ("u10", check_u10),
    ("u11", check_u11),
    ("u12", check_u12),
    ("u13", check_u13),
    ("s1", check_s1),
    ("f1", check_f1),
    ("f4", check_f4),
    ("f6", check_f6),
    ("s2", check_s2),
    ("s3", check_s3),
    ("s4_and_s5", check_s4_and_s5),
    ("f2", check_f2),
    ("o5", check_o5),
    ("o8", check_o8),
    ("o4", check_o4),
    ("f12", check_f12),
    ("x5", check_x5),
    ("x6", check_x6),
    ("x3", check_x3),
    ("x9", check_x9),
    ("x11", check_x11),
    ("x12", check_x12),
    ("add_a_menu_with_the", check_add_a_menu_with_the),
    ("f3", check_f3),
    ("o6", check_o6),
    ("tap_through_one_restaurant", check_tap_through_one_restaurant),
    ("f7_map", check_f7_map),
    ("f8_near_me", check_f8_near_me),
    ("f16_live_map", check_f16_live_map),
    ("whats_new", check_whats_new),
    ("f10_read_aloud", check_f10_read_aloud),
    ("f11_notes", check_f11_notes),
    ("f14_guide_link", check_f14_guide_link),
    ("f15_requests", check_f15_requests),
    ("city_requests", check_city_requests),
    ("f5_push", check_f5_push),
]


class Env:
    """What every check shares: the server, the restaurants, the first city, the browser and the arguments."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", type=Path, help="save a screenshot of each page here")
    ap.add_argument("--only", help="run only the checks whose name contains this (see CHECKS; 'webkit' for the WebKit pass)")
    ap.add_argument("--list", action="store_true", help="list the checks and stop")
    args = ap.parse_args()
    if args.list:
        for name, _ in CHECKS:
            print(name)
        print("webkit")
        return
    index = json.loads((SITE / "data" / "restaurants.json").read_text(encoding="utf-8"))
    ids = [r["id"] for r in index["restaurants"]]
    cities = json.loads((SITE / "cities.json").read_text(encoding="utf-8"))
    cid = next(iter(cities))
    httpd, base = serve()
    problems = []
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        env = Env(base=base, ids=ids, cid=cid, cities=cities, index=index, browser=browser, args=args, p=p)
        for name, check in CHECKS:
            if args.only and args.only not in name:
                continue
            problems += check(env)
        browser.close()

        # the iPhone runs WebKit, not Chromium: every page, the sheets and uploads again in Safari's engine
        if not args.only or args.only in "webkit":
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
