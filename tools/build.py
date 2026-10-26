#!/usr/bin/env python3
"""
Build the app's data for every restaurant in restaurants/.

Each restaurant is a folder with a restaurant.json naming the reader that
understands its allergen information (see tools/adapters/). A restaurant with
more than one guide (e.g. drinks and food) lists several: "readers": [...].
Folders starting with "_" or "." are skipped (use them for templates and drafts).

Writes:
  site/data/restaurants.json   the build time, and each restaurant's name, file, guide, stats, logo and fingerprint
  site/data/r/<id>.json        one restaurant's full menu and settings (unchanged byte for byte between builds
                               from the same guide and settings)

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
import hashlib
import importlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import changes  # noqa: E402  (needs the path above)
from adapters.common import MONTHS, valid_until  # noqa: E402

# what the index (site/data/restaurants.json) says about each restaurant: enough to list it and find its file.
# The rest (tips, gaps, settings) is in the restaurant's own file, which the app always loads.
INDEX_KEYS = ("id", "name", "file", "source", "guide", "stats", "logo", "officialUrl", "osm", "hash")
# a guide file named in a reader's "source" ("Knoops allergen guide, March 2024 (Knoops_allergen_guide_March_2024.pdf, ...)")
PDF_NAME = re.compile(r"[\w.-]+\.pdf", re.I)


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
    for n_part, p in enumerate(parts):
        for n in p.get("notices", []):
            if n["text"] not in seen:
                seen.add(n["text"])
                notices.append(n)
        for i in p["items"] + p["avoid"]:  # which guide a row's page numbers refer to ("guides" below)
            i["src"] = n_part
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


ROLES = {"part", "ingredient"}
# words that really are written in capitals (brands and abbreviations); any other all-capitals word in a name is the guide's styling
CAPS_WORDS = {"BBQ", "BLT", "IPA", "THIS", "UK", "USA", "PB", "KFC"}


def tidy_name(name):
    """'Americano (BLACK)' -> 'Americano (Black)'. Only item names: a quoted warning stays exactly as the guide wrote it.
    Case alone changes, so the app still finds a saved favourite and the changes list still matches it (both ignore case)."""
    return re.sub(r"\b[A-Z]{3,}\b", lambda m: m.group(0) if m.group(0) in CAPS_WORDS else m.group(0).capitalize(), name)


def apply_config(data, config, rid):
    """Corrections from restaurant.json, applied to the readers' output:
    "rename": {"Section|Name": "New name"} for a row whose guide name could be taken for another dish
      (Five Guys lists its hot dog sausage as "Hot Dog");
    "roles": {"Section" or "Section|Name": "part" | "ingredient"} for rows that aren't things to order as they
      are: parts of dishes (burger toppings) and ingredients listed on their own (milks). They get no staff card.
    A setting that matches nothing stops the build: the guide has changed, so it needs looking at again."""
    rows = data["items"] + data["avoid"]
    for key, new in (config.get("rename") or {}).items():
        hits = [i for i in rows if f"{i['section']}|{i['name']}" == key]
        if not hits:
            raise SystemExit(f"ERROR: {rid}/restaurant.json: rename {key!r} matches nothing in the guide. Check the guide, then update it.")
        for i in hits:
            i["name"] = new
    for key, role in (config.get("roles") or {}).items():
        if role not in ROLES:
            raise SystemExit(f"ERROR: {rid}/restaurant.json: role {role!r} for {key!r} isn't one of {sorted(ROLES)}.")
        hits = [i for i in rows if key in (i["section"], f"{i['section']}|{i['name']}")]
        if not hits:
            raise SystemExit(f"ERROR: {rid}/restaurant.json: roles {key!r} matches nothing in the guide. Check the guide, then update it.")
        for i in hits:
            i["role"] = role
    for i in rows:  # after the settings above, which are matched against the guide's own spelling
        i["name"] = tidy_name(i["name"])
    # the counts shown in the app are of things to order, so an ingredient listed on its own isn't one
    ingredients = sum(1 for i in data["items"] if i.get("role") == "ingredient")
    if ingredients:
        data["stats"]["items"] -= ingredients
        data["stats"]["ingredients"] = ingredients


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
        # when to look again: the guide's own end date, else the end of the season it names, else its version date
        # plus the restaurant's recheckDays
        guide["validUntil"] = guide.get("validUntil") or end_date(guide.get("runs")) or valid_until(guide.get("version"), config)
        parts.append(part)
    data = merge(parts)
    apply_config(data, config, folder.name)
    # "order": the order builder's words and which sections come first (parts of dishes). A section it names that
    # the guide no longer has stops the build, like a role that matches nothing.
    order = config.get("order")
    for s in (order or {}).get("first", []):
        if s not in data["sections"]:
            raise SystemExit(f"ERROR: {folder.name}/restaurant.json: order.first names {s!r}, which isn't a section in the guide. Check the guide, then update it.")
    # the chain's own mark for the chooser (tools/fetch_logos.py), copied in with the data
    logo = folder / "logo.png"
    if logo.exists():
        (ROOT / "site" / "data" / "logos").mkdir(parents=True, exist_ok=True)
        (ROOT / "site" / "data" / "logos" / f"{folder.name}.png").write_bytes(logo.read_bytes())
    # the guides themselves go out with the site, so an item's "Guide page 7" can open the guide at that page
    # (guideFiles: the source name each reader gave -> the published path)
    guide_files = {}
    for source in [g["source"] for g in data.get("guides", [])] or [data["source"]]:
        for name in PDF_NAME.findall(source):
            pdf = folder / "guides" / name
            if pdf.exists():
                (ROOT / "site" / "guides" / folder.name).mkdir(parents=True, exist_ok=True)
                (ROOT / "site" / "guides" / folder.name / name).write_bytes(pdf.read_bytes())
                guide_files[source] = f"guides/{folder.name}/{name}"
    meta = {
        "id": folder.name,
        "name": config["name"],
        "type": config.get("type", ""),
        "covers": config.get("covers", ""),
        "optionLabel": config.get("optionLabel", "option"),
        "officialUrl": config.get("officialUrl", ""),
        "tips": config.get("tips", []),
        "headline": config.get("headline", ""),  # the one tip that matters most, shown on the page once its full tips are folded
        "area": config.get("area", ""),
        "language": config.get("language", "en"),
        "reviewed": config.get("reviewed"),
        "gaps": config.get("gaps", []),
        "latestGuide": config.get("latestGuide"),  # when we last looked for a newer guide, and what we found
        "logo": f"data/logos/{folder.name}.png" if logo.exists() else "",
        "order": order,
        "osm": config.get("osm", []),  # what OpenStreetMap calls this chain's branches, for "Near me"
        "guideFiles": guide_files,
    }
    print(f"  {data['stats']['rows']} rows -> {data['stats']['items']} with no gluten ingredients, {data['stats']['avoid']} to avoid"
          + (f", {data['stats']['ingredients']} ingredients listed on their own" if data["stats"].get("ingredients") else ""))
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
        # the build time goes in the index only: a menu file that hasn't changed stays byte for byte the same, so a
        # phone's "has it changed?" check gets "not modified" instead of downloading every menu after every release
        full = {**meta, **data}
        prev_path = args.previous / "r" / f"{meta['id']}.json"
        prev = json.loads(prev_path.read_text(encoding="utf-8")) if prev_path.exists() else None
        full["changes"] = changes.compare(prev, full)
        if prev and prev.get("source") == full["source"]:
            print("  same guide as the live menu" + (f"; keeping its changes {changes.summary(full['changes'])}" if full["changes"] else ""))
        else:
            print("  changes", changes.summary(full["changes"]))
        # a fingerprint of everything the app shows, so it can tell a changed menu from an unchanged one by comparing
        # two short strings rather than the whole file
        full["hash"] = hashlib.sha256(json.dumps(full, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
        (out / "r" / f"{meta['id']}.json").write_text(json.dumps(full, indent=1, ensure_ascii=False), encoding="utf-8")
        entry = {**full, "file": f"data/r/{meta['id']}.json"}
        index.append({k: entry[k] for k in INDEX_KEYS if k in entry})
    (out / "restaurants.json").write_text(json.dumps({"built": built, "restaurants": index}, indent=1, ensure_ascii=False),
                                          encoding="utf-8")
    print(f"Wrote {len(index)} restaurant(s) to {out}")


if __name__ == "__main__":
    main()
