#!/usr/bin/env python3
"""
Reader for Caffè Nero's "Allergen, Nutritional & Ingredient Guide (GB)" (PDF), which has three parts:

  * food (pages headed PRODUCT / INGREDIENTS / NUTRITIONAL INFO): each product's ingredients, with allergens in
    bold capitals. A product is one block, from its "per 100g" line to its "Portion weight" line.
  * drinks (pages titled "... Beverage Nutritional & Allergen Information"): one row per drink and milk
    ("Cappuccino - Oat"), with an ALLERGENS column. Rows run from one drawn rule to the next.
  * an allergen grid for some food ("This Product Contains", with a Gluten column), used here to cross-check
    the food pages: if the two disagree, the item is treated as containing gluten.

Food contains gluten if its ingredients name wheat, rye, barley, oats, spelt, kamut, malt or gluten (not "gluten
free"); the guide says it lists oats as an allergen even when they're gluten free oats. A drink with a milk
that brings gluten (oat drink) is listed with the other milks. Pages that show how to read the guide (with a
sample product) are skipped.
"""
import re
from collections import defaultdict
from difflib import SequenceMatcher
from datetime import date, timedelta
from pathlib import Path

import pdfplumber

from . import notices

CEREAL = re.compile(r"\b(wheat\w*|rye|barley|oats?|oatmeal|oatly|spelt|kamut|malt(?:ed)?|gluten(?![\s-]*free))\b", re.I)
DRINK_GLUTEN = re.compile(r"^(WHEAT|RYE|BARLEY|OATS?|SPELT|KAMUT|MALT|GLUTEN|CEREALS?)$")
ALLERGENS = {"MILK", "SOYA", "ALMONDS", "NUTS", "NONE", "EGG", "EGGS", "PEANUTS", "FISH", "CELERY", "MUSTARD", "LUPIN",
             "SESAME", "SULPHITES", "SULPHUR", "DIOXIDE", "CRUSTACEANS", "MOLLUSCS", "HAZELNUTS", "COCONUT"}
SIZES = {"Regular", "Grande", "Small", "Medium", "Large", "Single", "Double", "Triple"}
DIET = {"Vegetarian", "Vegan", "DIETARY"}
MILKS = [(r"semi(\s+skimmed)?(\s+milk)?", "semi-skimmed"), (r"skimmed(\s+milk)?", "skimmed"), (r"whole(\s+milk)?", "whole"),
         (r"soya", "soya"), (r"coconut", "coconut"), (r"oat", "oat"), (r"almond", "almond"), (r"black", "black")]
MIN_FOOD, MIN_DRINKS = 60, 80


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def norm(name):
    return re.sub(r"[^a-z]", "", re.sub(r"\bnew\b", "", name.lower()))


