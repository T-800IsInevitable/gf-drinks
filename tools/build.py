#!/usr/bin/env python3
"""
Build the app's data for every restaurant in restaurants/.

Each restaurant is a folder with a restaurant.json naming the reader that
understands its allergen information (see tools/adapters/). Folders starting
with "_" or "." are skipped (use them for templates and drafts).

Writes:
  site/data/restaurants.json   list of restaurants with summary details
  site/data/r/<id>.json        one restaurant's full gluten free menu

If any restaurant fails to build, the whole build stops and nothing is
published, so the live app keeps its previous menus.

Usage:
  python tools/build.py               # all restaurants
  python tools/build.py starbucks-uk  # just one (for testing)
"""
import calendar
import importlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
MONTHS = {m: i for i, m in enumerate(calendar.month_name) if m}


def end_date(runs):
    """'September to November 2026' -> '2026-11-30' (last day of the end month)."""
    m = re.search(r"(\w+)\s+to\s+(\w+)\s+(\d{4})", runs or "")
    if not m or m.group(2) not in MONTHS:
        return None
    y, mo = int(m.group(3)), MONTHS[m.group(2)]
    return f"{y:04d}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}"


def build_one(folder):
    config = json.loads((folder / "restaurant.json").read_text(encoding="utf-8"))
    reader = config.get("reader")
    if not reader:
        raise SystemExit(f"ERROR: {folder.name}/restaurant.json has no 'reader'")
    print(f"{config.get('name', folder.name)} ({reader})")
    data = importlib.import_module(f"adapters.{reader}").build(folder, config)
    guide = data.setdefault("guide", {})
    guide["validUntil"] = guide.get("validUntil") or end_date(guide.get("runs"))
    meta = {
        "id": folder.name,
        "name": config["name"],
        "type": config.get("type", ""),
        "covers": config.get("covers", ""),
        "optionLabel": config.get("optionLabel", "option"),
        "officialUrl": config.get("officialUrl", ""),
        "tips": config.get("tips", []),
    }
    print(f"  {data['stats']['rows']} rows -> {data['stats']['items']} gluten free, {data['stats']['avoid']} to avoid")
    for w in data.get("warnings", []):
        print("  WARNING:", w)
    return meta, data


def main():
    only = set(sys.argv[1:])
    out = ROOT / "site" / "data"
    (out / "r").mkdir(parents=True, exist_ok=True)
    built = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    index = []
    folders = sorted(p for p in (ROOT / "restaurants").iterdir()
                     if p.is_dir() and not p.name.startswith(("_", ".")) and (not only or p.name in only))
    if not folders:
        raise SystemExit("ERROR: no restaurants found")
    for folder in folders:
        meta, data = build_one(folder)
        full = {**meta, **data, "built": built}
        (out / "r" / f"{meta['id']}.json").write_text(json.dumps(full, indent=1, ensure_ascii=False), encoding="utf-8")
        index.append({**meta, "guide": data["guide"], "source": data["source"], "stats": data["stats"],
                      "file": f"data/r/{meta['id']}.json"})
    (out / "restaurants.json").write_text(json.dumps({"built": built, "restaurants": index}, indent=1, ensure_ascii=False),
                                          encoding="utf-8")
    print(f"Wrote {len(index)} restaurant(s) to {out}")


if __name__ == "__main__":
    main()
