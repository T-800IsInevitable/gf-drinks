#!/usr/bin/env python3
"""
Sanity checks on the built data before it is published. Run after build.py.
Fails (and so blocks publishing) if anything looks wrong.

Usage:
  python tools/check.py
"""
import json
import re
import sys
import zoneinfo
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import CAPS_WORDS  # noqa: E402  (needs the path above)
from adapters.common import CEREAL, cereal_code  # noqa: E402
from check_release import app_number, cache_number  # noqa: E402

SITE = Path(__file__).resolve().parent.parent / "site"
DATA = SITE / "data"
ORDERS = {"asis", "any", "except", "swap", "modify"}
# cities.json: who says a place is gluten free: the place (all or part of its range), only the support groups' list,
# or a separate kitchen
CITY_CLAIMS = {"place-all", "list-all", "place-part", "separate"}
# opening hours as the app reads them (site/app.js, span()): "HH:MM–HH:MM", a note may follow
HOURS = re.compile(r"(\d{1,2}):(\d{2})\s*[–-]\s*(\d{1,2}):(\d{2})")
# the keys that hold a web address, anywhere in the data (plus any key ending in Url)
URL_KEYS = {"url", "officialUrl", "listPage", "logoUrl"}
SAFE_URL = re.compile(r"https://\S+")
UK_BOX = {"lat": (49, 61), "lon": (-9, 2)}  # the same box check_branches holds the chains' branches to
CITY_SPAN = 1  # degrees: a city's bounds are never wider or taller than this (London, the widest, is 0.86)


def real_date(v):
    """True for a real calendar date written YYYY-MM-DD."""
    if not (isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)):
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


def clock(h, m, closing=False):
    """True for a time of day; 24:00 only as a closing time."""
    h, m = int(h), int(m)
    return (h < 24 and m < 60) or (closing and h == 24 and m == 0)


def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def zone_known(tz):
    """True or False for a time zone name; None when this computer has no time zone list to ask (a Windows Python
    without the tzdata package), so the test is skipped there instead of failing every city."""
    try:
        zoneinfo.ZoneInfo("Europe/London")
    except zoneinfo.ZoneInfoNotFoundError:
        return None
    try:
        zoneinfo.ZoneInfo(tz)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, TypeError, OSError):
        return False
    return True


def check_bounds(cid, c, err):
    """A city's hand-typed bounds, which every place's coordinates are held to: {"lat": [low, high], "lon": [low,
    high]}, a box no bigger than a city, and inside the UK for a UK city. Returns the box, or None if it's no good."""
    box = c.get("bounds")
    ok = isinstance(box, dict) and all(isinstance(box.get(k), list) and len(box[k]) == 2 and all(number(v) for v in box[k])
                                       for k in ("lat", "lon"))
    if not ok:
        if box:  # a missing one is already reported
            err(f"city {cid}: bounds must be {{\"lat\": [low, high], \"lon\": [low, high]}}, in numbers")
        return None
    good = True
    for k in ("lat", "lon"):
        low, high = box[k]
        if not low < high:
            err(f"city {cid}: bounds {k} {box[k]} must run from low to high")
            good = False
        elif high - low > CITY_SPAN:
            err(f"city {cid}: bounds {k} {box[k]} span more than {CITY_SPAN} degree, too wide for one city")
            good = False
        elif c.get("group") == "uk" and not (UK_BOX[k][0] < low and high < UK_BOX[k][1]):
            err(f"city {cid}: bounds {k} {box[k]} aren't in the UK")
            good = False
    return box if good else None


