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
        err(f"{rid}: no gluten free items")
    for i in d["items"]:
        where = f"{rid}: {i.get('name')!r}"
        if not i.get("name") or not i.get("section"):
            err(f"{where}: missing name or section")
        if i.get("order") not in ORDERS:
            err(f"{where}: bad order {i.get('order')!r}")
        if i.get("order") in ("any", "except", "swap") and not i.get("ok"):
            err(f"{where}: no gluten free options listed")
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
        err(f"{rid}: listed as both gluten free and to avoid: {sorted(clash)}")
    print(f"{rid}: {len(d['items'])} gluten free, {len(d['avoid'])} to avoid, guide valid until {d['guide'].get('validUntil')}")

if errors:
    print("\nCHECK FAILED:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("All checks passed")
