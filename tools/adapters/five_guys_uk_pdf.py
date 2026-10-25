"""
Reader for Five Guys UK's allergen, ingredient and nutrition guide (one tall PDF page).

The allergen grid has 14 columns (one per legal allergen, shown by icons).
In each cell:
  * a red dot  = contains the allergen
  * "1"        = "Not suitable for this allergen sufferer due to manufacturing
                  and preparation methods" (cross-contact)
  * "2"        = not suitable during breakfast hours because of cooking methods

For gluten ("Cereals containing gluten", the 8th column):
  * a dot or a "1" means the item is listed as containing gluten / unsafe,
    so it goes in the avoid list with the reason shown;
  * a "2" means it needs avoiding at breakfast time (shown as needing a change);
  * blank means no gluten ingredients and no preparation warning.

The ingredient listing further down is checked too: any item whose ingredients
name WHEAT, RYE, BARLEY, OATS, SPELT, KAMUT or GLUTEN in bold capitals must
have a gluten mark in the grid. If they disagree, the item is treated as
containing gluten and a note is recorded. The build stops if the grid can't be
read (wrong number of allergen columns, marks outside any row, and so on).
"""
import re
from pathlib import Path

import pdfplumber

from . import notices

GLUTEN_COL = 7  # 0-based position of "Cereals containing gluten" among the 14 allergen icons
GLUTEN_WORDS = re.compile(r"\b(WHEAT|RYE|BARLEY|OATS?|SPELT|KAMUT|GLUTEN)\b")
LEGEND = {
    "1": "Not suitable for this allergen sufferer due to manufacturing and preparation methods.",
    "2": "Due to cooking methods used not suitable for allergy sufferers during Breakfast operation hours.",
}
MIN_ROWS = 60


def clean(s):
    s = re.sub(r"[​-‍﻿]", "", s or "")
    return re.sub(r"\s+", " ", s).strip()


