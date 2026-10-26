#!/usr/bin/env python3
"""
Reader for Pho's UK allergen guide (PDF): one allergen grid per page, with
the dishes down the left and an icon per allergen across the top.

The guide marks each cell with
  ●  contains the allergen, it cannot be removed
  ● on a pink cell  contains it, but the restaurant can remove it on request
  ▼  may have been fried in oil also used for something containing it
and writes the cereal under the mark ("wheat", "barley").

Only the "Cereals containing gluten" column is read:
  * nothing in it: no gluten ingredients (order as listed)
  * ● on pink: gluten that can be removed (order "modify", ask for it without)
  * ●, ▼, or a cereal named without a mark: avoid
Anything in that column that can't be matched to a dish stops the build, so a
layout change can't quietly publish a wrong menu.

Pho is accredited by Coeliac UK, so its guide makes a gluten free claim; its
own words are kept on the Warnings page (notices.py, "accreditation").
"""
import re
from pathlib import Path

import pdfplumber

from . import notices
from .common import CEREAL, MONTHS, cereal_code, cereal_word, clean, newest_by, result

RED = (0.02, 1.0, 0.85, 0.06)
PINK = (0.004, 0.21, 0.178, 0.013)
MIN_ROWS = 100


def close(a, b, tol=0.03):
    return a is not None and len(a) == len(b) and all(abs(x - y) < tol for x, y in zip(a, b))


def guide_info(pdf):
    text = " ".join((p.extract_text() or "") for p in pdf.pages[-3:])
    m = re.search(r"accurate as of (\w+) (\d{4})", text)
    version = f"{int(m.group(2)):04d}-{MONTHS[m.group(1)]:02d}-01" if m and m.group(1) in MONTHS else None
    return {"title": "Allergen guide", "runs": None, "version": version}


def lines_of(words):
    """Group words into text lines by their top edge."""
    out = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if out and abs(out[-1]["top"] - w["top"]) < 2.5:
            out[-1]["words"].append(w)
        else:
            out.append({"top": w["top"], "words": [w]})
    for ln in out:
        ln["words"].sort(key=lambda w: w["x0"])
        ln["size"] = max(w["size"] for w in ln["words"])
        ln["red"] = any(close(w.get("non_stroking_color"), RED, 0.05) for w in ln["words"])
        ln["text"] = clean(" ".join(w["text"] for w in ln["words"]))
    return out


def split_name(text):
    """'Wok fried noodles : phở xào' -> ('Wok fried noodles', 'phở xào')"""
    parts = [clean(p) for p in text.split(" : ", 1)]
    return (parts[0], parts[1]) if len(parts) == 2 else (text, None)


def styled_words(page):
    """Words with their largest font size and main colour. (Asking pdfplumber to split by size or colour
    breaks Vietnamese words apart at their accents, which are drawn in a different size.)"""
    words = page.extract_words()
    chars = page.chars
    for w in words:
        inside = [c for c in chars if w["x0"] - 0.5 <= c["x0"] <= w["x1"] and w["top"] - 3 <= c["top"] <= w["bottom"] and c["text"].strip()]
        w["size"] = max((c["size"] for c in inside), default=0)
        w["non_stroking_color"] = inside[0].get("non_stroking_color") if inside else None
    return words


