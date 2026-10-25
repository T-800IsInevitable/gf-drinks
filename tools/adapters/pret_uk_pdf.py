"""
Reader for Pret A Manger's GB allergen guide (PDF).

The guide is a grid: one row per product, one column per allergen, with a
tick (a Webdings character) where the product contains that allergen. Pret
lists gluten under "Cereals containing gluten" with six columns: Barley,
Kamut (Wheat), Oats, Rye, Spelt (Wheat) and Wheat.

  * A product contains gluten if it has a tick in ANY of those six columns.
    Oats count, matching how the guide itself groups them.
  * Column positions are read from each page's own headings, and each tick is
    matched to the nearest column heading, so small layout shifts between
    pages or editions don't matter.
  * The build stops with an error if a page is missing any gluten column
    heading, or a tick can't be matched to a product, so a changed layout
    can't silently publish a wrong menu.
  * Barista drinks listed once per milk ("Latte Semi Skimmed milk",
    "Latte Oat (instead of milk)") are grouped into one drink each.
"""
import re
from datetime import date, timedelta
from pathlib import Path

import pdfplumber

from . import notices

TICK = ""
GLUTEN_COLS = {"Barley": "BARLEY", "Kamut": "KAMUT", "Oats": "OAT", "Rye": "RYE", "Spelt": "SPELT", "Wheat": "WHEAT"}
RED = (0.624, 0.106, 0.196)
MILK = re.compile(r"^(.*?)\s+(?:-\s+)?((?:Semi Skimmed|Skimmed|Whole)(?: milk)?(?: \(instead of coconut(?: milk)?\))?|(?:Coconut|Oat|Soya|Almond|Rice) \(instead of (?:milk|coconut)(?: milk)?\)|(?<=Latte - )(?:Coconut|Oat|Soya)|(?<=Latte )(?:Coconut|Oat|Soya))$", re.I)
MIN_ROWS = 100


def clean(s):
    s = re.sub(r"[\u200b-\u200d\ufeff]", "", s or "")  # invisible characters in the source
    return re.sub(r"\s+", " ", s).strip()


def is_red(c):
    return isinstance(c, (tuple, list)) and len(c) == 3 and all(abs(a - b) < 0.05 for a, b in zip(c, RED))


def guide_info(pdf):
    text = "\n".join(pdf.pages[i].extract_text() or "" for i in range(min(2, len(pdf.pages))))
    m = re.search(r"Valid from\s+(\d{1,2})\s+(\w+)\s+(\d{4})(?:\s+(V\d+))?", text)
    if not m:
        m2 = re.search(r"Allergen Guide (\d{1,2})(?:st|nd|rd|th)?\s+(\w+)\s+(\d{4})(?:\s+(V\d+))?", text)
        m = m2
    version = None
    label = None
    if m:
        d, mon, y, v = m.groups()
        try:
            version = date(int(y), ["january", "february", "march", "april", "may", "june", "july", "august", "september",
                                    "october", "november", "december"].index(mon.lower()) + 1, int(d)).isoformat()
            label = f"Valid from {int(d)} {mon} {y}" + (f" {v}" if v else "")
        except ValueError:
            pass
    return {"title": "Allergen guide", "runs": None, "version": version, "label": label}


def page_title(page):
    big = [c for c in page.chars if c["size"] > 20]
    return clean("".join(c["text"] for c in sorted(big, key=lambda c: (round(c["top"]), c["x0"]))))


