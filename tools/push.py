#!/usr/bin/env python3
"""
Tell the phones about new menus: one push notification after a publish that brought a new guide, and the app's icon
badge with it. Nothing is sent when the publish changed no guide (a code-only release, or the same menus again).

There's no server. Each phone's push subscription is saved by hand as the repository secret PUSH_SUBSCRIPTIONS (one
JSON object per line, or a JSON array), and the private half of the push key pair as VAPID_PRIVATE_KEY (its public
half is PUSH_KEY in site/app.js). The phone decides for itself whether a favourite is among the items that now
contain gluten: the message carries their keys, and the service worker holds a copy of the favourites.

Usage:
  python tools/push.py --plan [--out push-message.json]   # after build.py, with .previous/ from fetch_previous.py
  python tools/push.py --send push-message.json           # after the deploy; needs the two secrets in the environment
"""
import argparse
import json
import os
from pathlib import Path

try:
    from pywebpush import WebPushException, webpush
except ImportError:  # only --send needs it (the notify job installs it)
    WebPushException, webpush = Exception, None

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
TITLE = "New menus in Treat Temple"
MOST = 3  # restaurants named in the message; the rest are counted
KEYS_MOST = 80  # "now contains gluten" keys carried for the phone's favourites check (a push payload is small)


def read(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def counts(c):
    """'26 new, 2 now contain gluten' from a restaurant's changes (tools/changes.py), in the order that matters."""
    parts = [("nowAvoid", "now contain gluten", "now contains gluten"), ("nowOk", "no longer to avoid", "no longer to avoid"),
             ("changed", "ordered differently", "ordered differently"), ("added", "new", "new"), ("removed", "gone", "gone")]
    out = []
    for k, many, one in parts:
        n = len((c or {}).get(k) or [])
        if n:
            out.append(f"{n} {one if n == 1 else many}")
    return ", ".join(out)


def plan(previous=ROOT / ".previous", data=SITE / "data"):
    """The message for this publish, or None when no restaurant has a new guide."""
    new_index = read(data / "restaurants.json")
    if not new_index:
        raise SystemExit("ERROR: no built menus (run tools/build.py first)")
    old = {r["id"]: r for r in (read(previous / "restaurants.json") or {"restaurants": []})["restaurants"]}
    news, keys = [], []
    for r in new_index["restaurants"]:
        was = old.get(r["id"])
        if was and was.get("source") == r.get("source"):
            continue
        full = read(data / "r" / f"{r['id']}.json") or {}
        c = full.get("changes") if was else None  # a restaurant new to the app has nothing to compare with
        guide = (r.get("guide") or {}).get("title") or ""
        what = counts(c) if was else f"{(r.get('stats') or {}).get('items', 0)} items with no gluten ingredients"
        news.append(f"{r['name']}: {guide + ' guide' if guide and guide != 'Allergen guide' else 'new guide'}" + (f": {what}" if what else ""))
        keys += [f"{r['id']}|{x.get('section', '')}|{x.get('name', '')}" for x in (c or {}).get("nowAvoid") or []]
    if not news:
        return None
    body = "; ".join(news[:MOST]) + (f"; and {len(news) - MOST} more" if len(news) > MOST else "") + "."
    url = "#" + new_index["restaurants"][0]["id"] if len(news) == 1 and len(new_index["restaurants"]) else ""
    if len(news) == 1:
        url = "#" + next(r["id"] for r in new_index["restaurants"] if news[0].startswith(r["name"] + ":"))
    return {"title": TITLE, "body": body[:400], "tag": "gf-menus", "url": url, "nowAvoid": keys[:KEYS_MOST], "badge": len(news)}


def subscriptions(text):
    """The saved subscriptions: a JSON array, one object, or one object per line (blank lines and # notes ignored)."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        d = json.loads(text)
        return d if isinstance(d, list) else [d]
    except ValueError:
        out = []
        for n, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                raise SystemExit(f"ERROR: PUSH_SUBSCRIPTIONS line {n} isn't JSON")
        return out


def send(msg, subs, private_key, claim):
    """Send msg to each subscription. Returns one line per phone: sent, gone (needs switching on again) or failed."""
    if webpush is None:
        raise SystemExit("ERROR: pip install pywebpush")
    lines = []
    for n, sub in enumerate(subs, 1):
        who = f"phone {n} ({(sub.get('endpoint') or '?')[:40]}…)"
        try:
            webpush(subscription_info=sub, data=json.dumps(msg), vapid_private_key=private_key, vapid_claims={"sub": claim}, ttl=86400)
            lines.append(f"{who}: sent")
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                lines.append(f"{who}: gone. Its subscription has expired: open Help on that phone and tap Tell me about new menus again, then save the new one.")
            else:
                lines.append(f"{who}: failed ({status or e})")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="work out the message for this publish")
    ap.add_argument("--previous", type=Path, default=ROOT / ".previous")
    ap.add_argument("--out", type=Path, default=Path("push-message.json"))
    ap.add_argument("--send", type=Path, help="send the message in this file")
    args = ap.parse_args()
    if args.plan:
        msg = plan(args.previous)
        args.out.write_text(json.dumps(msg or {"send": False}, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"push: {msg['body'] if msg else 'no new guide, so nothing to send'}")
        return
    if args.send:
        msg = read(args.send)
        if not msg or msg.get("send") is False:
            print("push: nothing to send")
            return
        subs = subscriptions(os.environ.get("PUSH_SUBSCRIPTIONS"))
        key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
        if not subs or not key:
            print("push: no phones saved yet (set the PUSH_SUBSCRIPTIONS and VAPID_PRIVATE_KEY secrets), so nothing sent")
            return
        claim = "https://github.com/" + os.environ.get("GITHUB_REPOSITORY", "T-800IsInevitable/gf-drinks")
        lines = send(msg, subs, key, claim)
        print("\n".join(lines))
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write("## Notifications\n\n" + msg["body"] + "\n\n" + "\n".join(f"- {l}" for l in lines) + "\n")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
