#!/usr/bin/env python3
"""
Reader for Greggs' allergen guide (PDF): one grid per page, a product per row, and a column per allergen, with
"Cereals Containing Gluten" split into Wheat, Rye, Barley, Oats, Spelt (Wheat) and Kamut (Wheat). The marks are
text in a Wingdings font: a tick means the product contains it, a bullet that it may contain it. The last column,
"Gluten Free (GF)", marks the products Greggs itself calls gluten free.

For each product:
  * a tick under any cereal: contains gluten (Avoid)
  * a bullet under any cereal: may contain gluten (Avoid, with the reason)
  * no cereal marks: no gluten ingredients
A product Greggs marks as gluten free gets its claim quoted on the item; the app never makes the claim itself.
A product marked both gluten free and with a cereal is treated as containing gluten, with a warning.

The column headers are rotated, so they're read by position. The build stops if a cereal column is missing, or if
a mark doesn't sit under a column.
"""
import re
from datetime import date, timedelta
from pathlib import Path

import pdfplumber

from . import notices

TICK, BULLET = "\u2713", "\uf09f"
CEREALS = {"Wheat": "WHEAT", "Rye": "RYE", "Barley": "BARLEY", "Oats": "OATS", "Spelt (Wheat)": "SPELT", "Kamut (Wheat)": "KAMUT"}
GF_HEAD = "Gluten Free (GF)"
OTHERS = ["Soya", "Nuts", "Peanut", "Sesame", "Milk", "Eggs", "Fish", "Crustaceans", "Celery", "Sulphites", "Mustard", "Molluscs", "Lupin"]
# the guide's own labels after a name: "(NEW)", "(NEW / NEW RECIPE)", "(NEW RECIPE/ ALLERGEN UPDATE)", "(GF)", "(HS)"
LABEL = r"(?:NEW RECIPE|NEW|ALLERGEN UPDATE|GF|HS)"
LABELS = re.compile(rf"\s*\(\s*{LABEL}(?:\s*/\s*{LABEL})*\s*\)\s*", re.I)
MIN_ROWS = 150


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def guide_info(pdf):
    first = pdf.pages[0].extract_text() or ""
    v = re.search(r"Version\s+(\d+)", first)
    d = re.search(r"\b(\d{2})\.(\d{2})\.(\d{2})\b", first)
    return {
        "title": "Allergen guide",
        "runs": None,
        "version": f"20{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None,
    }


def columns(page):
    """{header: x centre} from the rotated header text, read bottom to top."""
    top = next((w["bottom"] for w in page.extract_words() if w["text"] == "Containing"), None)
    if top is None:
        return None
    # the contents key on the left uses the same tick and bullet, so only marks right of the name column count
    first_row = min((c["top"] for c in page.chars if c["text"] in (TICK, BULLET) and c["x0"] > page.width * 0.25), default=page.height)
    heads = [c for c in page.chars if top + 2 < c["top"] < first_row - 4 and c["text"].strip() and c["x0"] > page.width * 0.25]
    groups = []
    for c in sorted(heads, key=lambda c: c["x0"]):
        if groups and c["x0"] - groups[-1][-1]["x0"] < 4:
            groups[-1].append(c)
        else:
            groups.append([c])
    found = {}
    for g in groups:
        text = "".join(c["text"] for c in sorted(g, key=lambda c: -c["top"]))
        found[re.sub(r"[\s()]", "", text).lower()] = sum(c["x0"] + c["x1"] for c in g) / (2 * len(g))
    # rotated text loses its spaces and the GF header splits in two, so match without spaces or brackets
    out = {}
    for head in list(CEREALS) + [GF_HEAD] + OTHERS:
        key = re.sub(r"[\s()]", "", head).lower()
        hit = next((x for k, x in found.items() if k == key or (head == GF_HEAD and k.startswith("glutenfree"))), None)
        if hit is not None:
            out[head] = hit
    return out