def parse_page(page, pno, state):
    words = styled_words(page)
    crust = next((w for w in words if w["text"] == "Crustacea"), None)
    egg = next((w for w in words if w["text"] == "Egg" and crust and abs(w["top"] - crust["top"]) < 3), None)
    if not crust or not egg:
        return []
    colw = ((egg["x0"] + egg["x1"]) - (crust["x0"] + crust["x1"])) / 2
    gx = (crust["x0"] + crust["x1"]) / 2 - colw  # centre of "Cereals containing gluten"
    if not 25 < colw < 40:
        raise SystemExit(f"ERROR: p.{pno}: allergen columns are {colw:.0f}pt apart. Layout changed? Menu not updated.")
    cereal = next((w for w in words if w["text"] == "Cereals"), None)
    if cereal and abs((cereal["x0"] + cereal["x1"]) / 2 - gx) > 8:
        raise SystemExit(f"ERROR: p.{pno}: the gluten column isn't where expected. Layout changed? Menu not updated.")
    left, right = gx - colw / 2, gx + colw / 2
    legend = min((w["top"] for w in words if w["text"] == "contains" and w["top"] > page.height * 0.85), default=page.height)

    # The grid's dotted column lines run only beside dish rows, so they tell dishes from headings and footnotes.
    segs = sorted((l["top"], l["bottom"]) for l in page.lines if l["width"] < 1 and abs(l["x0"] - left) < 3)
    spans = []
    for a, b in segs:
        if spans and a <= spans[-1][1] + 6:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    in_grid = lambda y: any(a - 2 <= y <= b for a, b in spans)  # noqa: E731

    lines = lines_of([w for w in words if w["x1"] < left - 4 and 30 < w["top"] < legend - 2])

    header_end = crust["bottom"] + 15

    def full_text(ln):  # headings and footnotes run on across the grid columns (but not into its header)
        return clean(" ".join(w["text"] for w in sorted(words, key=lambda w: w["x0"])
                              if abs(w["top"] - ln["top"]) < 2.5 and not in_grid(w["top"] + 3)
                              and not (w["x0"] > left - 4 and w["top"] < header_end)))

    # Footnote asterisks are small coloured shapes, one colour per footnote, beside the dish and before the note.
    stars = [(o, tuple(round(x, 2) for x in o.get("non_stroking_color") or ())) for o in page.curves
             if 4 < o["width"] < 7.5 and o["height"] < 8 and o["x1"] < left - 4 and not close(o.get("non_stroking_color"), RED, 0.05)]

    def star_at(top, x_from=0):
        return next((col for o, col in stars if abs(o["top"] - top) < 5 and o["x0"] >= x_from), None)

    rows, footnotes = [], []
    head_top = -99
    for ln in lines:
        mid = ln["top"] + 3
        small = clean(" ".join(w["text"] for w in ln["words"] if w["size"] < 11)) if ln["red"] else ""
        if in_grid(mid):
            if rows and ln["top"] - rows[-1]["top"] < 9:
                rows[-1]["lines"].append(ln)
            else:
                rows.append({"top": ln["top"], "lines": [ln], "sub": None if ln["size"] >= 13 else state["sub"],
                             "section": state["section"], "sectionOriginal": state["sectionOriginal"], "headNote": state["note"]})
        elif ln["red"] and ln["size"] >= 14:
            state["section"], state["sectionOriginal"] = split_name(" ".join(w["text"] for w in ln["words"] if w["size"] >= 14))
            state["sub"], state["note"], head_top = None, small or None, ln["top"]
        elif ln["red"] and ln["size"] >= 11:
            head = clean(" ".join(w["text"] for w in ln["words"] if w["size"] >= 11))
            if not head.lower().startswith("cont"):  # "Cont..." carries on the previous sub-heading
                # the first sub-heading under a section keeps the section's note ("Includes spring roll")
                state["note"] = small or (state["note"] if state["sub"] is None else None)
                state["sub"], head_top = head, ln["top"]
        elif ln["size"] < 9.5 and ln["top"] - head_top < 9:  # "- WITHOUT sauce" beside or under a heading
            state["note"] = full_text(ln)
        elif ln["red"] or ln["size"] < 9.5:
            footnotes.append({"text": full_text(ln), "colour": star_at(ln["top"])})
        else:
            raise SystemExit(f"ERROR: p.{pno}: text {ln['text']!r} isn't a dish, heading or footnote. Layout changed? Menu not updated.")

    # Each row owns the band from just above its name to just above the next row (or the end of its grid span).
    for n, r in enumerate(rows):
        span_end = next(b for a, b in spans if a - 2 <= r["top"] + 3 <= b)
        nxt = rows[n + 1]["top"] - 6 if n + 1 < len(rows) else span_end
        r["band"] = (r["top"] - 6, min(nxt, span_end + 1))
        # A row is one line on the page, though its smaller words sit a little lower: read it left to right.
        ws = sorted((w for ln in r["lines"] for w in ln["words"]), key=lambda w: w["x0"])
        name = clean(" ".join(w["text"] for w in ws if not close(w.get("non_stroking_color"), (0.66, 0.15, 1.0, 0.0), 0.05)))  # green "vg"
        # "Daura Damm *" points to a footnote; "* Spring roll added to the bún dish" is itself the explanation
        r["star"] = star_at(r["top"], ws[0]["x1"]) or ("*" in name and not name.startswith("*"))
        name = clean(re.sub(r"\(see bottle label\)", "", name).replace("*", ""))
        # "THIS™ isn't chicken" (a brand) has its ™ drawn as a separate superscript "TM"
        name = re.sub(r"\bTHIS\s*TM\b", "THIS™", name)
        name = re.sub(r"\bTHIS\b(?!™)", "THIS™", re.sub(r"\s+TM\b", "", name))
        r["name"] = clean(name.replace(" )", ")").replace("( ", "(").replace(" ,", ","))
        r["note"] = max(w["size"] for w in ws) < 9.5 and not any(ln["red"] for ln in r["lines"])
        r["marks"], r["labels"], r["pink"] = [], [], False

    def owner(y):
        return next((r for r in rows if r["band"][0] <= y < r["band"][1]), None)

    stray = []
    for c in page.curves:
        cx, cy = (c["x0"] + c["x1"]) / 2, (c["top"] + c["bottom"]) / 2
        if not (left < cx < right) or not close(c.get("non_stroking_color"), RED, 0.05) or cy < (spans[0][0] if spans else 0):
            continue
        r = owner(cy)
        if r is None:
            if cy < legend - 4:
                stray.append(round(cy))
            continue
        round_mark = abs(c["width"] - c["height"]) < 1 and c["width"] < 9
        r["marks"].append("dot" if round_mark else "fried")
    for rect in page.rects:
        if close(rect.get("non_stroking_color"), PINK) and rect["x0"] < gx < rect["x1"]:
            for r in rows:
                overlap = min(rect["bottom"], r["band"][1]) - max(rect["top"], r["band"][0])
                if overlap > 0.5 * (r["band"][1] - r["band"][0]):
                    r["pink"] = True
    for w in words:
        # headings beside the grid can run across this column; only text inside the grid is a label
        if left < (w["x0"] + w["x1"]) / 2 < right and in_grid(w["top"] + 2):
            r = owner(w["top"])
            if r:
                r["labels"] += [x for x in re.split(r"[,\s]+", w["text"].lower()) if x]
            else:
                stray.append(round(w["top"]))
    if stray:
        raise SystemExit(f"ERROR: p.{pno}: marks in the gluten column at y={stray} don't line up with a dish. Menu not updated.")
    for r in rows:
        r["page"], r["footnotes"] = pno, footnotes
    return rows


