#!/usr/bin/env python3
"""
Save a snapshot of Nando's UK allergen information, for tools/adapters/nandos_uk_json.py to build the menu from.

Nando's publishes no allergen guide as a file: each dish has its own page under nandos.co.uk/allergens/, with a
table of the 14 allergens (Contains, May Contain, Further Information) and its ingredients. This reads the dish pages
the site lists in its sitemap (robots.txt allows them), one at a time with a pause between, and writes what they say to
restaurants/nandos-uk/guides/nandos-allergens-<date>.json. Run it by hand when Nando's says its allergens have changed,
or when the app says the menu is due a re-check; then open a pull request as for any new guide.

A page whose table can't be read stops the run: nothing is written, so the app keeps the menu it has.

Usage:
  python tools/fetch_nandos.py            # all dishes
  python tools/fetch_nandos.py --limit 5  # a quick try
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "restaurants" / "nandos-uk" / "guides"
SITE = "https://www.nandos.co.uk"
UA = "Mozilla/5.0 (compatible; gf-drinks allergen snapshot; +https://github.com/T-800IsInevitable/gf-drinks)"
PAUSE = 1.5
ALLERGENS = ["celery", "gluten", "crustaceans", "eggs", "fish", "lupin", "milk", "molluscs", "mustard", "nuts", "peanuts",
             "sesame", "soya", "sulphites"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read().decode("utf-8", "replace")


def text(fragment):
    # Nando's bolds allergen words even inside other words ("Benz<b>oat</b>e"), so inline tags join without a space
    t = re.sub(r"</?(?:b|strong|em|i|u|mark)(?:\s[^>]*)?>", "", fragment)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).strip()


def marked(cell):
    """A table cell is either a dash (no) or a coloured circle with a tick (yes)."""
    if "<svg" in cell or "background-color" in cell:
        return True
    if text(cell) in ("–", "-", ""):
        return False
    raise ValueError(f"unexpected cell {text(cell)!r}")


def dish(slug, page):
    title = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    if not title:
        raise ValueError("no title")
    spans = [text(x) for x in re.findall(r"<span[^>]*>([^<]+)(?:<!-- -->)?\s*</span>", title.group(1))]
    name, variant = (spans + ["", ""])[:2] if spans else (text(title.group(1)), "")
    rows = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) == 4 and text(cells[0]).lower() in ALLERGENS:
            rows[text(cells[0]).lower()] = {"contains": marked(cells[1]), "may": marked(cells[2]), "info": text(cells[3])}
    flat = text(re.sub(r"<script.*?</script>", " ", page, flags=re.S))
    updated = re.search(r"Last Updated:\s*([0-9]{1,2} \w+ \d{4})", flat)
    # the line under the date: "Contains gluten, sesame." or "None of the top 14 allergens present, ..."
    summary = re.search(r"Last Updated:\s*[0-9]{1,2} \w+ \d{4}\s*(.*?)\s*Allergen Information", flat)
    summary = summary.group(1) if summary else ""
    if not rows and not summary:
        return None  # not a dish: an information page (such as an airport's allergy notes)
    if not summary:
        raise ValueError("no allergen summary line")
    # Some tables list every allergen, some only those present; the summary says the same in words. Both are kept.
    ingredients = re.search(r"\bIngredients\b(.*?)(?:Important Allergy Information|$)", flat)
    flight = page.replace('\\"', '"')
    category = re.search(r'"category":\[\{"name":"([^"]+)"', flight)
    return {"slug": slug, "name": name, "variant": variant, "category": html.unescape(json.loads('"' + category.group(1) + '"')) if category else None,
            "updated": updated.group(1) if updated else None, "url": f"{SITE}/allergens/{slug}",
            "contains": sorted(a for a, r in rows.items() if r["contains"]),
            "mayContain": sorted(a for a, r in rows.items() if r["may"]),
            "notes": {a: r["info"] for a, r in rows.items() if r["info"] and r["info"] not in ("–", "-")},
            "summary": summary, "fullTable": all(a in rows for a in ALLERGENS),
            "ingredients": ingredients.group(1).strip()[:4000] if ingredients else ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only the first n dishes, to try it")
    args = ap.parse_args()
    sitemap = get(f"{SITE}/UK/rp-sitemap.xml")
    slugs = sorted(set(re.findall(r"<loc>https://www\.nandos\.co\.uk/allergens/([a-z0-9-]+)</loc>", sitemap)))
    if len(slugs) < 50:
        raise SystemExit(f"ERROR: only {len(slugs)} allergen pages in the sitemap. Nothing written.")
    if args.limit:
        slugs = slugs[:args.limit]
    main_page = text(re.sub(r"<script.*?</script>", " ", get(f"{SITE}/allergens"), flags=re.S))
    general = re.search(r"All our food is prepared in kitchens where allergens are present[^.]*\.[^.]*\.", main_page)
    dishes = []
    for n, slug in enumerate(slugs, start=1):
        time.sleep(PAUSE)
        try:
            found = dish(slug, get(f"{SITE}/allergens/{slug}"))
        except Exception as e:
            raise SystemExit(f"ERROR: {slug}: {e}. Nothing written.")
        if found is None:
            print(f"{n}/{len(slugs)} {slug}: not a dish page, skipped", flush=True)
            continue
        dishes.append(found)
        print(f"{n}/{len(slugs)} {slug}: {dishes[-1]['name']} ({dishes[-1]['category']}) contains {dishes[-1]['contains']}", flush=True)
    today = date.today().isoformat()
    snapshot = {"source": f"{SITE}/allergens", "fetched": today, "notices": [general.group(0)] if general else [],
                "important": "Allergen data/info items are based on the product recipe and cannot be excluded. We handle many "
                             "allergens in our kitchen and cannot guarantee the product to be allergen free.",
                "dishes": dishes}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"nandos-allergens-{today}.json"
    path.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(dishes)} dishes to {path}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
