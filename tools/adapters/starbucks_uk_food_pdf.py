#!/usr/bin/env python3
"""
Reader for Starbucks UK food allergen guides (PDF), used alongside the
beverage reader ("readers": ["starbucks_uk_pdf", "starbucks_uk_food_pdf"]).

Both guides go in the restaurant's guides/ folder; this reader takes the
newest one whose cover says Food.

  * Each product is a row between ruled lines, with its ingredients and an
    Allergens column summarising them.
  * A row contains gluten if its Allergens column OR its ingredient list names,
    in BOLD CAPITALS: WHEAT, OAT(S), BARLEY, RYE, SPELT, KAMUT, GLUTEN or MALT.
  * If the two disagree the row is treated as containing gluten and a warning
    is recorded, so a parsing slip can only hide an item, never show one.
  * The build stops if the PDF doesn't look like a food guide.
"""
import re
from pathlib import Path

import pdfplumber

from . import notices
from .starbucks_uk_pdf import GLUTEN, clean, decided, is_food_guide

MIN_ROWS = 60  # a real guide has well over a hundred products
INGREDIENTS_X = 136


def guide_info(pdf):
    text = "\n".join((pdf.pages[i].extract_text() or "") for i in range(min(2, len(pdf.pages))))
    version = re.search(r"Version:\s*(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
    vdate = None
    if version:
        d, m, y = (int(x) for x in version.groups())
        y = y + 2000 if y < 100 else y
        vdate = f"{y:04d}-{m:02d}-{d:02d}"
    title = re.search(r"\b(Spring|Summer|Autumn|Winter|Holiday|Festive)\b[^\n]*\bFood\b", text)
    months = r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    span = re.search(months + r"\s*[-–]\s*" + months + r"\s+(\d{4})", text)
    return {
        "title": clean(title.group(0)) if title else None,
        "runs": clean(span.group(0)).replace(" - ", " to ").replace(" – ", " to ") if span else None,
        "version": vdate,
    }


def parse_rows(pdf_path):
    pdf = pdfplumber.open(pdf_path)
    info = guide_info(pdf)
    rows, warnings, table = [], [], []
    section = sub = None
    for pno, page in enumerate(pdf.pages, start=1):
        words = page.extract_words()
        hdr = {w["text"]: w for w in words if w["top"] < 130}
        if "Product" not in hdr or "Ingredients" not in hdr:
            continue
        table.append(pno)
        # Section from the breadcrumb: "STARBUCKS | Nutrition & Allergen Guide | Food | <Section>"
        crumb = clean(page.crop((0, 0, page.width, 40)).extract_text() or "")
        if "| Food |" not in crumb:
            raise SystemExit(f"ERROR: p.{pno}: no 'Food' breadcrumb ({crumb!r}). Layout changed? Menu not updated.")
        new = re.sub(r"\s*Version:.*$", "", crumb.split("| Food |")[-1]).strip()
        # "Bakery Menu" -> "Bakery"; "Seasonal Menu" -> "Seasonal food", so it isn't confused with seasonal drinks
        new = re.sub(r"\s+Menu$", "", new)
        new = "Seasonal food" if new == "Seasonal" else new
        if new != section:  # a page with no sub-heading bar continues the previous page's
            section, sub = new, None
        allergen_x = page.width - 75
        head_bottom = hdr["Product"]["bottom"]
        # The navigation bar at the foot of each table page ends the rows.
        foot = min((r["top"] for r in page.rects if r["width"] > page.width * 0.9 and r["top"] > page.height * 0.75),
                   default=page.height - 80)
        # Green sub-heading bars ("Bakery") start at the left margin and run under the ingredients.
        bars = [r for r in page.rects if r["x0"] < 30 and r["width"] > page.width * 0.5 and 8 < r["height"] < 30
                and head_bottom - 2 < r["top"] < foot]
        bounds = {round(o["top"], 1) for o in page.lines + page.rects
                  if o["height"] < 2 and o["width"] > 100 and abs(o["x0"] - INGREDIENTS_X) < 6 and head_bottom < o["top"] < foot}
        for b in bars:
            bounds |= {round(b["top"], 1), round(b["bottom"], 1)}
        bounds = sorted(bounds | {round(foot, 1)})
        for top, bot in zip(bounds, bounds[1:]):
            if bot - top < 5:
                continue

            def txt(x0, x1, tol=3):
                return clean(page.crop((x0, top, x1, bot)).extract_text(x_tolerance=tol) or "")

            if any(abs(b["top"] - top) < 2 and abs(b["bottom"] - bot) < 2 for b in bars):
                sub = re.sub(r"\s*-{3,}.*$", "", txt(20, page.width / 2, tol=4)) or sub
                continue
            name = clean(txt(20, 95, tol=4).replace("�", "® "))  # the guide's font has no ® for some names
            ingredients = txt(INGREDIENTS_X, 525)
            if not name and not ingredients:
                continue
            if not name or not ingredients:
                raise SystemExit(f"ERROR: p.{pno}: a row has {'no name' if not name else 'no ingredients'} "
                                 f"({name or ingredients[:40]!r}). Layout changed? Menu not updated.")
            rows.append({"page": pno, "section": section, "sub": sub, "name": name, "ingredients": ingredients,
                         "allergens": txt(allergen_x, page.width - 5, tol=4)})
    if not table or len(rows) < MIN_ROWS:
        raise SystemExit(f"ERROR: {Path(pdf_path).name} doesn't look like a Starbucks food guide "
                         f"({len(table)} table pages, {len(rows)} rows). Menu not updated.")
    for r in rows:
        a = set(GLUTEN.findall(r["allergens"]))
        i = set(GLUTEN.findall(r["ingredients"]))
        r["gluten"] = sorted({g.rstrip("S") if g == "OATS" else g for g in a | i})
        if bool(a) != bool(i):
            warnings.append(f"food p.{r['page']} {r['name']}: allergen column {sorted(a) or 'none'} vs "
                            f"ingredients {sorted(i) or 'none'}; treated as containing gluten")
        if not r["allergens"]:
            warnings.append(f"food p.{r['page']} {r['name']}: allergen column empty; classified from ingredients")
        r["decided"] = decided(r["allergens"], a, i)
    return info, rows, warnings, table


def newest_pdf(folder):
    dated = []
    for p in folder.glob("*.pdf"):
        with pdfplumber.open(p) as pdf:
            if not is_food_guide(pdf):
                continue
            v = guide_info(pdf)["version"] or "0000-00-00"
        dated.append((v, p.stat().st_mtime, p))
    if not dated:
        raise SystemExit(f"ERROR: no food guide PDF found in {folder}")
    dated.sort()
    for v, _, p in dated:
        print(f"  found {p.name} (version {v})")
    return dated[-1][2]


def build(folder, config):
    """Build the food part of the menu from the newest food guide in guides/."""
    pdf_path = newest_pdf(Path(folder) / "guides")
    print(f"  building from {pdf_path.name}")
    info, rows, warnings, table = parse_rows(pdf_path)
    ok, avoid, seen = [], [], set()
    for r in rows:
        key = (r["section"], r["name"])
        if key in seen:  # the same product listed twice: keep the first, but never let a duplicate hide gluten
            prev = next(x for x in ok + avoid if (x["section"], x["name"]) == key)
            if r["gluten"] and prev in ok:
                ok.remove(prev)
                avoid.append({**prev, "gluten": r["gluten"]})
                prev.pop("order", None)
            continue
        seen.add(key)
        item = {"name": r["name"], "section": r["section"], "sub": r["sub"], "pages": [r["page"]]}
        if r["decided"]:
            item["decided"] = r["decided"]
        if r["gluten"]:
            avoid.append({**item, "gluten": r["gluten"]})
        else:
            ok.append({**item, "order": "asis"})
    with pdfplumber.open(pdf_path) as pdf:
        intro = [n for n in range(2, table[0]) if n not in table]
        regions = {n: [(0, pdf.pages[n - 1].height - 60, pdf.pages[n - 1].width, pdf.pages[n - 1].height)] for n in table}
        guide_notices = notices.collect(pdf, intro, regions=regions)
    return {
        "notices": guide_notices,
        "source": pdf_path.name,
        "guide": info,
        "rule": "Food: excludes anything listing wheat, oats, barley, rye, spelt, kamut, gluten or malt.",
        "sections": list(dict.fromkeys(i["section"] for i in ok + avoid)),
        "items": ok,
        "avoid": avoid,
        "warnings": warnings,
        "stats": {"rows": len(rows), "items": len(ok), "avoid": len(avoid)},
    }