def rows(pdf, pages, warnings, notes=None):
    """Yield {page, section, name, marks: {header: tick|bullet}, gf} for each product row. The guide's own notes
    (italic rows with no marks) go in notes as {text, page}."""
    section, last_title = None, None
    for pno in pages:
        page = pdf.pages[pno - 1]
        cols = columns(page)
        missing = [h for h in list(CEREALS) + [GF_HEAD] if h not in (cols or {})]
        if missing:
            raise SystemExit(f"ERROR: p.{pno}: columns {missing} not found. Layout changed? Menu not updated.")
        xs = sorted(cols.values())
        gap = min(b - a for a, b in zip(xs, xs[1:]))
        grid_left = xs[0] - gap / 2
        head_bottom = max(c["top"] for c in page.chars if c["text"] == "W" and abs((c["x0"] + c["x1"]) / 2 - cols["Wheat"]) < gap / 2)
        top_chars = [c for c in page.chars if c["top"] < head_bottom - 60]
        biggest = max((c["size"] for c in top_chars if c["text"].strip()), default=0)
        title = clean("".join(c["text"] if c["size"] > biggest - 0.5 else " " for c in sorted(top_chars, key=lambda c: (round(c["top"]), c["x0"]))))
        title = clean(title.rstrip("- "))
        if title.split(" ")[0] != (last_title or "").split(" ")[0]:  # a new part of the guide: not a continued page
            section = None
        last_title = title
        # rows are the grid's own cells under the allergen columns; a name over two lines (and its marks, centred
        # between them) is one taller cell
        cells = [r for r in page.rects if r["x0"] > grid_left - 2 and r["width"] < gap * 1.5 and 6 < r["height"] < 80 and r["top"] > head_bottom - 2]
        bands = sorted({(round(r["top"]), round(r["bottom"])) for r in cells})
        bands = [b for b in bands if not any(o != b and o[0] <= b[0] and o[1] >= b[1] for o in bands)]  # inner cells
        marks = [c for c in page.chars if c["text"] in (TICK, BULLET) and c["top"] > head_bottom]
        gf_marks = [c for c in page.chars if c["text"].strip() and c["top"] > head_bottom and abs((c["x0"] + c["x1"]) / 2 - cols[GF_HEAD]) < gap / 2
                    and c["text"] not in (TICK, BULLET)]
        inside = lambda c, b: b[0] - 1 <= (c["top"] + c["bottom"]) / 2 <= b[1] + 1
        used = set()
        for band in bands:
            chars = sorted((c for c in page.chars if c["x1"] < grid_left and c["text"].strip() and inside(c, band)),
                           key=lambda c: (round(c["top"]), c["x0"]))
            text = ""
            for prev, c in zip([None] + chars, chars):
                gap_before = prev is not None and (round(prev["top"]) != round(c["top"]) or c["x0"] - prev["x1"] > 1)
                text += (" " if gap_before else "") + c["text"]
            text = clean(text)
            row_marks = [m for m in marks if inside(m, band)]
            if not text:
                if row_marks:
                    raise SystemExit(f"ERROR: p.{pno}: marks on a row with no name. Layout changed? Menu not updated.")
                continue
            italic = all("Italic" in c["fontname"] for c in chars if c["text"] not in "*")
            bold = all("Bold" in c["fontname"] for c in chars)
            if not row_marks and italic:  # the guide's own note
                if notes is not None:
                    notes.append({"text": text.strip("*"), "page": pno})
                continue
            if not row_marks and bold:
                section = clean(re.sub(r"\s+continued$", "", text.strip("*"), flags=re.I))
                continue
            labels = " ".join(LABELS.findall(text)).upper()
            name = clean(LABELS.sub(" ", text.strip("*")))
            if not name:
                continue
            got = {}
            for m in row_marks:
                x = (m["x0"] + m["x1"]) / 2
                head = min(cols, key=lambda h: abs(cols[h] - x))
                if abs(cols[head] - x) > gap / 2:
                    raise SystemExit(f"ERROR: p.{pno} {name}: a mark at x={x:.0f} isn't under any column. Layout changed? Menu not updated.")
                got[head] = "tick" if m["text"] == TICK else "bullet"
                used.add(id(m))
            gf = any(inside(g, band) for g in gf_marks)
            # "Dipping Sauces – selected shops only": the section is the part before the dash, and the rest is the
            # guide's own words about its items, quoted on each one
            parts = re.split(r"\s+[–-]\s+", section or title, maxsplit=1)
            head, said = parts[0], clean(parts[1].strip("()")) if len(parts) > 1 else ""
            yield {"page": pno, "title": title, "section": clean(head), "said": said, "name": name, "marks": got, "gf": gf,
                   "hospital": "HS" in labels, "updated": "ALLERGEN UPDATE" in labels}
        stray = [m for m in marks if id(m) not in used]
        if stray:
            raise SystemExit(f"ERROR: p.{pno}: {len(stray)} marks not on any product's line. Layout changed? Menu not updated.")


