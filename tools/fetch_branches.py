#!/usr/bin/env python3
"""
Fetch every UK branch of the app's chains from OpenStreetMap into site/data/branches.json, for the map page and
Near me. Run after build.py (it reads each restaurant's "osm" names from site/data/restaurants.json).

The phone used to ask OpenStreetMap's free query service (Overpass) each time it looked around, and that service is
often too busy to answer within a phone's patience. Asking once a week from the publish job instead means the phone
has the whole list to hand: the map and Near me work at once and offline, and the phone's position never leaves it.

The list that's live now is read first. A push publishes it again while it's under --reuse-days old, so only the
Monday run (and a run by hand) asks Overpass. Overpass answers a busy moment with 429 or 5xx: this waits and asks
again, trying a second public server too, inside a fixed time budget. A new list that has lost a fifth of the live
one, or every branch of a chain that had ten or more, is taken for a broken answer. In all of those cases, and on any
other error, the live list goes out again, so a bad week never empties the map. It never fails the publish: with no
list at all, the app says the branch list isn't on the phone yet.

The list is OpenStreetMap data (ODbL): the app credits "© OpenStreetMap contributors" wherever it's shown.

Usage:
  python tools/fetch_branches.py [--reuse-days N] [site-url]
  (site-url: where the live list is; default GF_LIVE_URL or the live site)
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"
OUT = DATA / "branches.json"
LIVE = "https://t-800isinevitable.github.io/gf-drinks/"
SERVERS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]
# Overpass asks every client to say who it is; a generic one (Python's own) is refused
AGENT = "gf-drinks-branch-list/1.0 (+https://github.com/T-800IsInevitable/gf-drinks)"
WAITS = [60, 120]  # seconds before the second and third rounds
BUSY = {429, 502, 503, 504}
BUDGET = 480  # seconds for every attempt together: well inside the publish step's 12-minute limit
KEEP_SHARE = 0.8  # a new list under this share of the live one is taken for a broken answer


def in_uk(lat, lon):
    """The same rough box as the app's inUK()."""
    return 49 < lat < 61 and -9 < lon < 2


def chains():
    """[(restaurant id, [OpenStreetMap names])] for every restaurant with "osm" names."""
    index = json.loads((DATA / "restaurants.json").read_text(encoding="utf-8"))
    return [(r["id"], r["osm"]) for r in index["restaurants"] if r.get("osm")]


def query(names):
    pat = "|".join(re.sub(r"([.*+?^${}()|\[\]\\\"])", r"\\\1", n) for n in names)
    return ('[out:json][timeout:300];area["ISO3166-1"="GB"][admin_level=2]->.uk;'
            '(nwr["brand"~"^(' + pat + ')$",i](area.uk);nwr["name"~"^(' + pat + ')$",i](area.uk););out center tags;')


def branches(elements, cs):
    """Overpass elements -> [chain number, lat, lon, street, opening_hours] for those that are one of the chains,
    matched as the app's chainOf() did: the brand or the name, whole and ignoring case."""
    lookup = {}
    for n, (_, names) in enumerate(cs):
        for name in names:
            lookup.setdefault(name.lower(), n)
    out, seen = [], set()
    for el in elements:
        if not isinstance(el, dict):
            continue
        tags = el.get("tags") if isinstance(el.get("tags"), dict) else {}
        n = next((lookup[x.lower()] for x in (tags.get("brand"), tags.get("name")) if isinstance(x, str) and x.lower() in lookup), None)
        centre = el.get("center") if isinstance(el.get("center"), dict) else {}
        lat, lon = el.get("lat", centre.get("lat")), el.get("lon", centre.get("lon"))
        if n is None or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or not in_uk(lat, lon):
            continue
        key = (el.get("type"), el.get("id"))
        if key in seen:
            continue
        seen.add(key)
        out.append([n, round(lat, 5), round(lon, 5), str(tags.get("addr:street") or "")[:60], str(tags.get("opening_hours") or "")[:200]])
    return sorted(out)


