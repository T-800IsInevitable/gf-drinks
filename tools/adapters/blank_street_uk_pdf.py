#!/usr/bin/env python3
"""
Reader for Blank Street's UK allergen guide (PDF): ruled tables of product,
ingredients and a "May Contain" line, with drinks listed once per milk
("With DAIRY: ...", "With OAT: ...").

For each product, and each milk version of a drink:
  * contains gluten if its ingredients name, in CAPITALS, WHEAT, OAT(S),
    BARLEY, RYE, SPELT, KAMUT, GLUTEN or MALT (the guide writes OAT/GLUTEN)
  * may contain gluten if its "May Contain" line names oats, wheat, gluten
    or cereals containing gluten. "May contain" counts as gluten here, so the
    item goes on the Avoid list with the reason shown.
A drink is listed with the milks that have neither; if none do, it's avoided.

The guide has no date in its text: the season comes from the file name
("...Autumn26.pdf") and the version from the PDF's creation date.
"""
import re
from pathlib import Path

import pdfplumber

from .common import CEREAL_CAPS as CONTAINS, CEREAL_WORDS, cereal_code as cereal, clean, newest_by, result

MAY = re.compile(rf"\b({CEREAL_WORDS}|cereals)\b", re.I)
VERSION = re.compile(r"With\s+(\w+)\s*:", re.I)
MIN_ROWS = 60


def guide_info(pdf, path):
    m = re.search(r"(Spring|Summer|Autumn|Winter)\s*(\d{2})", path.stem, re.I)
    created = re.match(r"D:(\d{4})(\d{2})(\d{2})", (pdf.metadata or {}).get("CreationDate") or "")
    return {
        "title": f"{m.group(1).title()} 20{m.group(2)}" if m else "Allergen guide",
        "runs": None,
        "version": "-".join(created.groups()) if created else None,
    }


def products(pdf):
    """Yield {page, section, name, text} for every product in the guide's tables.

    Each product sits between solid black lines drawn across the whole table; dotted lines
    inside the right-hand column only separate its milk versions. The name is centred in the
    left-hand cell, so it can't be matched row by row."""
    section, current = "Menu", None
    for pno, page in enumerate(pdf.pages, start=1):
        solid = [o for o in page.lines if o["height"] < 1.5 and o["x0"] < page.width * 0.1
                 and o["x1"] > page.width * 0.9 and not o.get("dash")]
        if not solid:
            continue
        split = min((o["x0"] for o in page.lines if o.get("dash") and o["height"] < 1.5), default=page.width * 0.31)
        left, right = min(o["x0"] for o in solid), max(o["x1"] for o in solid)
        # Section headings sit on short coloured bars (green for the menu, a colour per city for pastries).
        # Product rows are white, grey or a pale tint of the city colour, and taller.
        def coloured(r):
            c = r.get("non_stroking_color") or ()
            return r.get("fill") and len(c) == 3 and max(c) - min(c) > 0.08
        bars = [r for r in page.rects if coloured(r) and r["width"] > (right - left) * 0.9 and r["height"] < 20]
        # a bar doesn't always have a ruled line above it, so its edges end the product before it
        tops = sorted({round(o["top"], 1) for o in solid} | {round(r["top"], 1) for r in bars} | {round(r["bottom"], 1) for r in bars})
        for a, b in zip(tops, tops[1:]):
            if b - a < 4:
                continue
            name_text = page.crop((left, a, split - 1, b)).extract_text() or ""
            decl = clean(page.crop((split, a, right, b)).extract_text() or "")
            if any(r["top"] <= a + 2 and r["bottom"] >= b - 2 for r in bars):  # green section bar
                head = clean(name_text + " " + decl)
                if head and head not in ("INGREDIENT LIST",) and not head.startswith("PRODUCT NAME"):
                    section = head.title().replace(" - ", ": ")
                continue
            if clean(name_text).upper().startswith("PRODUCT NAME"):
                continue
            # the name is the lines before the size and calorie lines ("Hot | S - 120 | L - 199 kcal")
            lines = [clean(x) for x in name_text.split("\n") if clean(x)]
            name_lines = []
            for x in lines:  # "Hot Harvest Chai" is a name; "Hot | S - 242 | L - 336 kcal" isn't
                if re.search(r"kcal|\|", x, re.I):
                    break
                name_lines.append(x)
            name = clean(" ".join(name_lines))
            if not name:
                if decl and current:  # a product carried over from the previous page
                    current["text"] = clean(current["text"] + " " + decl)
                continue
            if current:
                yield current
            current = {"page": pno, "section": section, "name": name, "text": decl}
    if current:
        yield current


