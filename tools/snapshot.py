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


def order_lines(d):
    """What the order builder offers for a restaurant with "order" settings: in its section order, what can be ticked
    (parts of dishes included, ingredients listed on their own left out) and what's blocked as on the Avoid list.
    Saved as tests/snapshots/order-<id>.txt, so a reader change that moves a part shows up as a diff to review."""
    cfg = d.get("order") or {}
    first = [s for s in cfg.get("first", []) if s in d["sections"]]
    out = [f"# source: {d['source']}", f"# intro: {cfg.get('intro', '')}", f"# card: {cfg.get('cardLine', '')}"]
    for s in first + [s for s in d["sections"] if s not in first]:
        for i in d["items"]:
            if i["section"] == s and i.get("role") != "ingredient":
                out.append(f"TICK  | {s} | {i['name']} | {i['order']}" + (f" note={i['note']}" if i.get("note") else ""))
        for a in d["avoid"]:
            if a["section"] == s:
                out.append(f"BLOCK | {s} | {a['name']} | {a.get('tag') or ';'.join(a.get('gluten', []))}")
    return out


def compare(name, now, path, update, what):
    """True if the saved snapshot differs from what's built now (same guide only)."""
    if update:
        path.write_text("\n".join(now) + "\n", encoding="utf-8")
        print(f"{name}: snapshot saved ({len(now) - 1} {what})")
        return False
    if not path.exists():
        print(f"{name}: no snapshot yet. Check the {what}, then run: python tools/snapshot.py --update")
        return False
    saved = path.read_text(encoding="utf-8").splitlines()
    if saved[0] != now[0]:
        print(f"{name}: new guide ({now[0][10:]}), so not compared. Check the {what}, then run: python tools/snapshot.py --update")
        return False
    if saved != now:
        diff = list(difflib.unified_diff(saved, now, "snapshot", "built now", lineterm="", n=0))
        print(f"{name}: the same guide now gives different {what}:")
        print("\n".join("   " + x for x in diff[:60]))
        if len(diff) > 60:
            print(f"   ... and {len(diff) - 60} more lines")
        return True
    print(f"{name}: matches its snapshot")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="save the current menus as the snapshots")
    args = ap.parse_args()
    index = json.loads((DATA / "restaurants.json").read_text(encoding="utf-8"))
    failed = False
    SNAPS.mkdir(parents=True, exist_ok=True)
    for r in index["restaurants"]:
        d = json.loads((DATA.parent / r["file"]).read_text(encoding="utf-8"))
        failed |= compare(r["id"], lines(d), SNAPS / f"{r['id']}.txt", args.update, "items")
        if d.get("order"):
            failed |= compare(f"{r['id']} order builder", order_lines(d), SNAPS / f"order-{r['id']}.txt", args.update, "order choices")
    if failed:
        print("\nSNAPSHOT CHECK FAILED: a reader's output changed for the same guide. If that's intended, check the "
              "differences above against the guide, then run: python tools/snapshot.py --update")
        sys.exit(1)


if __name__ == "__main__":
    main()
