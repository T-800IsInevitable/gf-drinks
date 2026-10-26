#!/usr/bin/env python3
"""
Sanity checks on the built data before it is published. Run after build.py.
Fails (and so blocks publishing) if anything looks wrong.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import CAPS_WORDS  # noqa: E402  (needs the path above)

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
        if not a.get("gluten") and not a.get("reason"):
            err(f"{rid}: avoid item {a.get('name')!r} has no reason")
    # the same words in another order ("Pistachio Iced Latte" / "Iced Pistachio Latte") is one drink split in two
    seen_words = {}
    for i in d["items"] + d["avoid"]:
        k = (i["section"], i.get("sub") or "", tuple(sorted(set(i["name"].lower().split()))))
        if k in seen_words and seen_words[k] != i["name"]:
            err(f"{rid}: {seen_words[k]!r} and {i['name']!r} look like one item split in two")
        seen_words.setdefault(k, i["name"])
    names = {(i["section"], i["name"]) for i in d["items"]}
    clash = names & {(a["section"], a["name"]) for a in d["avoid"]}
    if clash:
        err(f"{rid}: listed as both safe and to avoid: {sorted(clash)}")
    # the same name in different sections (Five Guys' sausage under Meat, and the Hot Dog in a bun under Hot Dogs):
    # a staff card for the safe one would order the other
    plain = {" ".join(i["name"].lower().split()) for i in d["items"]}
    same = sorted(n for n in plain & {" ".join(a["name"].lower().split()) for a in d["avoid"]}
                  if not any(" ".join(x.lower().split()) == n for _, x in clash))
    if same:
        err(f"{rid}: {same} named the same on the list and on the Avoid list. Rename one with \"rename\" in restaurant.json")
    for i in d["items"] + d["avoid"]:
        if i.get("role") not in (None, "part", "ingredient"):
            err(f"{rid}: {i['name']!r} has an unknown role {i['role']!r}")
        shout = [w for w in re.findall(r"\b[A-Z]{3,}\b", i["name"]) if w not in CAPS_WORDS]
        if shout:
            err(f"{rid}: {i['name']!r} has {shout} in capitals; the build tidies these (tools/build.py CAPS_WORDS lists the real ones)")
        if "decided" in i and not (isinstance(i["decided"], str) and i["decided"].strip()):
            err(f"{rid}: {i['name']!r} has an empty note on how it was decided")
    # the folded first screen shows the headline instead of the tips, so a restaurant with tips needs one
    if d.get("tips") and not d.get("headline"):
        err(f"{rid}: has tips but no \"headline\" in restaurant.json (the one tip shown once the tips are folded)")
    if len(d.get("headline") or "") > 60:
        err(f"{rid}: headline is {len(d['headline'])} characters; keep it under 60 so it fits on one line")
    for n in d.get("notices", []):
        if not n.get("text"):
            err(f"{rid}: a warning has no text")
    print(f"{rid}: {len(d['items'])} with no gluten ingredients, {len(d['avoid'])} to avoid, guide valid until {d['guide'].get('validUntil')}")

# cities.json: hand-checked places (not built from guides)
# who says it's gluten free: the place (all or part of its range), only the support groups' list, or a separate kitchen
CITY_CLAIMS = {"place-all", "list-all", "place-part", "separate"}
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
        if p.get("claim") not in CITY_CLAIMS:
            err(f"{where}: bad claim {p.get('claim')!r}")
        if p.get("claim") == "place-part" and not p.get("claimLabel"):
            err(f"{where}: a part claim needs a claimLabel saying which part")
        if p.get("claim") == "list-all" and p.get("says"):
            err(f"{where}: quotes the place, so its claim isn't the list's alone")
        if p.get("caution") and not p.get("flag"):
            err(f"{where}: a caution needs a short flag to show on the row")
        if not p.get("says") and not p.get("listed"):
            err(f"{where}: no words from the place or the list")
        if p.get("says") and p["says"].get("lang") != "en" and not p["says"].get("en"):
            err(f"{where}: quote isn't in English and has no translation")
        if p.get("status") not in ("confirmed", "unconfirmed") or (p.get("status") == "unconfirmed" and not p.get("statusNote")):
            err(f"{where}: status must be confirmed, or unconfirmed with a statusNote")
        # a place re-checked on its own carries its own date, never earlier than the city's
        if "checked" in p and (not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(p["checked"])) or p["checked"] < c.get("checked", "")):
            err(f"{where}: checked {p['checked']!r} isn't a date on or after the city's {c.get('checked')}")
        if not p.get("locations") or any(not l.get("address") or not l.get("area") for l in p["locations"]):
            err(f"{where}: every location needs an address and area")
        for l in p.get("locations", []):
            # coordinates for "Near me": must fall inside the city (catches swapped or mistyped numbers)
            box = c.get("bounds", {"lat": [52.3, 52.7], "lon": [13.0, 13.8]})
            if not (box["lat"][0] < l.get("lat", 0) < box["lat"][1] and box["lon"][0] < l.get("lon", 0) < box["lon"][1]):
                err(f"{where}: {l.get('address')} has no coordinates inside {cid}")
            h = l.get("hours")
            if h is not None and (len(h) != 7 or not all(x is None or isinstance(x, str) for x in h)):
                err(f"{where}: {l.get('address')} hours must be 7 entries, Monday to Sunday ('' = closed, null = not known)")
            if l.get("kitchenCloses") and not re.fullmatch(r"\d{2}:\d{2}", l["kitchenCloses"]):
                err(f"{where}: {l.get('address')} kitchenCloses {l['kitchenCloses']!r} isn't HH:MM")
            for day, x in zip("Mon Tue Wed Thu Fri Sat Sun".split(), h or []):
                x = x or ""
                # the app reads "HH:MM–HH:MM" (a note may follow); a time it can't read would show the place as closed
                m = re.match(r"(\d{1,2}):(\d{2})\s*[–-]\s*(\d{1,2}):(\d{2})", x)
                if x and not m:
                    err(f"{where}: {l.get('address')} {day} hours {x!r} aren't HH:MM–HH:MM")
                elif m and int(m[3]) * 60 + int(m[4]) <= int(m[1]) * 60 + int(m[2]):
                    err(f"{where}: {l.get('address')} {day} closes before it opens ({x!r}); past midnight isn't supported")
        for u in [p.get("url"), p.get("listPage")]:
            if u is not None and not str(u).startswith("https://"):
                err(f"{where}: link {u!r} isn't https")
    print(f"city {cid}: {len(c.get('places', []))} places, checked {c.get('checked')}")

# the release number: the app's APP_VERSION and the service worker's cache number must be the same (tools/check_release.py)
SITE = DATA.parent
app_v = re.search(r"const APP_VERSION = (\d+);", (SITE / "app.js").read_text(encoding="utf-8"))
sw_v = re.search(r'const CACHE = "gf-menus-v(\d+)"', (SITE / "sw.js").read_text(encoding="utf-8"))
if not app_v or not sw_v or app_v.group(1) != sw_v.group(1):
    err(f"release: APP_VERSION in site/app.js ({app_v and app_v.group(1)}) and CACHE in site/sw.js ({sw_v and sw_v.group(1)}) must match")

if errors:
    print("\nCHECK FAILED:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("All checks passed")
