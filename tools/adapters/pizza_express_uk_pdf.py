#!/usr/bin/env python3
"""
Reader for PizzaExpress's allergen guide for England, Scotland, Wales and Jersey (PDF): grids of dishes, drinks and
ingredients, a row per item and a column per allergen, then "Are these suitable for?" (Vegetarian, Vegan,
Coeliacs) and a "Please note" column whose cells can cover several rows. A tick means the item contains the
allergen (sometimes with a word under it, such as "Wheat" or "In Dressing"); an asterisk that one of its ingredients
is made where the allergen is present and the guide sees a significant risk of cross-contamination.

PizzaExpress is accredited by Coeliac UK; its own words are kept on the Warnings page. For each item:
  * a tick or asterisk under "Cereals Containing Gluten": Avoid. But when the note says it is "Suitable for coeliacs"
    with a change ("on a gluten-free base", "if served with gluten-free Dough Balls", "without the Wafer"), it's
    listed with that change, in the guide's own words.
  * no gluten mark and ticked for Coeliacs: no gluten ingredients.
  * no gluten mark but not ticked for Coeliacs: Avoid, because PizzaExpress doesn't say it suits coeliacs.
  * "we cannot guarantee any allergen or dietary requirements": Avoid, in the guide's words.
Columns are found from each page's rotated headers, because the drinks pages order them differently.
"""
import re
from datetime import date, timedelta
from pathlib import Path

import pdfplumber

from . import notices

TICK = "\u2713"
CEREALS = ["wheat", "oats", "oat", "barley", "rye", "spelt", "kamut", "gluten", "malt"]
MIN_ROWS = 200


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def guide_info(pdf):
    text = " ".join(pdf.pages[n].extract_text() or "" for n in range(min(2, len(pdf.pages))))
    m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\s+V(\d+)", text)
    months = "January February March April May June July August September October November December".split()
    version = f"{m.group(2)}-{months.index(m.group(1)) + 1:02d}-01" if m else None
    return {"title": "Allergen guide",
            "runs": None, "version": version}


def text_in(chars, box):
    """Text of the characters inside a box, line by line (an accent or a raised ® sits a little higher than its line)."""
    x0, top, x1, bottom = box
    inside = sorted((c for c in chars if x0 - 0.5 <= c["x0"] and c["x1"] <= x1 + 0.5 and top - 0.5 <= (c["top"] + c["bottom"]) / 2 <= bottom + 0.5),
                    key=lambda c: c["bottom"])
    lines = []
    for c in inside:
        if lines and c["bottom"] - lines[-1][0] <= 3:
            lines[-1][1].append(c)
        else:
            lines.append([c["bottom"], [c]])
    out = []
    for _, line in lines:
        line.sort(key=lambda c: c["x0"])
        text = ""
        for prev, c in zip([None] + line, line):
            if prev is not None and c["x0"] - prev["x1"] > 1:
                text += " "
            text += c["text"]
        out.append(text)
    return clean(" ".join(out))


def columns(page):
    """{header: (x centre)} from the rotated headers; a two-line header is two groups of letters close together."""
    # the small rotated headers; not a section banner's large heading, which can sit just below them
    hdr = sorted([c for c in page.chars if 30 < c["top"] < 115 and 130 < c["x0"] < 690 and c["text"].strip() and c["size"] < 9],
                 key=lambda c: c["x0"])
    groups = []
    for c in hdr:
        if groups and c["x0"] - groups[-1][-1]["x0"] < 3:
            groups[-1].append(c)
        else:
            groups.append([c])
    cols = []
    for g in groups:
        text = "".join(c["text"] for c in sorted(g, key=lambda c: c["top"]))
        x = sum((c["x0"] + c["x1"]) / 2 for c in g) / len(g)
        if cols and x - cols[-1][1] < 13:
            cols[-1] = (cols[-1][0] + " " + text, (cols[-1][1] + x) / 2)  # the two lines of one header
        else:
            cols.append((text, x))
    out = {}
    for text, x in cols:
        low = text.lower()
        key = ("gluten" if "gluten" in low or "cereal" in low else "coeliacs" if "coeliac" in low else
               "vegan" if low.strip() == "vegan" else "vegetarian" if "vegetarian" in low else low)
        out[key] = x
    return out