def classify(r, warnings):
    item = {"name": r["name"], "section": r["section"], "sub": None, "pages": [r["page"]]}
    notes = []
    if r.get("said"):
        notes.append(f'The guide says: "{r["said"]}"')
    if r.get("hospital"):
        notes.append("The guide marks this HS (Hospital Shop).")
    if r.get("updated"):
        notes.append("The guide lists an allergen update for this item.")
    if notes:
        item["info"] = " ".join(notes)
    has = [CEREALS[h] for h in CEREALS if r["marks"].get(h) == "tick"]
    may = [CEREALS[h] for h in CEREALS if r["marks"].get(h) == "bullet"]
    claim = "Greggs calls this gluten free: it's marked GF in its allergen guide."
    if r["gf"] and (has or may):
        warnings.append(f"p.{r['page']} {r['name']}: marked gluten free and with a cereal; treated as containing gluten")
        named = " and ".join(x.lower() for x in has + may)
        item["decided"] = (f"The guide marks this as gluten free but also marks {named}, which this app counts as gluten, "
                           "so it's on the Avoid list.")
    if has or may:
        parts = []
        if has:
            parts.append("Contains " + " and ".join(x.lower() for x in has))
        if may:
            parts.append(("May contain " if not has else "may contain ") + " and ".join(x.lower() for x in may))
        out = {**item, "gluten": has or may, "reason": "; ".join(parts) + "."}
        if not has:
            out["tag"] = "May contain gluten"
        return "avoid", out
    out = {**item, "order": "asis"}
    if r["gf"]:
        out["info"] = " ".join(x for x in (item.get("info"), claim) if x)
    return "ok", out


def updates(pdf):
    """Names the guide lists under "Allergen Update" on its Product Updates page."""
    for page in pdf.pages[:6]:
        words = page.extract_words()
        head = next((w for w in words if w["text"].upper() == "ALLERGEN"), None)
        nxt = next((w for w in words if w["text"].upper() == "RECIPE" and head and w["x0"] > head["x1"]), None)
        if not head or not nxt:
            continue
        left = head["x0"] - 120
        right = nxt["x0"] - 120
        col = page.crop((max(left, 0), head["bottom"] + 4, right, page.height - 40))
        out = set()
        for line in (col.extract_text() or "").split("\n"):
            line = clean(line)
            if line and not re.search(r"\(Pages?\s", line):
                out.add(line.lower())
        return out
    return set()


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
        table = [n for n, pg in enumerate(pdf.pages, start=1) if "Cereals Containing Gluten" in (pg.extract_text() or "")]
        skip = set(config.get("skipPages") or [])
        table_notes = []
        found = [r for r in rows(pdf, [n for n in table if n not in skip], warnings, table_notes)]
        changed = updates(pdf)
        # the introduction's paragraphs; not the Product Updates table, which is read item by item above
        intro = [n for n in range(1, (table[0] if table else 4)) if n not in table
                 and "ALLERGEN UPDATE" not in (pdf.pages[n - 1].extract_text() or "").upper()]
        guide_notices = notices.collect(pdf, intro)
    guide_notices = [n for n in guide_notices if not n["text"].endswith("?")]  # a heading run into its question
    for n in guide_notices:  # Greggs' own gluten free claim and its definition, shown word for word as its claim
        if re.search(r"gluten free products|20 ?mg/kg|statement .gluten free", n["text"], re.I):
            n["kind"], n["label"] = "accreditation", notices.LABELS["accreditation"]
    for n in table_notes:
        if not any(n["text"] == o["text"] for o in guide_notices):
            guide_notices.append({"kind": "cross-contact", "label": notices.LABELS["cross-contact"], "text": n["text"],
                                  "pages": [n["page"]], "pagesTotal": 1})
    if len(found) < MIN_ROWS:
        raise SystemExit(f"ERROR: {pdf_path.name} doesn't look like Greggs' allergen guide ({len(found)} products). Menu not updated.")
    seen = {}
    for r in found:
        kind, item = classify(r, warnings)
        if item["name"].lower() in changed and "allergen update" not in (item.get("info") or ""):
            item["info"] = ((item.get("info") + " ") if item.get("info") else "") + "The guide lists an allergen update for this item."
        key = (item["section"], item["name"].lower())
        if key in seen:  # the same product twice in a section: keep one, and never let a duplicate hide gluten
            prev_kind, prev = seen[key]
            if prev_kind == "ok" and kind == "avoid":
                ok.remove(prev)
                avoid.append(item)
                seen[key] = (kind, item)
            continue
        seen[key] = (kind, item)
        (ok if kind == "ok" else avoid).append(item)
    if info["version"]:
        info["validUntil"] = (date.fromisoformat(info["version"]) + timedelta(days=int(config.get("recheckDays", 91)))).isoformat()
    return {
        "notices": guide_notices,
        "source": pdf_path.name,
        "guide": info,
        "rule": "Greggs: excludes anything the guide marks as containing, or maybe containing, wheat, rye, barley, oats, spelt or kamut.",
        "sections": list(dict.fromkeys(i["section"] for i in ok + avoid)),
        "items": ok,
        "avoid": avoid,
        "warnings": warnings,
        "stats": {"rows": len(found), "items": len(ok), "avoid": len(avoid)},
    }