def parse_rows(pdf_path):
    pdf = pdfplumber.open(pdf_path)
    info = guide_info(pdf)
    rows, warnings = [], []
    table_pages = 0
    prev_section, sub = None, None
    for pno, page in enumerate(pdf.pages, start=1):
        words = page.extract_words(extra_attrs=["non_stroking_color"])
        prod = next((w for w in words if w["text"] == "Product" and w["top"] < 250), None)
        if not prod:
            continue
        table_pages += 1
        section = page_title(page) or "Menu"
        veg = next((w for w in words if w["text"] == "Vegetarians"), None)
        peanut = next((w for w in words if w["text"] == "Peanut"), None)
        if not veg or not peanut:
            raise SystemExit(f"ERROR: p.{pno}: couldn't find the Vegetarians/Peanut headings. Layout changed? Menu not updated.")
        name_right = veg["x0"] - 3
        # Column headings: words in the heading band, right of the dietary columns.
        band_top, band_bot = prod["top"] - 3, prod["bottom"] + 20
        heads = [w for w in words if band_top <= w["top"] <= band_bot and w["x0"] >= peanut["x0"] - 2]
        clusters = []  # [centre_x, [words]]
        for w in sorted(heads, key=lambda w: (w["x0"] + w["x1"]) / 2):
            cx = (w["x0"] + w["x1"]) / 2
            if clusters and abs(clusters[-1][0] - cx) < 9:
                clusters[-1][1].append(w)
            else:
                clusters.append([cx, [w]])
        # label reads top to bottom, e.g. "Kamut (Wheat)"
        cols = [(cx, " ".join(w["text"] for w in sorted(ws, key=lambda w: w["top"]))) for cx, ws in clusters]
        gluten_cols = {}
        for cx, label in cols:
            first = label.split()[0].lower()
            # match on the start of the heading, so spelling slips in the guide
            # (page 13 of the Sept 2026 edition says "Kamult") still count
            for key, code in GLUTEN_COLS.items():
                if first.startswith(key.lower()[:3]) and first != "(wheat)":
                    gluten_cols[cx] = code
        if sorted(gluten_cols.values()) != sorted(GLUTEN_COLS.values()):
            raise SystemExit(f"ERROR: p.{pno}: found gluten columns {sorted(gluten_cols.values())}, expected all of "
                             f"{sorted(GLUTEN_COLS.values())}. Layout changed? Menu not updated.")
        # Row boundaries: thin full-width rules plus the red sub-heading bands.
        # Row boundaries: edges of the full-width rules, shaded row stripes and red
        # sub-heading bands, down to the red disclaimer box under the table.
        allwide = [r for r in page.rects if r["x0"] < 60 and r["x1"] > page.width * 0.8]
        footer = min((r["top"] for r in allwide if r["top"] > prod["bottom"] and is_red(r.get("non_stroking_color"))
                      and r["height"] >= 25), default=page.height)
        # the heading box's bottom edge is the first row's top
        head_bottom = max((r["bottom"] for r in allwide if r["top"] < prod["top"] and r["bottom"] > prod["bottom"]), default=prod["bottom"])
        wide = [r for r in allwide if r["top"] >= head_bottom - 1 and r["bottom"] <= footer + 1 and r["height"] < 25]
        reds = [r for r in wide if is_red(r.get("non_stroking_color")) and r["height"] > 5]
        bounds = sorted({round(r[k], 1) for r in wide for k in ("top", "bottom")} | {round(head_bottom, 1), round(footer, 1)})
        ticks = [c for c in page.chars if c["text"] == TICK]
        used = set()
        if section != prev_section:
            sub = None
        prev_section = section
        for top, bot in zip(bounds, bounds[1:]):
            if bot - top < 5:
                continue
            mid = lambda o: (o["top"] + o["bottom"]) / 2
            name = clean(" ".join(w["text"] for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
                                  if w["x1"] <= name_right + 2 and top <= mid(w) <= bot and w["x0"] > 40))
            red_band = any(abs(r["top"] - top) < 1.5 and abs(r["bottom"] - bot) < 1.5 for r in reds)
            if red_band:
                sub = name or sub
                continue
            row_ticks = [t for t in ticks if top <= mid(t) <= bot]
            if not name:
                if row_ticks:
                    raise SystemExit(f"ERROR: p.{pno}: ticks at y={top:.0f} with no product name. Menu not updated.")
                continue
            gl = set()
            for t in row_ticks:
                used.add(id(t))
                tx = (t["x0"] + t["x1"]) / 2
                cx, label = min(cols, key=lambda c: abs(c[0] - tx))
                if abs(cx - tx) > 14:
                    raise SystemExit(f"ERROR: p.{pno} {name}: tick at x={tx:.0f} isn't under any heading. Menu not updated.")
                if cx in gluten_cols:
                    gl.add(gluten_cols[cx])
            rows.append({"page": pno, "section": section, "sub": sub, "name": name, "gluten": sorted(gl)})
        stray = [t for t in ticks if id(t) not in used and head_bottom - 1 < (t["top"] + t["bottom"]) / 2 < footer]
        if stray:
            raise SystemExit(f"ERROR: p.{pno}: {len(stray)} tick(s) not matched to a product row. Menu not updated.")
    if table_pages == 0 or len(rows) < MIN_ROWS:
        raise SystemExit(f"ERROR: {Path(pdf_path).name} doesn't look like a Pret allergen guide "
                         f"({table_pages} table pages, {len(rows)} rows). Menu not updated.")
    return info, rows, warnings


