#!/usr/bin/env python3
"""
Sanity checks on the built data before it is published. Run after build.py.
Fails (and so blocks publishing) if anything looks wrong.
"""
import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "site" / "data"
ORDERS = {"asis", "any", "except", "swap", "modify"}
errors = []


def err(msg):
    errors.append(msg)


index = json.loads((DATA / "restaurants.json").read_text(encoding="utf-8"))
ids = [r["id"] for r in index["restaurants"]]
if not ids:
    err("no restaurants in restaurants.json")
if len(ids) != len(set(ids)):
    err("duplicate restaurant ids")

for r in index["restaurants"]:
    rid = r["id"]
    path = DATA.parent / r["file"]
    if not path.exists():
        err(f"{rid}: {r['file']} missing")
        continue
    d = json.loads(path.read_text(encoding="utf-8"))
    if not d["items"]:
        err(f"{rid}: no items without gluten ingredients")
    for i in d["items"]:
        where = f"{rid}: {i.get('name')!r}"
        if not i.get("name") or not i.get("section"):
            err(f"{where}: missing name or section")
        if i.get("order") not in ORDERS:
            err(f"{where}: bad order {i.get('order')!r}")
        if i.get("order") in ("any", "except", "swap") and not i.get("ok"):
            err(f"{where}: no options without gluten listed")
        if i.get("order") == "except" and not i.get("not"):
            err(f"{where}: 'except' with nothing excluded")
        if i.get("order") == "modify" and not i.get("note"):
            err(f"{where}: 'modify' without a note")
    for a in d["avoid"]:
        if not a.get("gluten"):
            err(f"{rid}: avoid item {a.get('name')!r} has no reason")
    names = {(i["section"], i["name"]) for i in d["items"]}
    clash = names & {(a["section"], a["name"]) for a in d["avoid"]}
    if clash:
        err(f"{rid}: listed as both safe and to avoid: {sorted(clash)}")
    for n in d.get("notices", []):
        if not n.get("text"):
            err(f"{rid}: a warning has no text")
    print(f"{rid}: {len(d['items'])} with no gluten ingredients, {len(d['avoid'])} to avoid, guide valid until {d['guide'].get('validUntil')}")

# cities.json: hand-checked places (not built from guides)
CITY_KINDS = {"dedicated", "options"}
cities = json.loads((DATA.parent / "cities.json").read_text(encoding="utf-8"))
phrases = json.loads((DATA.parent / "phrases.json").read_text(encoding="utf-8"))
for cid, c in cities.items():
    for key in ("name", "language", "checked", "list", "tips", "sections", "places"):
        if not c.get(key):
            err(f"city {cid}: missing {key}")
    if c.get("language") not in phrases:
        err(f"city {cid}: no coeliac card for language {c.get('language')!r}")
    for p in c.get("places", []):
        where = f"city {cid}: {p.get('name')!r}"
        if p.get("section") not in c.get("sections", []):
            err(f"{where}: section {p.get('section')!r} isn't in sections")
        if p.get("kind") not in CITY_KINDS:
            err(f"{where}: bad kind {p.get('kind')!r}")
        if not p.get("says") and not p.get("listed"):
            err(f"{where}: no words from the place or the list")
        if p.get("says") and p["says"].get("lang") != "en" and not p["says"].get("en"):
            err(f"{where}: quote isn't in English and has no translation")
        if p.get("status") not in ("confirmed", "unconfirmed") or (p.get("status") == "unconfirmed" and not p.get("statusNote")):
            err(f"{where}: status must be confirmed, or unconfirmed with a statusNote")
        if not p.get("locations") or any(not l.get("address") or not l.get("area") for l in p["locations"]):
            err(f"{where}: every location needs an address and area")
        for u in [p.get("url"), p.get("listPage")]:
            if u is not None and not str(u).startswith("https://"):
                err(f"{where}: link {u!r} isn't https")
    print(f"city {cid}: {len(c.get('places', []))} places, checked {c.get('checked')}")

if errors:
    print("\nCHECK FAILED:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("All checks passed")
