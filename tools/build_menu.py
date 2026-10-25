#!/usr/bin/env python3
"""
Build site/data/menu.json from a Starbucks UK beverage allergen guide (PDF).

Usage:
    python tools/build_menu.py                # newest PDF in menus/ -> site/data/menu.json
    python tools/build_menu.py path/to/guide.pdf [out.json]

How it decides "gluten free":
  * A drink (or a milk version of a drink) counts as containing gluten if its
    allergen column OR its ingredient list names a cereal containing gluten in
    BOLD CAPITALS: WHEAT, OAT(S), BARLEY, RYE, SPELT, KAMUT, GLUTEN or MALT.
    Oats are included because the guides list them under "cereals containing
    gluten".
  * Both columns are checked. If they disagree the row is treated as
    containing gluten and a warning is recorded, so a parsing slip can only
    ever hide a drink, never wrongly show one as safe.

The build stops with an error (and the live app keeps its previous menu) if
the PDF does not look like an allergen guide, so a bad upload can't wipe the
app.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
GLUTEN = re.compile(r"\b(WHEAT|OATS?|BARLEY|RYE|SPELT|KAMUT|GLUTEN|MALT)\b")
MILK_SUFFIX = re.compile(r"^(.*?)\s+[-–]\s+(.*\b(?:milk|drink))\s*(\(standard build\))?$", re.I)
STANDARD = re.compile(r"\s*\(standard build\)", re.I)
# Spelling slips in the source guides, corrected for display only.
TYPOS = {"Carmaelised": "Caramelised", "Hazenlut": "Hazelnut"}
MIN_ROWS = 100  # a real guide has several hundred rows


def clean(s):
    s = re.sub(r"\s+", " ", s or "").strip()
    for bad, good in TYPOS.items():
        s = s.replace(bad, good)
    return s


def milk_label(v):
    v = clean(v).lower().replace("semi- skimmed", "semi-skimmed").replace("semi skimmed", "semi-skimmed")
    return v


def short_milk(v):
    return re.sub(r"\s+(milk|drink)$", "", v)


def guide_info(pdf):
    """Season title, date range and version date from the cover pages."""
    text = "\n".join((pdf.pages[i].extract_text() or "") for i in range(min(3, len(pdf.pages))))
    version = re.search(r"Version:\s*(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
    vdate = None
    if version:
        d, m, y = (int(x) for x in version.groups())
        y = y + 2000 if y < 100 else y
        vdate = f"{y:04d}-{m:02d}-{d:02d}"
    title = re.search(r"\b(Spring|Summer|Autumn|Winter|Holiday|Festive)\b[^\n]*Beverages", text)
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
    rows, warnings = [], []
    table_pages = 0
    section, sub = "Other", None
    for pno, page in enumerate(pdf.pages, start=1):
        words = page.extract_words()
        hdr = {w["text"]: w for w in words if w["top"] < 130}
        if "Product" not in hdr or "Size" not in hdr:
            continue
        table_pages += 1
        size_x = hdr["Size"]["x0"]
        # Section name from the breadcrumb: "Nutrition & Allergen Guide | Beverages | <Section>"
        # Some pages have no breadcrumb text; they continue the previous section.
        crumb = clean(page.crop((0, 0, page.width, 40)).extract_text() or "")
        if "|" in crumb:
            new = re.sub(r"\s*Version:.*$", "", clean(crumb.split("|")[-1]))
            if new != section:
                section, sub = new, None
        allergen_x = min((o["x0"] for o in page.lines if abs(o["x1"] - page.width + 20) < 3 and o["x0"] > page.width * 0.85),
                         default=page.width * 0.93)
        # Row boundaries: separator lines drawn across the product column,
        # plus the edges of green sub-heading bars.
        bars = [r for r in page.rects if r["width"] > page.width * 0.7 and 8 < r["height"] < 30 and 95 < r["top"] < 525]
        bounds = {round(o["top"], 1) for o in page.lines + page.rects
                  if abs(o["x0"] - 20) < 3 and 80 < o["x1"] < 100 and 100 < o["top"] < 530}
        for b in bars:
            bounds |= {round(b["top"], 1), round(b["bottom"], 1)}
        bounds = sorted(bounds) + [525]
        for top, bot in zip(bounds, bounds[1:]):
            if bot - top < 5:
                continue

            def txt(x0, x1, tol=3):
                return clean(page.crop((x0, top, x1, bot)).extract_text(x_tolerance=tol) or "")

            name = txt(20, 90, tol=4)
            if not name:
                continue
            is_bar = any(abs(b["top"] - top) < 2 and abs(b["bottom"] - bot) < 2 for b in bars)
            sizes = txt(size_x - 3, size_x + 28)
            if is_bar or not sizes:
                sub = txt(20, page.width - 20, tol=4) if is_bar else name
                continue
            rows.append({
                "page": pno, "section": section, "sub": sub, "name": name,
                "ingredients": txt(90, size_x - 3),
                "allergens": txt(allergen_x, page.width - 20, tol=4),
            })
    if table_pages == 0 or len(rows) < MIN_ROWS:
        raise SystemExit(f"ERROR: {pdf_path.name} doesn't look like an allergen guide "
                         f"({table_pages} table pages, {len(rows)} rows). Menu not updated.")
    for r in rows:
        a = set(GLUTEN.findall(r["allergens"]))
        i = set(GLUTEN.findall(r["ingredients"]))
        r["gluten"] = sorted({g.rstrip("S") if g == "OATS" else g for g in a | i})
        if bool(a) != bool(i):
            warnings.append(f"p.{r['page']} {r['name']}: allergen column {sorted(a) or 'none'} vs "
                            f"ingredients {sorted(i) or 'none'}; treated as containing gluten")
        if not r["allergens"]:
            warnings.append(f"p.{r['page']} {r['name']}: allergen column empty; classified from ingredients")
    return info, rows, warnings


def group(rows):
    """Collapse milk versions into one drink each and decide how to order it."""
    drinks = {}
    for r in rows:
        m = MILK_SUFFIX.match(r["name"])
        if m:
            base, milk, std = clean(m.group(1)), milk_label(m.group(2)), bool(m.group(3))
        else:
            base, milk, std = clean(STANDARD.sub("", r["name"])), None, bool(STANDARD.search(r["name"]))
        # "Iced Brown Sugar Oat Shaken Espresso - oat drink" and "Iced Brown Sugar
        # Shaken Espresso - skimmed milk" are the same drink, so ignore "Oat" in the key.
        key = (r["section"], r["sub"] or "", re.sub(r"\s+Oat\b", "", base).lower())
        d = drinks.setdefault(key, {"names": [], "section": r["section"], "sub": r["sub"],
                                    "pages": [], "versions": []})
        d["names"].append(base)
        if r["page"] not in d["pages"]:
            d["pages"].append(r["page"])
        d["versions"].append({"milk": milk, "standard": std, "gluten": r["gluten"]})

    ok, avoid = [], []
    for d in drinks.values():
        name = max(d["names"], key=len)  # prefer the full name, e.g. the one with "Oat"
        vs = d["versions"]
        item = {"name": name, "section": d["section"], "sub": d["sub"], "pages": d["pages"]}
        good = [v for v in vs if not v["gluten"]]
        bad = [v for v in vs if v["gluten"]]
        if not good:
            # Report what every version shares (e.g. wheat), not the oat milk option.
            common = set.intersection(*(set(v["gluten"]) for v in bad))
            item["gluten"] = sorted(common or {g for v in bad for g in v["gluten"]})
            avoid.append(item)
            continue
        milks = [v for v in vs if v["milk"]]
        if not milks:
            item["order"] = "asis"
            ok.append(item)
            continue
        std = next((v for v in milks if v["standard"]), None)
        std_from = "guide" if std else None
        if std is None and re.search(r"\bOat\b", name):
            std = next((v for v in milks if short_milk(v["milk"]) == "oat"), None)
            std_from = "name" if std else None
        item["okMilks"] = [short_milk(v["milk"]) for v in milks if not v["gluten"]]
        item["notMilks"] = [short_milk(v["milk"]) for v in milks if v["gluten"]]
        if std:
            item["standard"] = short_milk(std["milk"])
            item["standardFrom"] = std_from
        if not item["notMilks"]:
            item["order"] = "any"
        elif std and std["gluten"]:
            item["order"] = "swap"
        else:
            item["order"] = "except"
        ok.append(item)
    return ok, avoid


def newest_pdf(folder):
    pdfs = [p for p in folder.glob("*.pdf")]
    if not pdfs:
        raise SystemExit(f"ERROR: no PDF found in {folder}")
    dated = []
    for p in pdfs:
        with pdfplumber.open(p) as pdf:
            v = guide_info(pdf)["version"] or "0000-00-00"
        dated.append((v, p.stat().st_mtime, p))
    dated.sort()
    for v, _, p in dated:
        print(f"  found {p.name} (version {v})")
    return dated[-1][2]


def main():
    args = sys.argv[1:]
    pdf_path = Path(args[0]) if args else newest_pdf(ROOT / "menus")
    out = Path(args[1]) if len(args) > 1 else ROOT / "site" / "data" / "menu.json"
    print(f"Building from {pdf_path.name}")
    info, rows, warnings = parse_rows(pdf_path)
    ok, avoid = group(rows)
    sections = list(dict.fromkeys(i["section"] for i in ok + avoid))
    menu = {
        "source": pdf_path.name,
        "guide": info,
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rule": "Excludes anything listing wheat, oats, barley, rye, spelt, kamut, gluten or malt.",
        "sections": sections,
        "drinks": ok,
        "avoid": avoid,
        "warnings": warnings,
        "stats": {"rows": len(rows), "drinks": len(ok), "avoid": len(avoid)},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(menu, indent=1, ensure_ascii=False))
    print(f"  {len(rows)} rows -> {len(ok)} gluten free drinks/add-ons, {len(avoid)} to avoid")
    print(f"  guide: {info}")
    for w in warnings:
        print("  WARNING:", w)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