def guide_info(pdf):
    m = re.search(r"Issued:\s*(\d{2})/(\d{2})/(\d{2})", pdf.pages[0].extract_text() or "")
    return {"title": "Allergen guide", "runs": None,
            "version": f"20{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None}


def lines_of(words, tol=2.0):
    """Group words into visual lines (by vertical centre), each sorted left to right."""
    out = []
    for w in sorted(words, key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"])):
        mid = (w["top"] + w["bottom"]) / 2
        if out and abs(out[-1][0] - mid) <= tol:
            out[-1][1].append(w)
        else:
            out.append([mid, [w]])
    return [sorted(ws, key=lambda w: w["x0"]) for _, ws in out]


def segments(line, gap=6):
    """Split a line where the space between words is wider than a word gap (two columns side by side)."""
    out = [[line[0]]]
    for a, b in zip(line, line[1:]):
        if b["x0"] - a["x1"] > gap:
            out.append([b])
        else:
            out[-1].append(b)
    return out


def kind_of(page):
    text = page.extract_text() or ""
    if re.search(r"HOW TO USE THIS GUIDE|Within this guide you will find", text):
        return "example"
    if "Beverage Nutritional & Allergen Information" in text:
        return "drinks"
    if "This Product Contains" in text:
        return "grid"
    if "INGREDIENTS" in text and "NUTRITIONAL INFO" in text:
        return "food"
    return None


# ---------- grid (cross-check) ----------
def grid_rows(page, pno):
    """[(section, name, contains gluten, page)] from the allergen grid's Gluten column. A name over two lines sits
    closer to the line above (about 3pt) than separate rows do (5pt or more)."""
    words = page.extract_words()
    heads = [w for w in words if w["text"] == "Gluten"]
    if not heads:
        raise SystemExit(f"ERROR: p.{pno}: allergen grid without a Gluten column. Layout changed? Menu not updated.")
    gx = sum((w["x0"] + w["x1"]) / 2 for w in heads) / len(heads)
    left = min(w["x0"] for w in heads) - 8
    stars = [c for c in page.chars if c["text"] == "*" and c["x0"] > left]
    rows, section = [], None
    for line in lines_of([w for w in words if w["x1"] < left and w["top"] > 100 and w["bottom"] < page.height - 40]):
        text = clean(" ".join(w["text"] for w in line))
        if text == "Product Name":
            continue
        if text.isupper():
            section, rows = text, rows + [None]
            continue
        if rows and rows[-1] is not None and line[0]["top"] - rows[-1]["bottom"] < 4.2:
            rows[-1].update(name=rows[-1]["name"] + " " + text, bottom=line[-1]["bottom"])
        else:
            rows.append({"section": section, "name": text, "top": line[0]["top"], "bottom": line[-1]["bottom"]})
    out, used = [], set()
    for r in filter(None, rows):
        hit = [c for c in stars if r["top"] - 3 <= (c["top"] + c["bottom"]) / 2 <= r["bottom"] + 3]
        used |= {id(c) for c in hit}
        gluten = any(abs((c["x0"] + c["x1"]) / 2 - gx) < 15 for c in hit)
        out.append((r["section"] or "", r["name"], gluten, pno))
    if any(id(c) not in used for c in stars):
        raise SystemExit(f"ERROR: p.{pno}: marks in the allergen grid outside any product's row. Layout changed? Menu not updated.")
    return out


def likeness(a, b, same_section):
    """How surely two names are one product. The grid and the food pages word some products differently ("Banan and
    Walnut Loaf Cake", "Rocky Road Traybake", "Porridge with ..." for "Porridge made with ..."), but "Cinnamon" (the
    spice) isn't the "Cinnamon Bun": an exact name always wins, and one word inside another only counts in its section."""
    if norm(a) == norm(b):
        return 10
    stop = {"and", "with", "made", "or"}
    ta, tb = set(re.findall(r"[a-z]+", a.lower())) - stop, set(re.findall(r"[a-z]+", b.lower())) - stop
    r = SequenceMatcher(None, norm(a), norm(b)).ratio()
    if ta == tb:
        return 9
    if ta and tb and (ta <= tb or tb <= ta):
        if min(len(ta), len(tb)) >= 2:
            return 5 + r
        if same_section:
            return 4 + r
    return r if r >= 0.85 else 0


# ---------- food ----------
def food_rows(page, pno, section):
    words = page.extract_words(extra_attrs=["fontname", "size"])
    heads = {w["text"]: w for w in words if w["text"] in ("PRODUCT", "INGREDIENTS", "NUTRITIONAL")}
    if len(heads) < 3:
        raise SystemExit(f"ERROR: p.{pno}: food page without its column headings. Layout changed? Menu not updated.")
    centre = {k: (w["x0"] + w["x1"]) / 2 for k, w in heads.items()}
    nutrition_left = heads["NUTRITIONAL"]["x0"] - 80
    starts = sorted(w["top"] for w in words if w["text"] == "100g")
    ends = sorted(w["bottom"] for w in words if w["text"] == "Portion")
    if len(starts) != len(ends) or any(e < s for s, e in zip(starts, ends)):
        raise SystemExit(f"ERROR: p.{pno}: {len(starts)} 'per 100g' lines but {len(ends)} 'Portion weight' lines. Layout changed? Menu not updated.")
    bands = list(zip(starts, ends))
    header_bars = [r for r in page.rects if r["height"] > 8 and isinstance(r.get("non_stroking_color"), tuple)
                   and max(r["non_stroking_color"]) < 0.3]
    left_bold = [round(w["size"], 1) for w in words if "Bold" in w["fontname"] and w["x1"] < centre["PRODUCT"] + 40
                 and any(s - 30 <= w["top"] <= e for s, e in bands)]
    if not left_bold:
        raise SystemExit(f"ERROR: p.{pno}: no product names found. Layout changed? Menu not updated.")
    name_size = max(set(left_bold), key=left_bold.count)
    # section headings: capitals, centred, outside every product's block
    head_lines = [l for l in lines_of([w for w in words if w["top"] > 80 and w["x1"] < nutrition_left and
                                       not any(s - 4 <= w["top"] <= e + 4 for s, e in bands)])]
    events = []
    for l in head_lines:
        text = clean(" ".join(w["text"] for w in l))
        if text.isupper() and text not in ("PRODUCT INGREDIENTS", "PRODUCT", "INGREDIENTS") and not text.startswith("PRODUCT "):
            events.append((l[0]["top"], "section", text))
    for s, e in bands:
        events.append((s, "band", (s, e)))
    for top, what, val in sorted(events, key=lambda x: x[0]):
        if what == "section":
            section = val.title().replace("&", "&")
            continue
        s, e = val
        # the name and ingredients are centred in their block, which can start a little above "per 100g"
        inside = [w for w in words if s - 30 <= w["top"] and w["bottom"] <= e + 4 and w["x1"] < nutrition_left
                  and not any(b["top"] - 1 <= (w["top"] + w["bottom"]) / 2 <= b["bottom"] + 1 for b in header_bars)]
        # the name is bold, in the product column's own size; an ingredient line can start right beside it (and
        # its allergens are bold too, but in the ingredients' size)
        is_name = lambda w: "Bold" in w["fontname"] and abs(w["size"] - name_size) < 0.3 and w["x0"] < centre["PRODUCT"] + 100
        name = clean(" ".join(w["text"] for line in lines_of([w for w in inside if is_name(w)]) for w in line))
        ingredients = clean(" ".join(w["text"] for line in lines_of([w for w in inside if not is_name(w)]) for w in line))
        yield pno, section, name, ingredients
    return section


def tidy_food_name(raw):
    """'NEW Chocolate and Hazelnut Croissant* (V) *Available at selected stores only' -> name, notes, gf claim."""
    notes = []
    # where it's sold: "*Available at selected stores only", "Only available at selected stores", "(Airport Stores Only)"
    m = re.search(r"\(?\*?\s*((?:only\s+)?available at selected stores(?:\s+only)?|airport stores only)\s*\)?", raw, re.I)
    if m:
        notes.append(f'The guide says: "{clean(m.group(1))}"')
        raw = raw[:m.start()] + raw[m.end():]
    gf = bool(re.search(r"\([^)]*\bGF\b[^)]*\)", raw))  # "(GF)", "(Vg, GF)"
    raw = re.sub(r"\(\s*(?:V|Vg|GF)(?:\s*,\s*(?:V|Vg|GF))*\s*\)", " ", raw, flags=re.I)
    raw = re.sub(r"^\s*NEW\s+", "", raw)
    return clean(raw.replace("*", "")), notes, gf


# ---------- drinks ----------
def drink_rows(page, pno, warnings):
    text = page.extract_text() or ""
    lines = [clean(x) for x in text.split("\n")]
    title_i = next(i for i, x in enumerate(lines) if "Beverage Nutritional & Allergen Information" in x)
    section = re.sub(r"^NEW\s+", "", lines[title_i + 1]).title()
    words = page.extract_words()
    bars = sorted((r for r in page.rects if r["height"] > 8 and r["width"] > 400 and isinstance(r.get("non_stroking_color"), tuple)
                   and max(r["non_stroking_color"]) < 0.3), key=lambda r: r["top"])
    # the rules under each row; not the edges of a header bar
    rules = sorted({round(r["top"], 1) for r in list(page.rects) + list(page.lines)
                    if r["width"] > 200 and abs(r["bottom"] - r["top"]) < 2.5
                    and not any(b["top"] - 3 <= r["top"] <= b["bottom"] + 3 for b in bars)})
    events = [(b["bottom"], 0, "bar", b) for b in bars] + [(t, 1, "rule", None) for t in rules]
    # a table's last row may have no rule under it: close it at its last line of figures before the next table
    limits = [b["top"] for b in bars[1:]] + [page.height - 40]
    for lim, b in zip(limits, bars):
        last = max((t for t in rules if b["bottom"] < t < lim), default=b["bottom"])
        # a line of figures, not a number in a description ("2 shots of espresso")
        figures = [ln[0]["bottom"] for ln in lines_of([w for w in words if last < w["top"] < lim and re.fullmatch(r"[\d.]+", w["text"])])
                   if len(ln) >= 5]
        if figures:
            events.append((max(figures) + 2, 1, "rule", None))
    events.sort(key=lambda x: x[:2])
    start, cols, standard, prev_end, table = None, None, None, 0, 0
    for top, _, what, bar in events:
        if what == "bar":
            table += 1
            # the table's own description, above its header: "*Served with Oat as standard"
            above = clean(" ".join(w["text"] for w in words if prev_end <= w["top"] < bar["top"] - 1))
            m = re.search(r"(?:Served|Made)\s+with\s+(\w+)\s+as\s+standard", above, re.I)
            standard = split_drink("x - " + m.group(1))[1] if m else None
            start = bar["bottom"]
            inbar = [w for w in words if bar["top"] - 2 <= w["top"] <= bar["bottom"] + 2]
            cols = {w["text"]: w for w in inbar if w["text"] in ("PRODUCT", "ALLERGENS", "DIETARY", "SIZE")}
            if "PRODUCT" not in cols or "ALLERGENS" not in cols:
                raise SystemExit(f"ERROR: p.{pno}: a drinks table without PRODUCT and ALLERGENS. Layout changed? Menu not updated.")
            continue
        if start is None or top - start < 6:
            start = top if start is not None else None
            continue
        band = [w for w in words if start - 1 <= (w["top"] + w["bottom"]) / 2 <= top + 1]
        start = prev_end = top
        numbers = [w["x0"] for w in band if re.fullmatch(r"[\d.]+", w["text"])]
        if not numbers:  # a drink's row always has its nutrition figures; anything else isn't a row
            if any(w["text"].strip(",").isupper() and DRINK_GLUTEN.match(w["text"].strip(",")) for w in band):
                raise SystemExit(f"ERROR: p.{pno}: a gluten allergen outside any drink's row. Layout changed? Menu not updated.")
            continue
        right = min(numbers) - 4 if numbers else page.width
        name_words, found = [], []
        for w in band:
            t = w["text"].strip(",")
            if w["x0"] >= right or t in SIZES or t in DIET:
                continue
            if t.isupper() and len(t) > 1:
                found.append(t)
            else:
                name_words.append(w)
        if not name_words:
            if found:
                raise SystemExit(f"ERROR: p.{pno}: allergens {found} on a row with no drink. Layout changed? Menu not updated.")
            continue
        name = clean(" ".join(w["text"] for line in lines_of(name_words) for w in line))
        unknown = [t for t in found if not DRINK_GLUTEN.match(t) and t not in ALLERGENS]
        if unknown:
            raise SystemExit(f"ERROR: p.{pno} {name}: unknown allergen words {unknown}. Layout changed? Menu not updated.")
        yield {"page": pno, "table": (pno, table), "section": section, "name": name, "standard": standard,
               "gluten": sorted({t for t in found if DRINK_GLUTEN.match(t)})}


def split_drink(name):
    m = re.match(r"(.+?)(?:\s+-\s*|\s*-\s+)(.+)$", name)
    if not m:
        return name, None
    base, variant = clean(m.group(1)), clean(m.group(2))
    for pat, milk in MILKS:
        if re.fullmatch(pat, variant, re.I):
            return base, milk
    return base, variant.lower()


def page_notices(pdf, drinks_pages):
    """The guide's own warnings: its introduction (food and drinks) and the notes over drinks tables."""
    intro = [n for n in range(1, len(pdf.pages) + 1) if "Within this guide you will find" in (pdf.pages[n - 1].extract_text() or "")]
    # the introduction pages also show a sample product; its table isn't a warning
    found = [n for n in notices.collect(pdf, intro) if not re.search(r"\bKJ\b|\bKcal\b|PRODUCT", n["text"])]
    for n in drinks_pages:
        text = clean(pdf.pages[n - 1].extract_text() or "")
        for s in re.findall(r"Nutritional & Allergen information does not include whipped cream\.", text, re.I):
            s = clean(s)
            if not any(s == o["text"] for o in found):
                found.append({"kind": "coverage", "label": notices.LABELS["coverage"], "text": s, "pages": [n], "pagesTotal": 1})
    return found


def newest_pdf(folder):
    dated = []
    for p in Path(folder).glob("*.pdf"):
        with pdfplumber.open(p) as pdf:
            dated.append((guide_info(pdf)["version"] or "0000-00-00", p.stat().st_mtime, p))
    if not dated:
        raise SystemExit(f"ERROR: no PDF found in {folder}")
    dated.sort()
    for v, _, p in dated:
        print(f"  found {p.name} (version {v})")
    return dated[-1][2]


def build(folder, config):
    pdf_path = newest_pdf(Path(folder) / "guides")
    print(f"  building from {pdf_path.name}")
    warnings, ok, avoid = [], [], []
    with pdfplumber.open(pdf_path) as pdf:
        info = guide_info(pdf)
        kinds = {n: kind_of(pdf.pages[n - 1]) for n in range(1, len(pdf.pages) + 1)}
        grid = [r for n, k in kinds.items() if k == "grid" for r in grid_rows(pdf.pages[n - 1], n)]
        food, section = [], "Pastries"
        for n, k in kinds.items():
            if k == "food":
                gen = food_rows(pdf.pages[n - 1], n, section)
                for row in gen:
                    food.append(row)
                    section = row[1]
        drinks = [r for n, k in kinds.items() if k == "drinks" for r in drink_rows(pdf.pages[n - 1], n, warnings)]
        guide_notices = page_notices(pdf, [n for n, k in kinds.items() if k == "drinks"])
    if len(food) < MIN_FOOD or len(drinks) < MIN_DRINKS:
        raise SystemExit(f"ERROR: {pdf_path.name} doesn't look like Caffè Nero's guide ({len(food)} foods, {len(drinks)} drinks). Menu not updated.")

    seen = set()
    for pno, section, raw, ingredients in food:
        name, notes, gf = tidy_food_name(raw)
        if not name or not ingredients:
            raise SystemExit(f"ERROR: p.{pno}: a food block with no name or no ingredients ({raw!r}). Layout changed? Menu not updated.")
        key = (section, name.lower())
        if key in seen:
            warnings.append(f"p.{pno} {name}: listed twice in {section}; kept the first")
            continue
        seen.add(key)
        item = {"name": name, "section": section, "sub": None, "pages": [pno]}
        cereals = sorted({c.lower() for c in CEREAL.findall(ingredients)})
        cereals = sorted({"oats" if c.startswith("oat") else ("wheat" if c.startswith("wheat") else c) for c in cereals})
        if gf:
            notes.append("Caffè Nero calls this gluten free: it's marked GF in its guide.")
        elif re.search(r"gluten[\s-]*free", name, re.I):
            notes.append("Gluten free is Caffè Nero's own name for it; the app lists it because its ingredients name no gluten cereal.")
        if notes:
            item["info"] = " ".join(notes)
        if cereals:
            avoid.append({**item, "gluten": [c.upper() for c in cereals], "reason": "The ingredients list " + " and ".join(cereals) + "."})
        else:
            ok.append({**item, "order": "asis"})

    # the allergen table: a second source for some food (where the two disagree, it contains gluten), and the only one
    # for some extras, sauces and syrups
    for gsection, gname, gluten, gpage in grid:
        scored = [(likeness(gname, i["name"], gsection.title() == i["section"]), n, i) for n, i in enumerate(ok + avoid)
                  if "Only in the guide" not in (i.get("info") or "")]
        best = max(scored, key=lambda x: x[:2], default=(0, 0, None))
        match = best[2] if best[0] > 0 else None
        if match is not None and best[0] < 10:
            warnings.append(f"p.{gpage} allergen table's {gname!r} read as {match['name']!r}")
        if match is None:
            item = {"name": gname, "section": gsection.title(), "sub": None, "pages": [gpage],
                    "info": "Only in the guide's allergen table, which lists allergens but not ingredients."}
            if gluten:
                avoid.append({**item, "gluten": ["GLUTEN"], "reason": "The guide's allergen table marks gluten."})
            else:
                ok.append({**item, "order": "asis"})
            continue
        if gluten and match in ok:
            warnings.append(f"p.{gpage} {gname}: the allergen table marks gluten but the ingredients don't; treated as containing gluten")
            ok.remove(match)
            match.pop("order", None)
            avoid.append({**match, "gluten": ["GLUTEN"], "reason": "The guide's allergen table marks gluten.",
                          "decided": "The guide's allergen table marks gluten but its ingredient list doesn't name a gluten "
                                     "cereal, so the app treats it as containing gluten."})
        elif not gluten and match in avoid:
            warnings.append(f"p.{gpage} {gname}: the ingredients name gluten but the allergen table doesn't mark it; kept on the Avoid list")

    # Each table is one drink in its milks. The guide sometimes words a row differently ("Iced Spiced PecanLatte - Oat",
    # or a "Luxury Frappe Crème" row in the "Frappe Crème" table), so rows are grouped by table, not by exact name;
    # a table only holds several drinks when a milk repeats in it.
    key = lambda base: re.sub(r"[^a-z]", "", base.lower())
    tables = defaultdict(list)
    for d in drinks:
        tables[d["table"]].append((d, *split_drink(d["name"])))
    groups = defaultdict(lambda: {"variants": {}, "page": None, "standard": None, "name": None})
    for rows in tables.values():
        variants = [v for _, _, v in rows]
        names = [b for _, b, _ in rows]
        if len(set(variants)) == len(variants) and len({key(b) for b in names}) > 1:
            common = max(set(names), key=names.count)
            odd = sorted({b for b in names if b != common})
            warnings.append(f"p.{rows[0][0]['page']}: {odd} read as {common!r}, the drink in the same table")
            rows = [(d, common, v) for d, _, v in rows]
        for d, base, variant in rows:
            g = groups[(d["section"], key(base))]
            g["name"] = g["name"] or base
            g["page"] = g["page"] or d["page"]
            g["standard"] = g["standard"] or d["standard"]
            prev = g["variants"].get(variant, [])
            g["variants"][variant] = sorted(set(prev) | set(d["gluten"]))  # listed twice: never let one copy hide gluten
    for (section, _), g in groups.items():
        base = g["name"]
        item = {"name": base, "section": section, "sub": None, "pages": [g["page"]]}
        vs = g["variants"]
        if list(vs) == [None]:
            if vs[None]:
                avoid.append({**item, "gluten": vs[None], "reason": "The guide lists " + " and ".join(x.lower() for x in vs[None]) + "."})
            else:
                ok.append({**item, "order": "asis"})
            continue
        if None in vs:
            raise SystemExit(f"ERROR: {base}: listed both with and without a milk. Layout changed? Menu not updated.")
        good = [v for v, gl in vs.items() if not gl]
        bad = [v for v, gl in vs.items() if gl]
        if not good:
            avoid.append({**item, "gluten": sorted({x for gl in vs.values() for x in gl}),
                          "reason": "Every version lists " + " and ".join(sorted({x.lower() for gl in vs.values() for x in gl})) + "."})
            continue
        out = {**item, "ok": good, "not": bad, "order": "except" if bad else "any"}
        if g["standard"] in vs:
            out["standard"], out["standardFrom"] = g["standard"], "guide"
            if g["standard"] in bad:
                out["order"] = "swap"
        ok.append(out)

    if info["version"]:
        info["validUntil"] = (date.fromisoformat(info["version"]) + timedelta(days=int(config.get("recheckDays", 91)))).isoformat()
    return {
        "notices": guide_notices,
        "source": pdf_path.name,
        "guide": info,
        "rule": "Caffè Nero: excludes food whose ingredients name wheat, rye, barley, oats, spelt, kamut, malt or gluten, "
                "and drinks with a milk the guide lists with a gluten cereal (oat).",
        "sections": list(dict.fromkeys(i["section"] for i in sorted(ok + avoid, key=lambda i: i["pages"][0]))),
        "items": ok,
        "avoid": avoid,
        "warnings": warnings,
        "stats": {"rows": len(food) + len(drinks), "items": len(ok), "avoid": len(avoid)},
    }