def check_urls(obj, where, err, path=""):
    """Every web address in the data must be https: the app puts them straight into links (site/app.js safeUrl()
    drops anything else, but a bad one should never get as far as a publish)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in URL_KEYS or k.endswith("Url"):
                if v and not (isinstance(v, str) and SAFE_URL.fullmatch(v)):
                    err(f"{where}: {path}{k} {v!r} isn't an https address")
            else:
                check_urls(v, where, err, f"{path}{k}.")
    elif isinstance(obj, list):
        for n, v in enumerate(obj):
            check_urls(v, where, err, f"{path}{n}.")


def check_restaurant(r, err):
    rid = r["id"]
    path = SITE / r["file"]
    if not path.exists():
        err(f"{rid}: {r['file']} missing")
        return
    d = json.loads(path.read_text(encoding="utf-8"))
    if not d["items"]:
        err(f"{rid}: no items without gluten ingredients")
    # every guide so far has rows to avoid, so an empty Avoid list is a reader that has stopped seeing the gluten marks
    if not d["avoid"]:
        err(f"{rid}: nothing on the Avoid list")
    # a guide with no end date would never show as out of date and never get a reminder
    for n, g in enumerate([d["guide"]] + list(d.get("guides") or [])):
        if not real_date(g.get("validUntil")):
            err(f"{rid}: {'the guide' if n == 0 else f'guide {n}'} has no end date (validUntil {g.get('validUntil')!r}); "
                "the reader couldn't read its date")
    # the counts shown in the app must be the lists' own (an ingredient listed on its own is counted apart)
    stats = d.get("stats")
    if stats is not None and (stats.get("items", 0) + stats.get("ingredients", 0) != len(d["items"])
                              or stats.get("avoid") != len(d["avoid"])):
        err(f"{rid}: stats {stats} don't match the lists ({len(d['items'])} listed, {len(d['avoid'])} to avoid)")
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
        # a row a reader marked as gluten and then filed in the wrong list: what only an Avoid row carries
        if i.get("gluten") or i.get("tag") or str(i.get("reason") or "").startswith("Contains"):
            err(f"{where}: listed with no gluten ingredients, but carries an Avoid row's gluten, tag or reason")
        both = sorted(set(i.get("ok") or []) & set(i.get("not") or []))
        if both:
            err(f"{where}: {both} are among both its fine options and the ones to avoid")
        if i.get("order") == "swap" and i.get("standard") in (i.get("ok") or []):
            err(f"{where}: a swap whose standard option {i.get('standard')!r} is one of its fine options")
        # the last line of defence, whatever the reader: an item on the list, or an option it says is fine, that names a
        # gluten cereal (oats included, CLAUDE.md) is wrong, so a hand-kept menu.csv or a reader's slip can't publish one.
        # The one exception (CLAUDE.md) is a drink named for the oat drink it normally comes with, which the guide lists
        # with other milks (an Oat Shaken Espresso, asked for with another milk): a swap, with oat as its standard
        # option and on its "not" list. No other cereal has one, because no other cereal is an option to swap out.
        nots = {cereal_code(m) for x in (i.get("not") or []) for m in CEREAL.findall(str(x))}
        standard = {cereal_code(m) for m in CEREAL.findall(str(i.get("standard") or ""))}
        swapped = {"OAT"} if i.get("order") == "swap" and "OAT" in nots and "OAT" in standard else set()
        bad = sorted({cereal_code(m) for m in CEREAL.findall(i.get("name") or "")} - swapped)
        bad += sorted({cereal_code(m) for x in (i.get("ok") or []) for m in CEREAL.findall(str(x))} - set(bad))
        if bad:
            err(f"{where}: names a gluten cereal ({', '.join(bad)}) in its name or its fine options, but is listed with "
                "no gluten ingredients; put it on the Avoid list")
    for a in d["avoid"]:
        if not a.get("gluten") and not a.get("reason"):
            err(f"{rid}: avoid item {a.get('name')!r} has no reason")
        if a.get("order"):
            err(f"{rid}: avoid item {a.get('name')!r} carries a way to order it ({a['order']!r})")
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
    # the order builder's words (restaurant.json "order"); build.py already stops on a section it names that has gone
    cfg = d.get("order")
    if cfg is not None:
        if not isinstance(cfg, dict):
            err(f"{rid}: \"order\" in restaurant.json must be an object")
        else:
            for k in ("intro", "cardLine"):
                if k in cfg and not (isinstance(cfg[k], str) and cfg[k].strip()):
                    err(f"{rid}: order.{k} must be a sentence")
            if len(cfg.get("intro") or "") > 320:
                err(f"{rid}: order.intro is {len(cfg['intro'])} characters; keep it under 320")
            if cfg.get("cardLine") and not cfg["cardLine"].rstrip().endswith("please."):
                err(f"{rid}: order.cardLine is what the staff card asks for, so end it with 'please.'")
    if d.get("logo") and not (SITE / d["logo"]).exists():
        err(f"{rid}: logo {d['logo']} wasn't written")
    # what OpenStreetMap calls the chain (Near me): plain names only, because they go into a query pattern as they are
    for name in d.get("osm") or []:
        if not (isinstance(name, str) and re.fullmatch(r"[\w' ]+", name)):
            err(f"{rid}: osm name {name!r} should be letters, digits, spaces and apostrophes only")
    if not d.get("hash") or r.get("hash") != d["hash"]:
        err(f"{rid}: the index and the menu file don't carry the same fingerprint")
    if "built" in d:
        err(f"{rid}: the menu file carries a build time, which would make every release re-download it")
    check_urls(r, rid, err)
    check_urls(d, rid, err)
    print(f"{rid}: {len(d['items'])} with no gluten ingredients, {len(d['avoid'])} to avoid, guide valid until {d['guide'].get('validUntil')}")


def check_branches(d, ids, err):
    """data/branches.json (tools/fetch_branches.py): [chain number, lat, lon, street, opening_hours] per branch, every
    one in the UK. A chain the app no longer has is only skipped by the app, so it's reported, not failed."""
    chains, rows = d.get("chains"), d.get("b")
    if not isinstance(chains, list) or not isinstance(rows, list) or not rows:
        err("branches: needs a list of chains and at least one branch")
        return
    gone = [c for c in chains if c not in ids]
    if gone:
        print(f"branches: {gone} aren't in the app any more; the app skips their branches")
    for x in rows:
        ok = (isinstance(x, list) and len(x) == 5 and isinstance(x[0], int) and 0 <= x[0] < len(chains)
              and all(isinstance(v, (int, float)) for v in x[1:3]) and all(isinstance(v, str) for v in x[3:]))
        if not ok or not (49 < x[1] < 61 and -9 < x[2] < 2):
            err(f"branches: {x!r} isn't a UK branch in the expected form")
            return
    print(f"branches: {len(rows)} from OpenStreetMap, fetched {d.get('fetched')}")


