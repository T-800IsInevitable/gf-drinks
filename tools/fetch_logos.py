#!/usr/bin/env python3
"""
Fetch each restaurant's own site icon for the chooser, by hand.

A chain's icon is the one it publishes for bookmarks and home screens (the
apple-touch-icon or favicon on its official page, or the image "logoUrl" in its
restaurant.json names), so it's the mark the chain itself uses to be recognised. Each is saved as restaurants/<id>/logo.png, 128px
square on a transparent background; build.py copies them into site/data/logos/.
They're the chains' own marks, used only to say which menu is which.

The script identifies itself honestly and doesn't try to get round a site's
blocking: a chain that answers with an error keeps its lettered badge in the app.

Usage:
  python tools/fetch_logos.py            # every restaurant without a logo yet
  python tools/fetch_logos.py --refresh  # fetch them all again
  python tools/fetch_logos.py pho-uk     # just one
"""
import argparse
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (compatible; gf-drinks logo fetch; +https://github.com/T-800IsInevitable/gf-drinks)"
SIZE = 128


class Icons(HTMLParser):
    """The <link rel=icon / apple-touch-icon> tags of a page, with their sizes."""

    def __init__(self):
        super().__init__()
        self.found = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        a = dict(attrs)
        rel = (a.get("rel") or "").lower().split()
        if not a.get("href") or not ({"icon", "apple-touch-icon", "apple-touch-icon-precomposed"} & set(rel)):
            return
        m = re.match(r"(\d+)x(\d+)", a.get("sizes") or "")
        size = int(m.group(1)) if m else (180 if "apple-touch-icon" in rel or "apple-touch-icon-precomposed" in rel else 32)
        self.found.append((size, a["href"]))


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read(), res.geturl()


def candidates(site):
    """Icon addresses to try, largest first, ending with the usual fixed paths."""
    try:
        page, final = get(site)
    except Exception as e:  # blocked or down: only the fixed paths are left to try
        print(f"  page: {e}")
        page, final = b"", site
    p = Icons()
    p.feed(page.decode("utf-8", "replace"))
    out = [urllib.parse.urljoin(final, href) for _, href in sorted(p.found, key=lambda x: -x[0])]
    origin = urllib.parse.urljoin(final, "/")
    return list(dict.fromkeys(out + [origin + "apple-touch-icon.png", origin + "favicon.ico"]))


def render_svg(raw):
    """An SVG icon drawn at 128px by the test browser (Pillow can't read SVG); None without Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    import base64
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page(viewport={"width": SIZE, "height": SIZE}, device_scale_factor=1)
        page.set_content('<!doctype html><style>html,body{margin:0;background:transparent}img{width:%dpx;height:%dpx;display:block}</style>'
                         '<img src="data:image/svg+xml;base64,%s">' % (SIZE, SIZE, base64.b64encode(raw).decode()))
        page.wait_for_timeout(300)
        png = page.locator("img").screenshot(omit_background=True)
        b.close()
    return png


def square(raw):
    """The icon as a 128px square PNG, padded with transparency, or None if it can't be read."""
    if re.match(rb"\s*(<\?xml[^>]*>\s*)?(<!--.*?-->\s*)*<svg\b", raw, re.S):
        raw = render_svg(raw) or b""
    try:
        im = Image.open(io.BytesIO(raw))
        if getattr(im, "n_frames", 1) > 1:  # an .ico: take its largest frame
            best = max(range(im.n_frames), key=lambda k: (im.seek(k) or im.size[0]))
            im.seek(best)
        im = im.convert("RGBA")
    except Exception:
        return None
    if min(im.size) < 48:
        return None
    im.thumbnail((SIZE, SIZE), Image.LANCZOS)
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(im, ((SIZE - im.width) // 2, (SIZE - im.height) // 2))
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--refresh", action="store_true", help="fetch again even where a logo exists")
    args = ap.parse_args()
    folders = sorted(p for p in (ROOT / "restaurants").iterdir()
                     if p.is_dir() and not p.name.startswith(("_", ".")) and (not args.ids or p.name in args.ids))
    missing = []
    for folder in folders:
        cfg = json.loads((folder / "restaurant.json").read_text(encoding="utf-8"))
        out = folder / "logo.png"
        if out.exists() and not args.refresh:
            continue
        site = cfg.get("officialUrl")
        print(f"{folder.name}: {site}")
        if not site:
            missing.append(folder.name)
            continue
        done = False
        # "logoUrl" in restaurant.json names a better mark on the chain's own site when its icon doesn't work small
        for url in ([cfg["logoUrl"]] if cfg.get("logoUrl") else []) + candidates(urllib.parse.urljoin(site, "/")):
            try:
                raw, _ = get(url)
            except Exception as e:
                print(f"  {url}: {e}")
                continue
            png = square(raw)
            if png:
                out.write_bytes(png)
                print(f"  saved {out.name} from {url} ({len(png)} bytes)")
                done = True
                break
            print(f"  {url}: not a usable image")
        if not done:
            missing.append(folder.name)
        time.sleep(1)
    if missing:
        print("no logo for: " + ", ".join(missing) + " (the app shows a lettered badge instead)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
