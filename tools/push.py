#!/usr/bin/env python3
"""
Tell the phones about new menus: one push notification after a publish that brought a new guide, and the app's icon
badge with it. Nothing is sent when the publish changed no guide (a code-only release, or the same menus again).

There's no server. Each phone's push subscription is saved by hand as the repository secret PUSH_SUBSCRIPTIONS (one
JSON object per line, or a JSON array), and the private half of the push key pair as VAPID_PRIVATE_KEY (its public
half is PUSH_KEY in site/app.js). The secret may hold the key as PEM text ("-----BEGIN PRIVATE KEY-----" ...) or as
the 43-character base64url value py_vapid calls raw. The phone decides for itself whether a favourite is among the
items that now contain gluten: the message carries their keys, and the service worker holds a copy of the favourites.

To make a new key pair (if the private half is lost; phones then switch notifications on again):
  pip install py-vapid && vapid --gen                  # writes private_key.pem and public_key.pem
  vapid --applicationServerKey                         # the public half: paste it into PUSH_KEY in site/app.js
  the VAPID_PRIVATE_KEY secret: the text of private_key.pem

Usage:
  python tools/push.py --plan [--out push-message.json]   # after build.py, with .previous/ from fetch_previous.py
  python tools/push.py --send push-message.json           # after the deploy; needs the two secrets in the environment
"""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    from py_vapid import Vapid
    from pywebpush import WebPushException, webpush
except ImportError:  # only --send needs them (the notify job installs them)
    Vapid, WebPushException, webpush = None, Exception, None

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
TITLE = "New menus in Treat Temple"
MOST = 3  # restaurants named in the message; the rest are counted
KEYS_MOST = 80  # "now contains gluten" keys carried for the phone's favourites check, at most
MAX_BYTES = 3500  # push services refuse a payload over about 4 KB, so the keys are trimmed to fit under this


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
    msg = {"title": TITLE, "body": body[:400], "tag": "gf-menus", "url": url, "nowAvoid": keys[:KEYS_MOST], "badge": len(news)}
    while msg["nowAvoid"] and len(json.dumps(msg, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        msg["nowAvoid"].pop()  # a big change must still arrive; the phone's favourites check then covers fewer items
    return msg


def vapid_key(text):
    """The private key as the secret holds it: PEM text becomes a Vapid instance; a raw base64url value is passed as is."""
    text = (text or "").strip()
    if "BEGIN" in text and Vapid is not None:
        return Vapid.from_pem(text.encode("utf-8"))
    return text


def loads_lenient(text):
    """JSON, or JSON whose characters a share sheet or notes app turned into web-address codes ({ as %7B, " as %22)."""
    try:
        return json.loads(text)
    except ValueError:
        if "%" not in text:
            raise
        return json.loads(unquote(text))


def subscriptions(text):
    """The saved subscriptions: a JSON array, one object, or one object per line (blank lines and # notes ignored)."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        d = loads_lenient(text)
        return d if isinstance(d, list) else [d]
    except ValueError:
        out = []
        for n, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                out.append(loads_lenient(line))
            except ValueError:
                raise SystemExit(f"ERROR: PUSH_SUBSCRIPTIONS line {n} isn't JSON (it should start with {{\"endpoint\": and end with }})")
        return out


def send(msg, subs, private_key, claim):
    """Send msg to each subscription. Returns one line per phone: sent, gone (needs switching on again) or failed."""
    if webpush is None:
        raise SystemExit("ERROR: pip install pywebpush")
    lines = []
    for n, sub in enumerate(subs, 1):
        # the host only: part of an endpoint is part of a secret, and the job's log is public
        who = f"phone {n} ({urlparse(str((sub or {}).get('endpoint') or '')).netloc or 'no endpoint'})"
        try:
            webpush(subscription_info=sub, data=json.dumps(msg), vapid_private_key=private_key, vapid_claims={"sub": claim}, ttl=86400)
            lines.append(f"{who}: sent")
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                lines.append(f"{who}: gone. Its subscription has expired: open Help on that phone and tap Tell me about new menus again, then save the new one.")
            else:
                lines.append(f"{who}: failed ({status or e})")
        except Exception as e:  # a malformed line or key: say so for this phone and carry on with the others
            lines.append(f"{who}: failed ({type(e).__name__}: {e})")
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
        lines = send(msg, subs, vapid_key(key), claim)
        print("\n".join(lines))
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write("## Notifications\n\n" + msg["body"] + "\n\n" + "\n".join(f"- {l}" for l in lines) + "\n")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