def check_whatsnew(notes, app_v, err):
    """site/whatsnew.json: the notes for each announced release (What's new, and the "Update N is live!" notification
    that tools/push.py sends when the release it names goes live). Newest first, never ahead of the app."""
    if not isinstance(notes, list):
        err("whatsnew.json: must be a list")
        return
    seen = []
    for n in notes:
        v = n.get("version") if isinstance(n, dict) else None
        if not isinstance(v, int) or v > app_v or v in seen:
            err(f"whatsnew.json: version {v!r} must be a release number, once, no later than APP_VERSION ({app_v})")
            continue
        seen.append(v)
        if not (isinstance(n.get("title"), str) and n["title"].strip()) or len(n["title"]) > 90:
            err(f"whatsnew.json {v}: needs a title of up to 90 characters (it ends the notification's sentence)")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(n.get("date", ""))):
            err(f"whatsnew.json {v}: date must be YYYY-MM-DD")
        if not n.get("items") or not all(isinstance(i, str) and i.strip() for i in n["items"]):
            err(f"whatsnew.json {v}: needs a list of items")
    if seen != sorted(seen, reverse=True):
        err("whatsnew.json: newest release first")


def check_city(cid, c, phrases, err):
    no_places = c.get("places") == [] and isinstance(c.get("none"), str) and c["none"].strip()  # see below: a city that says it has none
    for key in ("name", "language", "checked", "list", "tips", "sections", "country", "bounds", "timeZone"):
        if not c.get(key) and not (key == "sections" and no_places and c.get(key) == []):  # no places, so no sections
            err(f"city {cid}: missing {key}")
    # a city can have no places yet, but only when it says so: "none" is the sentence shown where they would be
    if not c.get("places") and not (c.get("places") == [] and isinstance(c.get("none"), str) and c["none"].strip()):
        err(f"city {cid}: missing places (an empty list needs \"none\", a sentence to show in their place)")
    # the dates drive "checked N days ago", the stale banner and the reminders: real, and not in the future
    # (a day's grace, because the check runs on UTC and the date was typed somewhere else)
    latest = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    if c.get("checked") and (not real_date(c["checked"]) or c["checked"] > latest):
        err(f"city {cid}: checked {c['checked']!r} must be a real date (YYYY-MM-DD), not after today")
    if "recheckDays" in c and not (isinstance(c["recheckDays"], int) and not isinstance(c["recheckDays"], bool)
                                   and 0 < c["recheckDays"] <= 180):
        err(f"city {cid}: recheckDays {c['recheckDays']!r} must be a whole number of days, 1 to 180")
    # "uk": listed under UK cities, and needs no coeliac card in another language; any other city is International
    if c.get("group") not in (None, "uk"):
        err(f"city {cid}: group {c.get('group')!r} must be 'uk' or left out")
    if c.get("group") != "uk" and c.get("language") not in phrases:
        err(f"city {cid}: no coeliac card for language {c.get('language')!r}")
    if c.get("group") == "uk" and c.get("timeZone") != "Europe/London":
        err(f"city {cid}: a UK city's timeZone must be Europe/London")
    elif c.get("timeZone"):  # the app asks the phone for the time there; a name it doesn't know stops the page
        known = zone_known(c["timeZone"])
        if known is None:
            print(f"city {cid}: no time zone list on this computer, so timeZone {c['timeZone']!r} wasn't checked")
        elif not known:
            err(f"city {cid}: timeZone {c['timeZone']!r} isn't a time zone name (such as Europe/Berlin)")
    box = check_bounds(cid, c, err)
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
        if p.get("says") and not (isinstance(p["says"], dict) and isinstance(p["says"].get("text"), str) and p["says"]["text"].strip()):
            err(f"{where}: says has no text, so there are no words from the place to quote")
            continue
        if p.get("listedBy") and not p.get("listed"):
            err(f"{where}: listedBy names who listed it, so it needs their words in listed")
        if c.get("group") == "uk" and p.get("listed") and not p.get("listedBy"):  # else the app credits a support group
            err(f"{where}: a UK city's listed words need listedBy, saying whose they are")
        if p.get("says") and p["says"].get("lang") != "en" and not p["says"].get("en"):
            err(f"{where}: quote isn't in English and has no translation")
        if p.get("status") not in ("confirmed", "unconfirmed") or (p.get("status") == "unconfirmed" and not p.get("statusNote")):
            err(f"{where}: status must be confirmed, or unconfirmed with a statusNote")
        # a place re-checked on its own carries its own date, never earlier than the city's
        if "checked" in p and (not real_date(p["checked"]) or p["checked"] < str(c.get("checked") or "")):
            err(f"{where}: checked {p['checked']!r} isn't a date on or after the city's {c.get('checked')}")
        elif "checked" in p and p["checked"] > latest:
            err(f"{where}: checked {p['checked']!r} is after today")
        if not p.get("locations") or any(not l.get("address") or not l.get("area") for l in p["locations"]):
            err(f"{where}: every location needs an address and area")
        for l in p.get("locations", []):
            # coordinates for "Near me": must fall inside the city's own bounds (catches swapped or mistyped numbers)
            lat, lon = l.get("lat", 0), l.get("lon", 0)
            if not (number(lat) and number(lon)):
                err(f"{where}: {l.get('address')} lat and lon must be numbers, not {lat!r} and {lon!r}")
            elif box and not (box["lat"][0] < lat < box["lat"][1] and box["lon"][0] < lon < box["lon"][1]):
                err(f"{where}: {l.get('address')} has no coordinates inside {cid}")
            h = l.get("hours")
            if h is not None and (len(h) != 7 or not all(x is None or isinstance(x, str) for x in h)):
                err(f"{where}: {l.get('address')} hours must be 7 entries, Monday to Sunday ('' = closed, null = not known)")
            if l.get("kitchenCloses") and not (isinstance(l["kitchenCloses"], str) and re.fullmatch(r"\d{2}:\d{2}", l["kitchenCloses"])
                                               and clock(*l["kitchenCloses"].split(":"), closing=True)):
                err(f"{where}: {l.get('address')} kitchenCloses {l['kitchenCloses']!r} isn't a time of day, HH:MM")
            for day, x in zip("Mon Tue Wed Thu Fri Sat Sun".split(), h or []):
                x = x or ""
                if x and not HOURS.match(x):  # a time the app can't read would show the place as closed
                    err(f"{where}: {l.get('address')} {day} hours {x!r} aren't HH:MM–HH:MM")
                    continue
                # a day with a break lists its ranges in order ("12:00–14:30, 17:00–21:30"); the app reads each one,
                # so a time after them that isn't a whole range ("12:00–14:30, 17:00") would be dropped without a word
                lead = re.match(rf"{HOURS.pattern}(?:,\s*{HOURS.pattern})*", x)
                if lead and re.search(r"\d{1,2}:\d{2}", x[lead.end():]):
                    err(f"{where}: {l.get('address')} {day} hours {x!r} have a time the app can't read after the ranges")
                last = -1
                for m in HOURS.finditer(x):
                    a, b = int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])
                    if not (clock(m[1], m[2]) and clock(m[3], m[4], closing=True)):
                        err(f"{where}: {l.get('address')} {day} hours {x!r} have a time that isn't a time of day")
                    elif b <= a:
                        err(f"{where}: {l.get('address')} {day} closes before it opens ({x!r}); past midnight isn't supported")
                    elif a <= last:
                        err(f"{where}: {l.get('address')} {day} ranges overlap or are out of order ({x!r})")
                    last = b
    check_urls(c, f"city {cid}", err)  # the list's own address, each place's website and list entry
    print(f"city {cid}: {len(c.get('places', []))} places, checked {c.get('checked')}")


