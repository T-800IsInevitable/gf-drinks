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
    for r in index.get("restaurants", []):
        try:
            (OUT / "r" / f"{r['id']}.json").write_bytes(get(base + r["file"]))
            print(f"  live {r['id']}: {r.get('source')}")
        except Exception as e:
            print(f"  live {r['id']}: couldn't download ({e})")


if __name__ == "__main__":
    main()
