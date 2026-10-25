#!/usr/bin/env python3
"""
List restaurants whose guide has ended or ends within three weeks, and
(with --github) open one GitHub issue for each, so a new guide can be added
before the app starts showing "may be out of date". Run after build.py.

There's one issue per restaurant per end date. Closing it (for example
because no newer guide exists yet) stops the reminder until the end date
changes, so it never nags daily.

Usage:
  python tools/reminders.py            # just list them
  python tools/reminders.py --github   # also open issues (needs GITHUB_TOKEN and GITHUB_REPOSITORY)
"""
import argparse
import json
import os
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"
WARN_DAYS = 21


def due(today):
    index = json.loads((DATA / "restaurants.json").read_text(encoding="utf-8"))
    out = []
    for r in index["restaurants"]:
        end = (r.get("guide") or {}).get("validUntil")
        if end and (date.fromisoformat(end) - today).days <= WARN_DAYS:
            out.append((r, end, (date.fromisoformat(end) - today).days))
    return out


def github(method, path, body=None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}{path}", method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read() or "null")


def issue_body(r, end, days):
    folder = f"restaurants/{r['id']}/"
    when = f"ended on {end}" if days < 0 else f"ends on {end} ({days} days)"
    how = (f"Download the newest allergen guide from {r.get('officialUrl') or 'their website'} and upload the PDF to "
           f"`{folder}guides/` (on GitHub: open the folder, then **Add file → Upload files → Commit changes**). "
           "The publish workflow builds it, and the app shows what changed.")
    config = json.loads((ROOT / folder / "restaurant.json").read_text(encoding="utf-8"))
    if config.get("reader") == "manual_csv":
        how = f"Check the restaurant's allergen information, then update `{folder}menu.csv` and the dates in `{folder}restaurant.json`."
    return (f"The **{r['name']}** guide in the app ({r.get('source')}) {when}. After that, the app warns that it may be out of date.\n\n"
            f"**To update:** {how}\n\n"
            "If there's no newer guide yet, close this issue. You won't be reminded again until the end date changes.\n\n"
            "_Opened automatically by `.github/workflows/guide-reminders.yml`._")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--github", action="store_true", help="open an issue for each guide that's due")
    args = ap.parse_args()
    items = due(date.today())
    if not items:
        print(f"No guides end within {WARN_DAYS} days.")
        return
    existing = set()
    if args.github:
        for page in range(1, 6):
            batch = github("GET", f"/issues?state=all&per_page=100&page={page}")
            existing |= {i["title"] for i in batch}
            if len(batch) < 100:
                break
    for r, end, days in items:
        title = f"Guide check: {r['name']} (guide ends {end})"
        print(f"{r['name']}: guide {'ended' if days < 0 else 'ends'} {end}")
        if args.github:
            if title in existing:
                print("  issue already exists")
            else:
                made = github("POST", "/issues", {"title": title, "body": issue_body(r, end, days)})
                print(f"  opened {made['html_url']}")


if __name__ == "__main__":
    main()