def main():
    errors = []
    err = errors.append
    index = json.loads((DATA / "restaurants.json").read_text(encoding="utf-8"))
    ids = [r["id"] for r in index["restaurants"]]
    if not ids:
        err("no restaurants in restaurants.json")
    if len(ids) != len(set(ids)):
        err("duplicate restaurant ids")
    for r in index["restaurants"]:
        check_restaurant(r, err)
    if (DATA / "branches.json").exists():  # written by the publish job only (tools/fetch_branches.py)
        check_branches(json.loads((DATA / "branches.json").read_text(encoding="utf-8")), set(ids), err)
    cities = json.loads((SITE / "cities.json").read_text(encoding="utf-8"))
    phrases = json.loads((SITE / "phrases.json").read_text(encoding="utf-8"))
    for cid, c in cities.items():
        check_city(cid, c, phrases, err)
    # the release number: the app's APP_VERSION and the service worker's cache number must be the same
    app_v = app_number((SITE / "app.js").read_text(encoding="utf-8"))
    sw_v = cache_number((SITE / "sw.js").read_text(encoding="utf-8"))
    if app_v != sw_v:
        err(f"release: APP_VERSION in site/app.js ({app_v}) and CACHE in site/sw.js ({sw_v}) must match")
    if (SITE / "whatsnew.json").exists():
        check_whatsnew(json.loads((SITE / "whatsnew.json").read_text(encoding="utf-8")), app_v, err)
    if errors:
        print("\nCHECK FAILED:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("All checks passed")


if __name__ == "__main__":
    main()
