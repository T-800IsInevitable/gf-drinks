#!/usr/bin/env python3
"""
Build the app's data for every restaurant in restaurants/.

Each restaurant is a folder with a restaurant.json naming the reader that
understands its allergen information (see tools/adapters/). A restaurant with
more than one guide (e.g. drinks and food) lists several: "readers": [...].
Folders starting with "_" or "." are skipped (use them for templates and drafts).

Writes:
  site/data/restaurants.json   list of restaurants with summary details
  site/data/r/<id>.json        one restaurant's full gluten free menu

If .previous/ holds the menus that are live now (tools/fetch_previous.py),
each restaurant also gets "changes": what's different since the last guide.

If any restaurant fails to build, the whole build stops and nothing is
published, so the live app keeps its previous menus.

Usage:
  python tools/build.py               # all restaurants
  python tools/build.py starbucks-uk  # just one (for testing)
  python tools/build.py --previous DIR  # compare with menus saved somewhere else
"""
import argparse
import calendar
import importlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import changes  # noqa: E402  (needs the path above)

MONTHS = {m: i for i, m in enumerate(calendar.month_name) if m}


def end_date(runs):
    """'September to November 2026' -> '2026-11-30' (last day of the end month)."""
    m = re.search(r"(\w+)\s+to\s+(\w+)\s+(\d{4})", runs or "")
    if not m or m.group(2) not in MONTHS:
        return None
    y, mo = int(m.group(3)), MONTHS[m.group(2)]
    return f"{y:04d}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}"


def merge(parts):
    """Combine several guides for one restaurant (e.g. drinks and food) into one menu.
    The header shows the first guide; the restaurant counts as out of date when any guide is."""
    if len(parts) == 1:
        return parts[0]
    guide = dict(parts[0]["guide"])
    ends = [p["guide"].get("validUntil") for p in parts if p["guide"].get("validUntil")]
    guide["validUntil"] = min(ends) if ends else None
    seen, notices = set(), []
    for p in parts:
        for n in p.get("notices", []):
            if n["text"] not in seen:
                seen.add(n["text"])
                notices.append(n)
    return {
        "notices": notices,
        "source": " and ".join(p["source"] for p in parts),
        "guide": guide,
        "guides": [{**p["guide"], "source": p["source"]} for p in parts],
        "rule": " ".join(dict.fromkeys(p["rule"] for p in parts)),
        "sections": list(dict.fromkeys(s for p in parts for s in p["sections"])),
        "items": [i for p in parts for i in p["items"]],
        "avoid": [a for p in parts for a in p["avoid"]],
        "warnings": [w for p in parts for w in p.get("warnings", [])],
        "stats": {k: sum(p["stats"][k] for p in parts) for k in ("rows", "items", "avoid")},
    }


def build_one(folder):
    config = json.loads((folder / "restaurant.json").read_text(encoding="utf-8"))
    readers = config.get("readers") or ([config["reader"]] if config.get("reader") else [])
    if not readers:
        raise SystemExit(f"ERROR: {folder.name}/restaurant.json has no 'reader'")
    print(f"{config.get('name', folder.name)} ({', '.join(readers)})")
    parts = []
    for reader in readers:
        part = importlib.import_module(f"adapters.{reader}").build(folder, config)
        guide = part.setdefault("guide", {})
        guide["validUntil"] = guide.get("validUntil") or end_date(guide.get("runs"))
        parts.append(part)
    data = merge(parts)
    meta = {
        "id": folder.name,
        "name": config["name"],
        "type": config.get("type", ""),
        "covers": config.get("covers", ""),
        "optionLabel": config.get("optionLabel", "option"),
        "officialUrl": config.get("officialUrl", ""),
        "tips": config.get("tips", []),
        "area": config.get("area", ""),
        "language": config.get("language", "en"),
        "reviewed": config.get("reviewed"),
        "gaps": config.get("gaps", []),
    }
    print(f"  {data['stats']['rows']} rows -> {data['stats']['items']} with no gluten ingredients, {data['stats']['avoid']} to avoid")
    for w in data.get("warnings", []):
        print("  WARNING:", w)
    return meta, data


def main():
    ap = argparse.ArgumentParser(description="Build every restaurant's menu into site/data/.")
    ap.add_argument("ids", nargs="*", help="only these restaurants (for testing)")
    ap.add_argument("--previous", type=Path, default=ROOT / ".previous", help="folder with the live menus to compare with")
    args = ap.parse_args()
    only = set(args.ids)
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
        prev_path = args.previous / "r" / f"{meta['id']}.json"
        prev = json.loads(prev_path.read_text(encoding="utf-8")) if prev_path.exists() else None
        full["changes"] = changes.compare(prev, full)
        if prev and prev.get("source") == full["source"]:
            print("  same guide as the live menu" + (f"; keeping its changes {changes.summary(full['changes'])}" if full["changes"] else ""))
        else:
            print("  changes", changes.summary(full["changes"]))
        (out / "r" / f"{meta['id']}.json").write_text(json.dumps(full, indent=1, ensure_ascii=False), encoding="utf-8")
        index.append({**meta, "guide": data["guide"], "source": data["source"], "stats": data["stats"],
                      "file": f"data/r/{meta['id']}.json"})
    (out / "restaurants.json").write_text(json.dumps({"built": built, "restaurants": index}, indent=1, ensure_ascii=False),
                                          encoding="utf-8")
    print(f"Wrote {len(index)} restaurant(s) to {out}")


if __name__ == "__main__":
    main()