def rows(page, pno, section, warnings):
    """Yield one dict per item row on a grid page. Returns the section the page ends in."""
    cols = columns(page)
    for need in ("gluten", "coeliacs"):
        if need not in cols:
            raise SystemExit(f"ERROR: p.{pno}: no {need!r} column found. Layout changed? Menu not updated.")
    xs = sorted(cols.values())
    half = min(b - a for a, b in zip(xs, xs[1:])) / 2
    chars = page.chars
    cells = sorted((r for r in page.rects if r["x0"] < 20 and 100 < r["x1"] < 200 and r["top"] > 115 and r["height"] > 8),
                   key=lambda r: r["top"])
    cells = [r for i, r in enumerate(cells) if not any(abs(o["top"] - r["top"]) < 1 and abs(o["bottom"] - r["bottom"]) < 1 for o in cells[:i])]
    if not cells:
        return section
    name_right = max(r["x1"] for r in cells)
    note_left = max(cols.values()) + half + 2
    note_cells = sorted((r for r in page.rects if r["x0"] >= note_left - 6 and r["top"] > 115 and r["height"] > 8), key=lambda r: r["top"])
    # section banners: full-width bars between rows, with their heading in capitals
    banners = [r for r in page.rects if r["width"] > page.width * 0.8 and 8 < r["height"] < 30 and r["top"] > 100
               and not any(c["top"] - 1 <= r["top"] and r["bottom"] <= c["bottom"] + 1 for c in cells)]
    events = [(b["top"], "banner", b) for b in banners] + [(c["top"], "row", c) for c in cells]
    used = set()
    marks = [c for c in chars if c["text"] in (TICK, "*") and name_right < c["x0"] < note_left]
    for top, what, r in sorted(events, key=lambda e: e[0]):
        if what == "banner":
            head = text_in(chars, (r["x0"], r["top"], r["x1"], r["bottom"]))
            if head:
                head = re.split(r"\s+–\s+(?=\S+(?:\s+\S+){3})", head)[0]  # "PIZZAS – For pizzas listed on the main menu, refer to ..."
                head = re.sub(r"\s+([,)])", r"\1", re.sub(r"\(\s+", "(", head.replace("[", "(").replace("]", ")")))
                section = head.title()
            continue
        band = (r["top"], r["bottom"])
        name = text_in(chars, (r["x0"], r["top"], r["x1"], r["bottom"]))
        if not name:
            continue
        in_row = [m for m in marks if band[0] - 1 <= (m["top"] + m["bottom"]) / 2 <= band[1] + 1]
        got = {}
        for m in in_row:
            x = (m["x0"] + m["x1"]) / 2
            col = min(cols, key=lambda k: abs(cols[k] - x))
            if abs(cols[col] - x) > half + 1:
                raise SystemExit(f"ERROR: p.{pno} {name}: a mark at x={x:.0f} isn't under any column. Layout changed? Menu not updated.")
            got.setdefault(col, set()).add("tick" if m["text"] == TICK else "star")
            used.add(id(m))
        gx = cols["gluten"]
        gluten_words = text_in([c for c in chars if c["text"] not in (TICK, "*")], (gx - half, band[0], gx + half, band[1]))
        across = text_in(chars, (name_right + 2, band[0], note_left - 4, band[1]))
        note_cell = next((n for n in note_cells if n["top"] - 1 <= (band[0] + band[1]) / 2 <= n["bottom"] + 1), None)
        note = text_in(chars, (note_cell["x0"], note_cell["top"], note_cell["x1"], note_cell["bottom"])) if note_cell else ""
        yield {"page": pno, "section": section, "name": name, "marks": got, "gluten_words": gluten_words,
               "across": across, "note": note}
    stray = [m for m in marks if id(m) not in used and m["top"] > 115]
    if stray:
        raise SystemExit(f"ERROR: p.{pno}: {len(stray)} marks outside any item's row. Layout changed? Menu not updated.")
    return section