def group(rows, warnings=None):
    drinks = {}
    for r in rows:
        m = MILK.match(r["name"])
        base, milk = (clean(m.group(1)), re.sub(r"(?: milk)?(?: \(instead of [\w ]+\))?$", "", m.group(2).lower())) if m else (r["name"], None)
        # the guide sometimes words one milk version differently ("Pistachio Iced Latte" among "Iced Pistachio Latte"
        # rows), so versions are grouped by the words in the name, whatever their order
        key = (r["section"], r["sub"] or "", tuple(sorted(set(base.lower().split()))))
        d = drinks.setdefault(key, {"name": base, "section": r["section"], "sub": r["sub"], "pages": [], "versions": [], "names": []})
        if r["page"] not in d["pages"]:
            d["pages"].append(r["page"])
        d["versions"].append({"milk": milk, "gluten": r["gluten"]})
        d["names"].append(base)
    ok, avoid = [], []
    for d in drinks.values():
        names = d.pop("names")
        d["name"] = max(dict.fromkeys(names), key=names.count)  # the wording most of its rows use
        if len(set(names)) > 1 and warnings is not None:
            warnings.append(f"{d['name']}: the guide also calls one version {', '.join(repr(n) for n in dict.fromkeys(names) if n != d['name'])}; grouped as one drink")
        vs = d.pop("versions")
        good = [v for v in vs if not v["gluten"]]
        bad = [v for v in vs if v["gluten"]]
        if not good:
            common = set.intersection(*(set(v["gluten"]) for v in bad))
            d["gluten"] = sorted(common or {g for v in bad for g in v["gluten"]})
            avoid.append(d)
            continue
        milks = [v for v in vs if v["milk"]]
        if not milks or len(vs) == 1:
            d["order"] = "asis"
        else:
            d["ok"] = [v["milk"] for v in milks if not v["gluten"]]
            d["not"] = [v["milk"] for v in milks if v["gluten"]]
            d["order"] = "except" if d["not"] else "any"
        ok.append(d)
    return ok, avoid


def newest_pdf(folder):
    pdfs = list(Path(folder).glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"ERROR: no PDF found in {folder}")
    dated = []
    for p in pdfs:
        with pdfplumber.open(p) as pdf:
            dated.append((guide_info(pdf)["version"] or "0000-00-00", p.stat().st_mtime, p))
    dated.sort()
    for v, _, p in dated:
        print(f"  found {p.name} (valid from {v})")
    return dated[-1][2]


def build(folder, config):
    pdf_path = newest_pdf(Path(folder) / "guides")
    print(f"  building from {pdf_path.name}")
    info, rows, warnings = parse_rows(pdf_path)
    ok, avoid = group(rows, warnings)
    with pdfplumber.open(pdf_path) as pdf:
        first_table = next((i + 1 for i, pg in enumerate(pdf.pages) if "Product" in (pg.extract_text() or "")), 3)
        guide_notices = notices.collect(pdf, list(range(1, first_table)), columns_for=tuple(range(2, first_table)))
    # Pret guides have no end date. Ask for a re-check after the number of days in restaurant.json.
    if info["version"]:
        days = int(config.get("recheckDays", 91))
        info["validUntil"] = (date.fromisoformat(info["version"]) + timedelta(days=days)).isoformat()
    return {
        "notices": guide_notices,
        "source": pdf_path.name,
        "guide": {k: info.get(k) for k in ("title", "runs", "version", "validUntil")},
        "rule": "Excludes anything ticked for barley, kamut, oats, rye, spelt or wheat.",
        "sections": list(dict.fromkeys(i["section"] for i in ok + avoid)),
        "items": ok,
        "avoid": avoid,
        "warnings": warnings,
        "stats": {"rows": len(rows), "items": len(ok), "avoid": len(avoid)},
    }