def norm_name(s):
    s = re.sub(r"\*+|®|°|\(.*?\)", "", s or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def find_heading(words, text):
    return next((w for w in words if w["text"] == text), None)


def band_rows(page, top, bottom, left_max):
    """Row bands from the table's horizontal rules between top and bottom."""
    ys = sorted({round(l["top"], 1) for l in page.lines
                 if top <= l["top"] <= bottom and l["x0"] < left_max and (l["x1"] - l["x0"]) > 150 and abs(l["top"] - l["bottom"]) < 1.5})
    rows = []
    for a, b in zip(ys, ys[1:]):
        if b - a >= 12:
            rows.append((a, b))
    return rows


def parse(pdf_path):
    pdf = pdfplumber.open(pdf_path)
    page = pdf.pages[0]
    words = page.extract_words(extra_attrs=["fontname", "non_stroking_color"])
    ing_head = find_heading(words, "INGREDIENT")
    nut_head = find_heading(words, "NUTRITION")
    if not ing_head or not nut_head:
        raise SystemExit("ERROR: couldn't find the INGREDIENT / NUTRITION sections. Layout changed? Menu not updated.")
    icons = sorted((i for i in page.images if i["top"] < ing_head["top"] and i["width"] < 80), key=lambda i: i["x0"])
    if len(icons) != 14:
        raise SystemExit(f"ERROR: expected 14 allergen icons, found {len(icons)}. Layout changed? Menu not updated.")
    centres = [(i["x0"] + i["x1"]) / 2 for i in icons]
    col_w = min(b - a for a, b in zip(centres, centres[1:]))
    gx = centres[GLUTEN_COL]
    grid_top = max(i["bottom"] for i in icons)
    grid_bottom = ing_head["top"] - 20
    name_right = centres[0] - col_w / 2

    # section bars: black full-width rectangles with white titles
    bars = [r for r in page.rects if grid_top < r["top"] < grid_bottom and r["width"] > 1000 and r["height"] > 20]
    rows_out, warnings = [], []
    marks = [c for c in page.chars if grid_top < c["top"] < grid_bottom and c["text"] in ("•", "1", "2")
             and abs((c["x0"] + c["x1"]) / 2 - gx) < col_w / 2]
    used = set()
    # each product row is the gap between consecutive horizontal rules in the name column
    rules = sorted({round(r["top"], 1) for r in page.rects if grid_top < r["top"] < grid_bottom and r["width"] > 1000} |
                   {round(r["bottom"], 1) for r in page.rects if grid_top < r["top"] < grid_bottom and r["width"] > 1000} |
                   {round(l["top"], 1) for l in page.lines if grid_top < l["top"] < grid_bottom and l["x0"] < name_right
                    and (l["x1"] - l["x0"]) > 100})
    section = None
    for a, b in zip(rules, rules[1:]):
        if b - a < 12:
            continue
        mid = lambda o: (o["top"] + o["bottom"]) / 2
        bar = next((r for r in bars if abs(r["top"] - a) < 2 and abs(r["bottom"] - b) < 2), None)
        cell = [w for w in words if a <= mid(w) <= b and w["x0"] < name_right]
        if bar:
            title = [w for w in words if a <= mid(w) <= b and w["x1"] < bar["x1"] + 2]  # bar titles run past the name column
            section = clean(" ".join(w["text"] for w in sorted(title, key=lambda w: w["x0"])))
            continue
        if not cell:
            continue
        lines = {}
        for w in sorted(cell, key=lambda w: (round(w["top"]), w["x0"])):
            lines.setdefault(round(w["top"]), []).append(w)
        first = list(lines.values())[0]
        bold = [w["text"] for w in first if "Light" not in w["fontname"] and "Regular" not in w["fontname"]]
        rest = [w["text"] for w in first if w["text"] not in bold] + [w["text"] for ws in list(lines.values())[1:] for w in ws]
        # names can wrap onto a second bold line
        for ws in list(lines.values())[1:2]:
            if all("Light" not in w["fontname"] and "Regular" not in w["fontname"] for w in ws):
                bold += [w["text"] for w in ws]
                rest = [t for t in rest if t not in [w["text"] for w in ws]]
        raw = clean(" ".join(bold)) or clean(" ".join(w["text"] for w in first))
        stars = len(re.search(r"\*+$", raw).group(0)) if re.search(r"\*+$", raw) else 0
        name = clean(raw.rstrip("*"))
        cell_marks = [m for m in marks if a <= mid(m) <= b]
        for m in cell_marks:
            used.add(id(m))
        kinds = {("dot" if m["text"] == "•" else m["text"]) for m in cell_marks}
        rows_out.append({"section": section or "Menu", "name": name, "info": clean(" ".join(rest)), "stars": stars,
                         "marks": sorted(kinds)})
    stray = [m for m in marks if id(m) not in used]
    if stray:
        raise SystemExit(f"ERROR: {len(stray)} gluten-column mark(s) not matched to a row. Menu not updated.")
    if len(rows_out) < MIN_ROWS:
        raise SystemExit(f"ERROR: only {len(rows_out)} rows read from the allergen grid. Menu not updated.")

    # ingredient listing: name in the left column, ingredients to the right, under section bars
    ing = {}
    ing_bars = [r for r in page.rects if ing_head["bottom"] < r["top"] < nut_head["top"] - 20 and r["width"] > 1000 and r["height"] > 20]
    ing_section = None
    ing_rows = sorted({round(l["top"], 1) for l in page.lines if ing_head["bottom"] < l["top"] < nut_head["top"] - 20
                       and l["x0"] < 120 and (l["x1"] - l["x0"]) > 150} |
                      {round(r[k], 1) for r in page.rects if ing_head["bottom"] < r["top"] < nut_head["top"] - 20 and r["width"] > 1000
                       for k in ("top", "bottom")})
    split_x = 400
    for a, b in zip(ing_rows, ing_rows[1:]):
        if b - a < 12:
            continue
        mid = lambda o: (o["top"] + o["bottom"]) / 2
        if any(abs(r["top"] - a) < 2 and abs(r["bottom"] - b) < 2 for r in ing_bars):
            ing_section = clean(" ".join(w["text"] for w in sorted([w for w in words if a <= mid(w) <= b], key=lambda w: w["x0"])))
            continue
        left = [w for w in words if a <= mid(w) <= b and w["x0"] < split_x - 5]
        right = [w for w in words if a <= mid(w) <= b and w["x0"] >= split_x - 5]
        if not left or not right:
            continue
        nm = clean(" ".join(w["text"] for w in sorted(left, key=lambda w: (round(w["top"]), w["x0"]))))
        text = clean(" ".join(w["text"] for w in sorted(right, key=lambda w: (round(w["top"]), w["x0"]))))
        ing.setdefault(norm_name(nm), []).append(((ing_section or "").split(" ")[0].upper(), text))

    version = None
    m = re.search(r"FGUK_(\d{4})(\d{2})(\d{2})", page.extract_text() or "") or re.search(r"(\d{4})(\d{2})(\d{2})", Path(pdf_path).name)
    if m:
        version = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # footnotes (legend at the top, notes under the nutrition table) for the warnings page
    foot = [w for w in words if w["text"].startswith("*Products")]
    regions = {1: [(0, foot[0]["top"] - 5, page.width, foot[0]["top"] + 130)]} if foot else {}
    guide_notices = notices.collect(pdf, [], regions=regions)
    # the "1"/"2" key sits inside the legend and doesn't extract as clean sentences; quote it
    # word for word, after confirming the wording is in this edition of the guide
    flat = clean(page.crop((0, max(0, grid_top - 300), name_right, grid_top)).extract_text() or "").lower()
    key = []
    for code, text in LEGEND.items():
        probe = "manufacturing and preparation methods" if code == "1" else "breakfast operation hours"
        if probe not in flat:
            raise SystemExit(f"ERROR: the guide's key for '{code}' has changed. Menu not updated.")
        key.append({"kind": "cross-contact", "label": "Five Guys' allergen key", "text": f"“{code}”: {text}",
                    "pages": [1], "pagesTotal": 1})
    guide_notices = key + guide_notices
    return rows_out, ing, version, guide_notices, warnings


def build(folder, config):
    pdfs = sorted(Path(folder, "guides").glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"ERROR: no PDF in {folder}/guides")
    # newest by the date in the guide (FGUK_YYYYMMDD), else by file name
    dated = []
    for p in pdfs:
        with pdfplumber.open(p) as pdf:
            m = re.search(r"FGUK_(\d{8})", pdf.pages[0].extract_text() or "")
        dated.append((m.group(1) if m else "", p.name, p))
    pdf_path = sorted(dated)[-1][2]
    print(f"  building from {pdf_path.name}")
    rows, ing, version, guide_notices, warnings = parse(pdf_path)
    stars_note = {1: "Available at participating locations only.", 2: "Available in non-halal stores only.",
                  3: "Not available at the Heathrow Airport location."}
    items, avoid = [], []
    seen = set()
    for r in rows:
        key = (r["section"], r["name"].lower())
        if key in seen:
            continue
        seen.add(key)
        # same name can appear in two sections (the Meat "Hot Dog" sausage vs the Hot Dogs "Hot Dog" in a bun)
        cands = ing.get(norm_name(r["name"]), [])
        first = r["section"].split(" ")[0].upper()
        match = [t for sec, t in cands if sec == first] or ([cands[0][1]] if len(cands) == 1 else [])
        ingredients = match[0] if match else None
        if len(cands) > 1 and not match:
            warnings.append(f"{r['name']}: several ingredient entries and none in section {r['section']}; grid used alone")
        listed = sorted(set(GLUTEN_WORDS.findall(ingredients or "")))
        sec_full = r["section"]
        paren = re.search(r"\((.*?)\)", sec_full)
        sec = re.sub(r"\s*\(.*?\)", "", sec_full).strip().title()
        sec = re.sub(r"\b(In|And|Of)\b", lambda m: m.group(1).lower(), sec).replace("Mix-Ins", "Mix-ins")
        item = {"name": r["name"], "section": sec, "sub": None, "pages": [1]}
        info = []
        if paren and "available" in paren.group(1).lower():
            # "(SANDWICHES AVAILABLE AT HEATHROW ONLY)" is about the sandwiches in the section, not its coffees
            kind = re.match(r"(\w+?)e?s\s+available", paren.group(1), re.I)
            if not kind or kind.group(1).lower() in r["name"].lower():
                info.append(paren.group(1)[0].upper() + paren.group(1)[1:].lower().replace("heathrow", "Heathrow") + ".")
        if r["info"]:
            info.append(r["info"])
        if r["stars"]:
            info.append(stars_note.get(r["stars"], ""))
        if info:
            item["info"] = " ".join(i for i in info if i)
        if "dot" in r["marks"] or (listed and "1" not in r["marks"]):
            if listed and "dot" not in r["marks"]:
                warnings.append(f"{r['name']}: ingredients list {listed} but the grid has no gluten dot; treated as containing gluten")
            item["gluten"] = [g.rstrip("S") if g == "OATS" else g for g in listed] or ["GLUTEN"]
            avoid.append(item)
        elif "1" in r["marks"]:
            item["gluten"] = ["PREPARATION"]
            item["tag"] = "Not suitable"
            item["reason"] = "Five Guys marks this “1” for gluten: " + LEGEND["1"]
            avoid.append(item)
        elif "2" in r["marks"]:
            item["order"] = "modify"
            item["note"] = "Not at breakfast time"
            item["info"] = (item.get("info", "") + " Five Guys: " + LEGEND["2"]).strip()
            items.append(item)
        else:
            item["order"] = "asis"
            items.append(item)
    sections = list(dict.fromkeys(i["section"] for i in items + avoid))
    from datetime import date, timedelta
    valid = (date.fromisoformat(version) + timedelta(days=int(config.get("recheckDays", 91)))).isoformat() if version else None
    return {
        "notices": guide_notices,
        "source": pdf_path.name,
        "guide": {"title": "Allergen guide", "runs": None, "version": version, "validUntil": valid},
        "rule": "Excludes anything Five Guys marks for cereals containing gluten, either as an ingredient (dot) or as not suitable because of preparation (1).",
        "sections": sections,
        "items": items,
        "avoid": avoid,
        "warnings": warnings,
        "stats": {"rows": len(rows), "items": len(items), "avoid": len(avoid)},
    }