def classify(r, config, warnings):
    if r["note"]:  # e.g. "See adult menu section for full info on soup stocks"
        return "note", None
    item = {"name": r["name"], "section": r["section"], "sub": r["sub"], "pages": [r["page"]]}
    if r["sectionOriginal"]:
        item["sectionOriginal"] = r["sectionOriginal"]
    info = []
    if r.get("headNote"):
        info.append("The guide lists it " + clean(r["headNote"].lstrip("- ").replace("*", "")) + ".")
    if r["star"]:  # the footnote with the same colour of asterisk (or every footnote, for a plain "*"), quoted as the guide's
        info += ['The guide says: "' + clean(f["text"].lstrip("* ")) + '"' for f in r["footnotes"]
                 if f["colour"] == r["star"] or r["star"] is True or f["colour"] is None]
    if info:
        item["info"] = " ".join(info).replace("..", ".")
    codes = sorted({cereal_code(c) for c in r["labels"] if CEREAL.fullmatch(c)})
    cereals = [cereal_word(c) for c in codes]
    gluten = codes or ["GLUTEN"]
    where = f"p.{r['page']} {r['name']}"
    if not r["marks"] and not r["labels"] and not r["pink"]:
        return "ok", {**item, "order": "asis"}
    if "fried" in r["marks"]:
        return "avoid", {**item, "gluten": gluten, "tag": "Shared fryer",
                         "reason": "The guide marks it as possibly fried in oil also used for something containing gluten."}
    if r["marks"] == ["dot"] and r["pink"]:
        # removeNotes: {"<section starts with>": {"note": "<what to ask for>", "why": "<optional extra detail>"}}
        hint = next((h for sec, h in config.get("removeNotes", {}).items() if r["section"].startswith(sec)), {})
        why = " ".join(x for x in ("The guide says the gluten can be removed on request.", hint.get("why")) if x)
        item["info"] = clean(" ".join(x for x in (item.get("info"), why) if x))
        return "ok", {**item, "order": "modify", "note": hint.get("note") or "Without gluten, please"}
    if "dot" in r["marks"]:
        return "avoid", {**item, "gluten": gluten}
    warnings.append(f"{where}: gluten column has {'a pink cell' if r['pink'] else 'the word ' + ', '.join(r['labels'])} "
                    "but no mark; treated as containing gluten")
    why = "The guide names " + (", ".join(cereals) or "gluten") + " for this without its usual mark, so it's treated as containing gluten."
    return "avoid", {**item, "gluten": gluten, "reason": why, "decided": why}


def newest_pdf(folder):
    return newest_by(folder, lambda pdf, p: guide_info(pdf)["version"])


def build(folder, config):
    pdf_path = newest_pdf(Path(folder) / "guides")
    print(f"  building from {pdf_path.name}")
    warnings, ok, avoid, rows = [], [], [], []
    with pdfplumber.open(pdf_path) as pdf:
        info = guide_info(pdf)
        state = {"section": "Menu", "sectionOriginal": None, "sub": None, "note": None}
        table = []
        for pno, page in enumerate(pdf.pages, start=1):
            got = parse_page(page, pno, state)
            if got:
                table.append(pno)
                rows += got
        if len(rows) < MIN_ROWS:
            raise SystemExit(f"ERROR: {pdf_path.name} doesn't look like Pho's allergen guide ({len(rows)} dishes). Menu not updated.")
        text_pages = [n for n in range(1, len(pdf.pages) + 1) if n not in table]
        guide_notices = notices.collect(pdf, text_pages, columns_for=[2])
    for r in rows:
        kind, item = classify(r, config, warnings)
        if kind != "note":
            (ok if kind == "ok" else avoid).append(item)
    return result(pdf_path.name, info,
                  "Pho: excludes anything with a mark or a cereal named in the guide's gluten column, unless the guide says the gluten can be removed.",
                  ok, avoid, warnings, guide_notices, rows=len(rows))
