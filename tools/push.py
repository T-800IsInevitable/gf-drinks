#!/usr/bin/env python3
"""
Tell the phones about new menus: one push notification after a publish that brought a new guide, and the app's icon
badge with it. Also "Update N is live!" after a publish that raised the app's release number, when site/whatsnew.json
has notes for that release (opening the app's What's new page); a release without notes goes out quietly. Nothing is
sent when the publish changed no guide and no announced release (the same menus again).

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
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_release import app_number  # noqa: E402

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
    # a tag of its own: iPhones replace a notification with the same tag silently (no banner), so one still in the
    # Notification Centre would swallow the next
    msg = {"title": TITLE, "body": body[:400], "tag": "gf-menus-" + str(new_index.get("built", ""))[:16], "url": url, "nowAvoid": keys[:KEYS_MOST], "badge": len(news)}
    while msg["nowAvoid"] and len(json.dumps(msg, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        msg["nowAvoid"].pop()  # a big change must still arrive; the phone's favourites check then covers fewer items
    return msg


def release_plan(previous=ROOT / ".previous", site=SITE):
    """'Update N is live!' when this publish raises the release number past the live one (.previous/app-version, from
    fetch_previous.py) and whatsnew.json has notes for it, or None. An unknown live release announces nothing, so a
    failed download can't announce an old release again."""
    try:
        live = int((previous / "app-version").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    new = app_number((site / "app.js").read_text(encoding="utf-8"))
    note = next((n for n in read(site / "whatsnew.json") or [] if isinstance(n, dict) and n.get("version") == new), None)
    if new <= live or not note:
        return None
    # "?whatsnew", not a #: the phone may still be on the last release when it's tapped, which reads a # as a page name
    return {"title": f"Update {new} is live!", "body": f"Tap to see the new features: {note['title']}"[:400],
            "tag": f"gf-update-{new}", "url": "?whatsnew"}  # no badge: that counts the guides not yet looked at


def city_plan(previous=ROOT / ".previous", site=SITE):
    """'Leeds is in the app' when this publish adds a city to cities.json that the live one (.previous/cities.json, from
    fetch_previous.py) doesn't have, or None. As for the release, an unknown live list announces nothing, so a failed
    download can't announce every city again."""
    try:
        live, now = read(previous / "cities.json"), read(site / "cities.json")
    except ValueError:  # a damaged download: say nothing rather than stop the publish
        return None
    if not isinstance(live, dict) or not isinstance(now, dict):  # nor announce every city from a list that isn't one
        return None
    new = [cid for cid in now if cid not in live]
    if not new:
        return None
    names = [now[cid]["name"] for cid in new]
    places = sum(len(now[cid].get("places") or []) for cid in new)
    who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return {"title": f"{who} {'is' if len(names) == 1 else 'are'} in the app"[:120],
            "body": f"{places} {'place' if places == 1 else 'places'} to eat, from coeliac guides, each checked against its own website where it has one. Tap to see "
                    + ("it." if len(names) == 1 else "them."),
            "tag": "gf-cities-" + "-".join(new), "url": "#" + new[0] if len(new) == 1 else ""}


def messages(previous=ROOT / ".previous", data=SITE / "data", site=SITE):
    """Everything to send for this publish: the new guides first (what matters at the counter), then new cities, then
    the release."""
    return [m for m in (plan(previous, data), city_plan(previous, site), release_plan(previous, site)) if m]


def scrub(error):
    """An error's text without the long tokens in it (a connection error quotes the phone's address, which is secret)."""
    return re.sub(r"[A-Za-z0-9_-]{20,}", "…", str(error))[:200]


def contact(repository):
    """Who is sending, as push services ask: the app's own site. It must be a bare https address (no path) or a mailto:."""
    owner = (repository or "T-800IsInevitable/gf-drinks").split("/")[0].lower()
    return f"https://{owner}.github.io"


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
            lines.append(f"{who}: failed ({type(e).__name__}: {scrub(e)})")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="work out the message for this publish")
    ap.add_argument("--previous", type=Path, default=ROOT / ".previous")
    ap.add_argument("--out", type=Path, default=Path("push-message.json"))
    ap.add_argument("--send", type=Path, help="send the message in this file")
    args = ap.parse_args()
    if args.plan:
        msgs = messages(args.previous)
        args.out.write_text(json.dumps({"messages": msgs} if msgs else {"send": False}, indent=1, ensure_ascii=False), encoding="utf-8")
        print("push: " + (" | ".join(f"{m['title']}: {m['body']}" for m in msgs) if msgs else "no new guide or announced release, so nothing to send"))
        return
    if args.send:
        saved = read(args.send) or {}
        # {"messages": [...]}, or a single message as plans from before releases were announced wrote it
        msgs = saved.get("messages") if isinstance(saved.get("messages"), list) else [saved] if saved.get("body") else []
        if not msgs:
            print("push: nothing to send")
            return
        subs = subscriptions(os.environ.get("PUSH_SUBSCRIPTIONS"))
        key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
        if not subs or not key:
            print("push: no phones saved yet (set the PUSH_SUBSCRIPTIONS and VAPID_PRIVATE_KEY secrets), so nothing sent")
            return
        claim = contact(os.environ.get("GITHUB_REPOSITORY", ""))
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        for msg in msgs:
            lines = send(msg, subs, vapid_key(key), claim)
            print(f"{msg['title']}:\n" + "\n".join(lines))
            if summary:
                with open(summary, "a", encoding="utf-8") as f:
                    f.write(f"## Notification: {msg['title']}\n\n" + msg["body"] + "\n\n" + "\n".join(f"- {l}" for l in lines) + "\n")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