def tidy_name(raw):
    """'BBQ Chicken Wings [Dine-Out Exclusive]' -> name and the guide's own words about it."""
    notes = [f'The guide says: "{m.strip()}"' for m in re.findall(r"\[([^\]]+)\]", raw)]
    name = clean(re.sub(r"\[[^\]]*\]", " ", raw))
    name = clean(re.sub(r"\s*[-–]?\s*NEW(?:\s+RECIPE)?$", "", name))
    return name, notes


def coeliac_change(note):
    """'Suitable for coeliacs on a gluten-free base' -> 'With the GF base, please' (PizzaExpress marks its gluten
    free dishes GF), or None when the note offers no change."""
    m = re.search(r"Suitable for coeliacs\s+(?:if served\s+)?(with(?:out)?|on)\s+(?:an?\s+|the\s+)?(.+?)(?:\s*\*|$)", note, re.I)
    if not m:
        return None
    what = clean(re.sub(r"gluten[\s-]*free", "GF", m.group(2), flags=re.I)).rstrip(".").lower()
    what = re.sub(r"\bgf\b", "GF", re.sub(r"^the\s+", "", what))
    lead = {"with": "With", "without": "Without the", "on": "On the"}[m.group(1).lower()]
    return f"{lead} {what}, please"


def classify(r, extra, warnings):
    name, notes = tidy_name(r["name"])
    notes += extra
    item = {"name": name, "section": r["section"], "sub": None, "pages": [r["page"]]}
    gl = r["marks"].get("gluten", set())
    coeliac = "tick" in r["marks"].get("coeliacs", set())
    named = [c for c in CEREALS if re.search(rf"\b{c}\b", r["gluten_words"], re.I)]
    said = re.sub(r"gluten\s*-\s*free", "gluten-free", r["note"].split("*")[0].strip(), flags=re.I)
    quoted = f'PizzaExpress says: "{said}"' if said else None
    if re.search(r"cannot guarantee", r["across"], re.I):
        return "avoid", {**item, "gluten": ["GLUTEN"], "reason": f'The guide says: "{r["across"]}"', "tag": "Not guaranteed",
                         **({"info": " ".join(notes)} if notes else {})}
    if gl:
        change = coeliac_change(r["note"]) if "Suitable for coeliacs" in r["note"] else None
        if change:
            out = {**item, "order": "modify", "note": change, "info": " ".join(x for x in [quoted] + notes if x)}
            return "ok", out
        what = " and ".join(named) if named else "gluten"
        reason = ("Contains " if "tick" in gl else "May contain ") + what + "."
        if "tick" in gl and "star" in gl:
            reason = "Contains gluten (" + what + "), some of it as a may-contain."
        out = {**item, "gluten": [x.upper() for x in named] or ["GLUTEN"], "reason": reason}
        if "tick" not in gl:
            out["tag"] = "May contain gluten"
        if coeliac:
            warnings.append(f"p.{r['page']} {name}: ticked for coeliacs but with a gluten mark; treated as containing gluten")
            out["decided"] = "The guide ticks this as suitable for coeliacs but also marks gluten, so the app treats it as containing gluten."
        if notes:
            out["info"] = " ".join(notes)
        return "avoid", out
    if re.search(r"\boat", name, re.I):  # oats count as gluten here, gluten free oats included
        return "avoid", {**item, "gluten": ["OATS"], "reason": "Made with oat drink.", "tag": "Oats",
                         "decided": "The guide marks no gluten for this and ticks it for coeliacs (it uses gluten free oat drink), "
                                    "but this app counts oats as gluten, so it's on the Avoid list.",
                         **({"info": " ".join(notes)} if notes else {})}
    if not coeliac:
        return "avoid", {**item, "gluten": [], "reason": "PizzaExpress doesn't mark this as suitable for coeliacs, though the guide shows no gluten mark.",
                         "tag": "Not marked for coeliacs", **({"info": " ".join(notes)} if notes else {})}
    out = {**item, "order": "asis"}
    if re.search(r"gluten[\s-]*free", name, re.I):
        notes.append("Gluten free is PizzaExpress's own name for it.")
    if notes:
        out["info"] = " ".join(notes)
    return "ok", out


