#!/usr/bin/env python3
"""
List restaurants whose guide has ended or ends within three weeks, and
(with --github) open one GitHub issue for each, so a new guide can be added
before the app starts showing "may be out of date". Run after build.py.

Each city list (site/cities.json) gets a "Places check" issue a month after its last check, one city a morning; the
issue starts the scan routine, which re-checks the places and opens a pull request (tools/SCAN_INSTRUCTIONS.md).

There's one issue per restaurant per end date. Closing it (for example
because no newer guide exists yet) stops the reminder until the end date
changes, so it never nags daily.

Usage:
  python tools/reminders.py            # just list them
  python tools/reminders.py --github   # also open issues (needs GITHUB_TOKEN and GITHUB_REPOSITORY)
  python tools/reminders.py --index .previous/restaurants.json   # read the live index (tools/fetch_previous.py) instead of building
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gh  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"
WARN_DAYS = 21
CITY_EVERY = 30  # days between a city's re-checks
CITIES_A_DAY = 1  # new city issues a morning: each starts a routine run, and several at once would trip over each other


def due(today, index_path=None):
    index = json.loads((index_path or DATA / "restaurants.json").read_text(encoding="utf-8"))
    out = []
    for r in index["restaurants"]:
        end = (r.get("guide") or {}).get("validUntil")
        if end and (date.fromisoformat(end) - today).days <= WARN_DAYS:
            out.append((r, end, (date.fromisoformat(end) - today).days))
    # city lists (site/cities.json): the scan routine re-checks a city a month after its last check (the issue starts
    # it), well before the app calls the list possibly out of date at recheckDays; the longest unchecked first
    cities = json.loads((ROOT / "site" / "cities.json").read_text(encoding="utf-8"))
    for cid, c in sorted(cities.items(), key=lambda kv: kv[1]["checked"]):
        end = (date.fromisoformat(c["checked"]) + timedelta(days=c.get("recheckDays", 90))).isoformat()
        left = (date.fromisoformat(end) - today).days
        if (today - date.fromisoformat(c["checked"])).days >= CITY_EVERY:  # the routine's monthly re-check
            out.append(({"id": cid, "name": c["name"] + " places", "city": c, "kind": "recheck"}, end, left))
        if left <= WARN_DAYS:  # and the owner's own warning, under its own title, when no re-check has been merged
            out.append(({"id": cid, "name": c["name"] + " places", "city": c, "kind": "ends"}, end, left))
    return out


def issue_body(r, end, days):
    if r.get("kind") == "ends":
        c = r["city"]
        when = f"on {end}" if days >= 0 else f"since {end}"
        return (f"The **{r['name']}** list in the app was last checked on {c['checked']}, so the app warns that it may be out "
                f"of date {when}. The monthly re-check should have renewed it: look for an open pull request named "
                "\"Re-check …\" for this city and merge it, or re-check the list by hand and update `checked` in `site/cities.json`.\n\n"
                "_Opened automatically by `.github/workflows/guide-reminders.yml`._")
    if "city" in r:
        c = r["city"]
        return (f"The **{r['name']}** list in the app was checked on {c['checked']}. It's re-checked every month, and after "
                f"{end} the app warns that it may be out of date.\n\n"
                "The scan follows the \"Re-checking a city\" section of `tools/SCAN_INSTRUCTIONS.md`: it goes through "
                f"{c['list']['url']} and each place's own website, and opens a pull request for you to check, with any place "
                "that has closed or changed what it says, and the new check date. This issue closes once that pull request is open.\n\n"
                "_Opened automatically by `.github/workflows/guide-reminders.yml`._")
    folder = f"restaurants/{r['id']}/"
    when = f"ended on {end}" if days < 0 else f"ends on {end} ({days} days)"
    how = (f"Download the newest allergen guide from {r.get('officialUrl') or 'their website'} and upload the PDF to "
           f"`{folder}guides/` (on GitHub: open the folder, then **Add file → Upload files → Commit changes**). "
           "The publish workflow builds it, and the app shows what changed.")
    config = json.loads((ROOT / folder / "restaurant.json").read_text(encoding="utf-8"))
    if config.get("reader") == "manual_csv":
        how = (f"Check the restaurant's allergen information, then update `{folder}menu.csv` and the dates in `{folder}restaurant.json`. "
               f"If there's nothing newer, record the check in `latestGuide` in `{folder}restaurant.json` so the app can say so.")
    return (f"The **{r['name']}** guide in the app ({r.get('source')}) {when}. After that, the app warns that it may be out of date.\n\n"
            f"**To update:** {how}\n\n"
            "If there's no newer guide yet, close this issue. You won't be reminded again until the end date changes.\n\n"
            "_Opened automatically by `.github/workflows/guide-reminders.yml`._")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--github", action="store_true", help="open an issue for each guide that's due")
    ap.add_argument("--index", type=Path, help="the restaurants.json to read end dates from (default: site/data, as built; "
                                                "the workflow passes the live one from .previous/)")
    args = ap.parse_args()
    items = due(date.today(), args.index)
    if not items:
        print(f"No guides end within {WARN_DAYS} days.")
        return
    existing = gh.issue_titles() if args.github else set()
    cities_left = CITIES_A_DAY
    for r, end, days in items:
        if r.get("kind") == "ends":
            title = f"Places list ends: {r['name']} ({end})"
            print(f"{r['name']}: out of date {'since' if days < 0 else 'on'} {end}")
        elif "city" in r:
            title = f"Places check: {r['name']} (re-check due {end})"
            print(f"{r['name']}: checked {r['city']['checked']}, re-check due")
            if args.github and title not in existing:
                if not cities_left:
                    print("  tomorrow: one city a day")
                    continue
                cities_left -= 1
        else:
            title = f"Guide check: {r['name']} (guide ends {end})"
            print(f"{r['name']}: guide {'ended' if days < 0 else 'ends'} {end}")
        if args.github:
            if title in existing:
                print("  issue already exists")
            else:
                made = gh.request("POST", "/issues", {"title": title, "body": issue_body(r, end, days)})
                print(f"  opened {made['html_url']}")


if __name__ == "__main__":
    main()