def ask(server, q, seconds):
    """One request with a hard deadline: urllib's timeout covers each read, not the whole answer, so the request runs in
    a thread that's abandoned (it's a daemon) once the time is up."""
    got = {}

    def run():
        try:
            req = urllib.request.Request(server, data=("data=" + urllib.parse.quote(q)).encode(), method="POST",
                                         headers={"User-Agent": AGENT, "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=seconds) as res:
                got["body"] = json.load(res)
        except BaseException as e:  # noqa: BLE001 (handed to the caller)
            got["error"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError(f"no complete answer in {seconds:.0f} s")
    if "error" in got:
        raise got["error"]
    body = got.get("body")
    if not isinstance(body, dict) or not isinstance(body.get("elements"), list):
        raise ValueError("not an Overpass answer")
    if body.get("remark") and "error" in str(body["remark"]).lower():  # Overpass reports its own time-outs inside a 200
        raise RuntimeError(str(body["remark"])[:200])
    return body["elements"]


def from_openstreetmap(cs):
    q = query([name for _, names in cs for name in names])
    end = time.time() + BUDGET
    for wait in [0] + WAITS:
        if time.time() + wait + 30 > end:
            print("  out of time for asking again")
            break
        if wait:
            print(f"  waiting {wait} s before asking again")
            time.sleep(wait)
        for server in SERVERS:
            left = end - time.time()
            if left < 30:
                break
            host = urllib.parse.urlparse(server).netloc
            t = time.time()
            try:
                elements = ask(server, q, min(360, left))
                print(f"  {host} answered in {time.time() - t:.0f} s with {len(elements)} elements")
                return elements
            except urllib.error.HTTPError as e:
                print(f"  {host}: HTTP {e.code}" + (" (busy)" if e.code in BUSY else ""))
            except Exception as e:  # a time-out, a dropped connection or a strange answer: try the next server
                print(f"  {host}: {type(e).__name__}: {str(e)[:120]}")
    return None


def valid(d):
    """The list's own form, as check.py checks it: chains, and rows of [chain number, lat, lon, street, hours] in the UK."""
    if not isinstance(d, dict) or not isinstance(d.get("chains"), list) or not isinstance(d.get("b"), list) or not d["b"]:
        return False
    n = len(d["chains"])
    return all(isinstance(x, list) and len(x) == 5 and isinstance(x[0], int) and 0 <= x[0] < n
               and all(isinstance(v, (int, float)) for v in x[1:3]) and in_uk(x[1], x[2])
               and all(isinstance(v, str) for v in x[3:]) for x in d["b"])


def from_live(base, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(base + "data/branches.json", headers={"Cache-Control": "no-cache", "User-Agent": AGENT})
            with urllib.request.urlopen(req, timeout=30) as res:
                d = json.load(res)
            return d if valid(d) else None
        except urllib.error.HTTPError as e:
            if e.code == 404:  # none published yet
                print("  no live list yet")
                return None
            print(f"  live list: HTTP {e.code}")
        except Exception as e:
            print(f"  live list: {type(e).__name__}: {str(e)[:120]}")
        if attempt + 1 < tries:
            time.sleep(10)
    return None


def age_days(d):
    try:
        return (date.today() - date.fromisoformat(d["fetched"])).days
    except Exception:
        return 10 ** 6


def broken(new, live):
    """Why a new list looks like a broken answer next to the live one, or "" if it doesn't."""
    if not live:
        return ""
    if len(new["b"]) < KEEP_SHARE * len(live["b"]):
        return f"{len(new['b'])} branches against {len(live['b'])} live"
    count = lambda d, rid: sum(1 for x in d["b"] if d["chains"][x[0]] == rid)  # noqa: E731
    lost = [rid for rid in live["chains"] if rid in new["chains"] and count(live, rid) >= 10 and count(new, rid) == 0]
    return f"every branch of {', '.join(lost)} gone" if lost else ""


def write(d):
    OUT.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def keep(live, why):
    if live:
        write(live)
        print(f"::warning::{why}; publishing the live branch list from {live.get('fetched')} again")
    else:
        print(f"::warning::{why}, and none is live yet: no branch list this time")


def run(base, reuse_days):
    cs = chains()
    print(f"Branch list: {len(cs)} chains")
    live = from_live(base)
    if live and reuse_days is not None and age_days(live) < reuse_days:
        write(live)
        print(f"  the live list from {live['fetched']} is under {reuse_days} days old: published again ({len(live['b'])} branches)")
        return
    elements = from_openstreetmap(cs)
    if elements is None:
        keep(live, "OpenStreetMap didn't answer")
        return
    new = {"fetched": date.today().isoformat(), "chains": [rid for rid, _ in cs], "b": branches(elements, cs)}
    if not valid(new):
        keep(live, "OpenStreetMap answered with no branches")
        return
    why = broken(new, live)
    if why:
        keep(live, f"The new list looks broken ({why})")
        return
    write(new)
    counts = {rid: sum(1 for x in new["b"] if x[0] == n) for n, (rid, _) in enumerate(cs)}
    print(f"  {len(new['b'])} branches ({OUT.stat().st_size // 1024} KB): " + ", ".join(f"{k} {v}" for k, v in counts.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse-days", type=int, default=None, help="publish the live list again while it's younger than this")
    ap.add_argument("site", nargs="?", default=os.environ.get("GF_LIVE_URL") or LIVE)
    args = ap.parse_args()
    base = args.site.rstrip("/") + "/"
    try:
        run(base, args.reuse_days)
    except Exception:  # never fail the publish over the branch list
        traceback.print_exc()
        try:
            keep(from_live(base, tries=1), "The branch list fetch went wrong")
        except Exception:
            print("::warning::The branch list fetch went wrong and the live list couldn't be read: no branch list this time")


if __name__ == "__main__":
    main()
