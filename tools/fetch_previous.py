#!/usr/bin/env python3
"""
Download the menus that are live now into .previous/, so build.py can say
what changed when a restaurant's guide is updated (see tools/changes.py).

A 404 for the index means the site is up with nothing published yet (the
very first deploy): that's not an error, the build simply has nothing to
compare with. Any other failure (no connection, a timeout, the site
returning an error) stops the build instead of publishing silently with
every restaurant's change marks dropped: see assessment finding X4.

Usage:
  python tools/fetch_previous.py [site-url]
  (default: the GF_LIVE_URL environment variable, or the live GitHub Pages site)
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_release import app_number  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".previous"
LIVE = "https://t-800isinevitable.github.io/gf-drinks/"


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Cache-Control": "no-cache"}), timeout=30) as res:
        return res.read()


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GF_LIVE_URL") or LIVE).rstrip("/") + "/"
    try:
        index = json.loads(get(base + "data/restaurants.json"))
    except Exception as e:
        if isinstance(e, urllib.error.HTTPError) and e.code == 404:  # the site is up; first deploy, nothing to compare with yet
            print(f"No live menus to compare with (first deploy: {e}).")
            return
        raise SystemExit(f"ERROR: couldn't download the live menus to compare with ({e}). Not publishing: "
                          "a failed download must not wipe every restaurant's change marks. Retry, or pass "
                          "a different --previous DIR to tools/build.py to publish anyway.")
    (OUT / "r").mkdir(parents=True, exist_ok=True)
    (OUT / "restaurants.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    # the live release number, so tools/push.py can announce a new one; not worth stopping the build for
    try:
        (OUT / "app-version").write_text(str(app_number(get(base + "app.js").decode("utf-8"))), encoding="utf-8")
    except BaseException as e:  # app_number stops with SystemExit when it can't find the number
        print(f"  live release number unknown ({e}); a new release won't be announced this time")
    # the live cities, so tools/push.py can announce a new one; as for the release, not worth stopping the build for
    try:
        live_cities = get(base + "cities.json")
        if not isinstance(json.loads(live_cities), dict):  # an error page or a damaged copy is no list to compare with
            raise ValueError("not a list of cities")
        (OUT / "cities.json").write_bytes(live_cities)
    except Exception as e:
        print(f"  live cities unknown ({e}); a new city won't be announced this time")
    for r in index.get("restaurants", []):
        try:
            (OUT / "r" / f"{r['id']}.json").write_bytes(get(base + r["file"]))
            print(f"  live {r['id']}: {r.get('source')}")
        except Exception as e:  # one menu missing would publish that restaurant with its change marks dropped
            raise SystemExit(f"ERROR: couldn't download the live {r['id']} menu to compare with ({e}). Not publishing: "
                             "a failed download must not wipe a restaurant's change marks. Retry, or pass "
                             "a different --previous DIR to tools/build.py to publish anyway.")


if __name__ == "__main__":
    main()
