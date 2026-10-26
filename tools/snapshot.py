#!/usr/bin/env python3
"""
Compare each restaurant's built menu with a saved snapshot, so a change to a
reader can't quietly change what's listed. Run after build.py.

Snapshots live in tests/snapshots/<id>.txt, one line per item, headed by the
guide they were made from. A snapshot is only compared when it was made from
the same guide: a new guide is reported, not failed, because the menu is
expected to change (the app shows what changed; see tools/changes.py).

Usage:
  python tools/snapshot.py           # check (fails if a reader's output changed)
  python tools/snapshot.py --update  # save the current menus as the snapshots
"""
import argparse
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"
SNAPS = ROOT / "tests" / "snapshots"


def lines(d):
    out = [f"# source: {d['source']}"]
    for i in d["items"]:
        how = i["order"]
        if i.get("ok"):
            how += f" ok={';'.join(i['ok'])}"
        if i.get("not"):
            how += f" not={';'.join(i['not'])}"
        if i.get("note"):
            how += f" note={i['note']}"
        if i.get("role"):
            how += f" role={i['role']}"
        out.append(f"OK    | {i['section']} | {i['name']} | {how}")
    for a in d["avoid"]:
        out.append(f"AVOID | {a['section']} | {a['name']} | {';'.join(a.get('gluten', []))}" + (f" tag={a['tag']}" if a.get("tag") else "")
                   + (f" role={a['role']}" if a.get("role") else ""))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="save the current menus as the snapshots")
    args = ap.parse_args()
    index = json.loads((DATA / "restaurants.json").read_text(encoding="utf-8"))
    failed = False
    SNAPS.mkdir(parents=True, exist_ok=True)
    for r in index["restaurants"]:
        d = json.loads((DATA.parent / r["file"]).read_text(encoding="utf-8"))
        now = lines(d)
        path = SNAPS / f"{r['id']}.txt"
        if args.update:
            path.write_text("\n".join(now) + "\n", encoding="utf-8")
            print(f"{r['id']}: snapshot saved ({len(now) - 1} items)")
            continue
        if not path.exists():
            print(f"{r['id']}: no snapshot yet. Check the menu, then run: python tools/snapshot.py --update")
            continue
        saved = path.read_text(encoding="utf-8").splitlines()
        if saved[0] != now[0]:
            print(f"{r['id']}: new guide ({now[0][10:]}), so not compared. Check the menu, then run: python tools/snapshot.py --update")
            continue
        if saved != now:
            failed = True
            diff = list(difflib.unified_diff(saved, now, "snapshot", "built now", lineterm="", n=0))
            print(f"{r['id']}: the same guide now gives a different menu:")
            print("\n".join("   " + x for x in diff[:60]))
            if len(diff) > 60:
                print(f"   ... and {len(diff) - 60} more lines")
        else:
            print(f"{r['id']}: matches its snapshot")
    if failed:
        print("\nSNAPSHOT CHECK FAILED: a reader's output changed for the same guide. If that's intended, check the "
              "differences above against the guide, then run: python tools/snapshot.py --update")
        sys.exit(1)


if __name__ == "__main__":
    main()
