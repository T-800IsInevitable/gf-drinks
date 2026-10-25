"""
Reader for restaurants whose gluten free list is kept by hand in menu.csv.

Use this when a restaurant's allergen guide can't be read automatically
(a web page, an image, or a PDF laid out differently). One row per item:

  section   Menu section, e.g. "Burgers"
  name      Item name as it appears on the menu
  order     How to order it:
              asis    gluten free as listed
              any     gluten free with any of the options
              except  gluten free except with the options in "not"
              swap    normally comes with a "not" option, so ask for an "ok" one
              modify  gluten free only with a change, written in "note"
              avoid   contains gluten whatever you do
  ok        Options that are fine, separated by ";" (e.g. "skimmed;soya")
  not       Options to avoid, separated by ";" (e.g. "oat")
  standard  The option it normally comes with (for swap)
  contains  For avoid rows: what it contains, separated by ";" (e.g. "wheat")
  note      For modify rows: the change to ask for (e.g. "No croutons")
  page      Where in the source document this came from (optional)
  original  The item name in the menu's own language, if not English (optional)
  section_original  The section name in the menu's own language (optional)

Guide details (title, version date, end date, source) go in restaurant.json
under "guide".
"""
import csv
from pathlib import Path

ORDERS = {"asis", "any", "except", "swap", "modify", "avoid"}


def _split(v):
    return [x.strip() for x in (v or "").split(";") if x.strip()]


def build(folder, config):
    path = Path(folder) / "menu.csv"
    if not path.exists():
        raise SystemExit(f"ERROR: {path} not found")
    items, avoid, warnings = [], [], []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            name, order = row.get("name", ""), row.get("order", "").lower()
            if not name:
                continue
            if order not in ORDERS:
                raise SystemExit(f"ERROR: {path.name} line {n} ({name}): order must be one of {sorted(ORDERS)}")
            item = {"name": name, "section": row.get("section") or "Menu", "sub": None,
                    "pages": [row["page"]] if row.get("page") else []}
            if row.get("original") and row["original"] != name:
                item["original"] = row["original"]
            if row.get("section_original") and row["section_original"] != item["section"]:
                item["sectionOriginal"] = row["section_original"]
            if row.get("note") and order != "modify":
                item["info"] = row["note"]
            if order == "avoid":
                item["gluten"] = [g.upper() for g in _split(row.get("contains"))] or ["GLUTEN"]
                avoid.append(item)
                continue
            item["order"] = order
            if order in ("any", "except", "swap"):
                item["ok"], item["not"] = _split(row.get("ok")), _split(row.get("not"))
                if not item["ok"]:
                    raise SystemExit(f"ERROR: {path.name} line {n} ({name}): '{order}' needs at least one 'ok' option")
                if order == "swap":
                    item["standard"] = row.get("standard") or (item["not"][0] if item["not"] else "")
                    item["standardFrom"] = "guide"
            if order == "modify":
                if not row.get("note"):
                    raise SystemExit(f"ERROR: {path.name} line {n} ({name}): 'modify' needs a 'note'")
                item["note"] = row["note"]
            items.append(item)
    if not items and not avoid:
        raise SystemExit(f"ERROR: {path} has no rows")
    guide = config.get("guide", {})
    return {
        "source": guide.get("source") or path.name,
        "guide": {k: guide.get(k) for k in ("title", "runs", "version", "validUntil")},
        "rule": config.get("rule") or "Checked by hand against the restaurant's allergen information.",
        "sections": list(dict.fromkeys(i["section"] for i in items + avoid)),
        "items": items,
        "avoid": avoid,
        "warnings": warnings,
        "stats": {"rows": len(items) + len(avoid), "items": len(items), "avoid": len(avoid)},
    }