def newest_pdf(folder):
    dated = []
    for p in Path(folder).glob("*.pdf"):
        with pdfplumber.open(p) as pdf:
            first = pdf.pages[0].extract_text() or ""
            if "Allergen Information" not in first or "England" not in first:
                continue  # an ingredients list or another region's guide
            dated.append((guide_info(pdf)["version"] or "0000-00-00", p.stat().st_mtime, p))
    if not dated:
        raise SystemExit(f"ERROR: no PizzaExpress allergen guide in {folder}")
    dated.sort()
    for v, _, p in dated:
        print(f"  found {p.name} (version {v})")
    return dated[-1][2]


def build(folder, config):
    pdf_path = newest_pdf(Path(folder) / "guides")
    print(f"  building from {pdf_path.name}")
    warnings, ok, avoid, found = [], [], [], []
    with pdfplumber.open(pdf_path) as pdf:
        info = guide_info(pdf)
        section, breakfast = "Dishes", False
        for n, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if re.search(r"Breakfast at PizzaExpress", text) and "DOES IT CONTAIN" not in text:
                breakfast = True
                continue
            if "DOES IT CONTAIN" not in text:
                continue
            gen = rows(page, n, section, warnings)
            while True:
                try:
                    r = next(gen)
                except StopIteration as stop:
                    section = stop.value or section
                    break
                r["breakfast"] = breakfast
                if breakfast and "breakfast" not in r["section"].lower():  # the breakfast menu reuses "Drinks", "Ingredients"
                    r["section"] = "Breakfast " + r["section"][0].lower() + r["section"][1:]
                found.append(r)
        intro = [n for n in range(1, 4) if "DOES IT CONTAIN" not in (pdf.pages[n - 1].extract_text() or "")]
        guide_notices = notices.collect(pdf, intro)
    if len(found) < MIN_ROWS:
        raise SystemExit(f"ERROR: {pdf_path.name} doesn't look like PizzaExpress's allergen guide ({len(found)} rows). Menu not updated.")
    seen = set()
    for r in found:
        extra = ['The guide says breakfast is at "Selected Restaurants Only".'] if r["breakfast"] else []
        kind, item = classify(r, extra, warnings)
        key = (item["section"], item["name"].lower())
        if key in seen:
            warnings.append(f"p.{r['page']} {item['name']}: listed twice in {item['section']}")
            prev = next(i for i in ok + avoid if (i["section"], i["name"].lower()) == key)
            if kind == "avoid" and prev in ok:  # never let a duplicate hide gluten
                ok.remove(prev)
                avoid.append(item)
            continue
        seen.add(key)
        (ok if kind == "ok" else avoid).append(item)
    plain = lambda n: re.sub(r"[^a-z]", "", n.lower())
    dishes = {plain(i["name"]) for i in ok + avoid if "ingredients" not in i["section"].lower()}
    for i in ok + avoid:
        if "ingredients" in i["section"].lower() and plain(i["name"]) in dishes and "(ingredient)" not in i["name"]:
            i["name"] += " (ingredient)"
    if info["version"]:
        info["validUntil"] = (date.fromisoformat(info["version"]) + timedelta(days=int(config.get("recheckDays", 91)))).isoformat()
    return {
        "notices": guide_notices,
        "source": pdf_path.name,
        "guide": info,
        "rule": "PizzaExpress: lists items with no gluten mark that PizzaExpress ticks for coeliacs, and dishes with a gluten mark only "
                "with the change the guide says makes them suitable for coeliacs. Everything else is on the Avoid list.",
        "sections": list(dict.fromkeys(i["section"] for i in sorted(ok + avoid, key=lambda i: i["pages"][0]))),
        "items": ok,
        "avoid": avoid,
        "warnings": warnings,
        "stats": {"rows": len(found), "items": len(ok), "avoid": len(avoid)},
    }