def versions(text):
    """Split a drink into its milk versions: [(milk or None, ingredients, may_contain)]."""
    parts = VERSION.split(text)
    chunks = [(None, parts[0])] if clean(parts[0]) else []
    chunks += [(parts[i].lower(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    out = []
    for milk, chunk in chunks:
        m = re.search(r"May Contain\s*-\s*([^|]*)", chunk, re.I)
        ingredients = chunk[:m.start()] if m else chunk
        out.append((milk, ingredients, m.group(1) if m else ""))
    return out


def classify(p, warnings):
    item = {"name": p["name"], "section": p["section"], "sub": None, "pages": [p["page"]]}
    vs = []
    for milk, ingredients, may in versions(p["text"]):
        has = sorted({cereal(g) for g in CONTAINS.findall(ingredients)} - {"GLUTEN"} or
                     ({"GLUTEN"} if CONTAINS.search(ingredients) else set()))
        # "Oat (Gluten)" means oats: name the cereal, and only say "gluten" when no cereal is named
        maybe = sorted({cereal(g) for g in MAY.findall(may)} - {"CEREALS", "GLUTEN"} or ({"GLUTEN"} if MAY.search(may) else set()))
        vs.append({"milk": milk, "has": has, "may": maybe})
    if not vs:
        raise SystemExit(f"ERROR: p.{p['page']} {p['name']}: no ingredients found. Layout changed? Menu not updated.")
    milks = [v["milk"] for v in vs]
    if len(set(milks)) != len(milks) or (None in milks and len(milks) > 1):
        # two products run together: never guess which milk belongs to which drink
        raise SystemExit(f"ERROR: p.{p['page']} {p['name']}: versions {milks} don't belong to one drink. Layout changed? Menu not updated.")
    good = [v for v in vs if not v["has"] and not v["may"]]
    if not good:
        def why(v):
            what = ("contains " + " and ".join(x.lower() for x in v["has"])) if v["has"] else \
                   ("may contain " + " and ".join(x.lower() for x in v["may"]))
            return (f"With {v['milk']} milk: " if v["milk"] else "") + what
        reason = ". ".join(why(v)[:1].upper() + why(v)[1:] for v in vs) + "."
        all_contain = all(v["has"] for v in vs)
        out = {**item, "gluten": sorted({x for v in vs for x in v["has"] + v["may"]}), "reason": reason}
        if not all_contain:
            out["tag"] = "May contain gluten"
        return "avoid", out
    milks = [v for v in vs if v["milk"]]
    if not milks:
        return "ok", {**item, "order": "asis"}
    item["ok"] = [v["milk"] for v in milks if v in good]
    item["not"] = [v["milk"] for v in milks if v not in good]
    item["order"] = "except" if item["not"] else "any"
    return "ok", item


def newest_pdf(folder):
    return newest_by(folder, lambda pdf, p: guide_info(pdf, p)["version"])


def build(folder, config):
    pdf_path = newest_pdf(Path(folder) / "guides")
    print(f"  building from {pdf_path.name}")
    warnings, ok, avoid = [], [], []
    with pdfplumber.open(pdf_path) as pdf:
        info = guide_info(pdf, pdf_path)
        rows = list(products(pdf))
    if len(rows) < MIN_ROWS or not any("With DAIRY" in r["text"] for r in rows):
        raise SystemExit(f"ERROR: {pdf_path.name} doesn't look like Blank Street's allergen guide ({len(rows)} products). Menu not updated.")
    for r in rows:
        kind, item = classify(r, warnings)
        note = config.get("sectionInfo", {}).get(item["section"])
        if note:
            item["info"] = note
        (ok if kind == "ok" else avoid).append(item)
    return result(pdf_path.name, info,
                  "Blank Street: excludes anything whose ingredients list wheat, oats, barley, rye, spelt, kamut, gluten or malt, "
                  "or whose 'May Contain' line names oats, gluten or cereals containing gluten.", ok, avoid, warnings, rows=len(rows))
