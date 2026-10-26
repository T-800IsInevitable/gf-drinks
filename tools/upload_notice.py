#!/usr/bin/env python3
"""
Open a GitHub issue for each upload waiting in inbox/ on the `uploads` branch, and for each place asked for by name
(inbox/requests/<file>.json), so the Claude scan can start the moment something arrives instead of waiting for its
weekly run.

The scan routine can't watch a branch (GitHub triggers on routines cover pull requests, releases and issues only), but it
can start when an issue opens. This runs every 15 minutes (.github/workflows/upload-notice.yml), reads the branch, and
opens "Upload waiting: <folder>" once per folder and "Place requested: <name> (<area>)" once per request. A folder or
request that already has an issue, open or closed, gets no second one, so a processed upload doesn't come back. Only
the folder name and the restaurant and area from upload.json go in the issue; the uploader's free-text notes don't.

Usage:
  python tools/upload_notice.py            # list what's waiting; changes nothing
  python tools/upload_notice.py --github   # also open the issues (needs GITHUB_TOKEN and GITHUB_REPOSITORY)
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gh  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BRANCH = "origin/uploads"
TITLE = "Upload waiting: "
REQUEST_TITLE = "Place requested: "
REQUESTS = "requests"  # inbox/requests/<when>-<name>-<area>.json: a place asked for by name, with no menu yet


def git(*args):
    run = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 else None


def clean(v):
    return re.sub(r"[`\s]+", " ", str(v or "")).strip()[:80]


def read_json(path):
    try:
        return json.loads(git("show", f"{BRANCH}:{path}") or "{}")
    except ValueError:
        return {}


def waiting():
    """The upload folders on the uploads branch, each with the restaurant and area its upload.json names."""
    listed = git("ls-tree", "--name-only", BRANCH, "inbox/")
    out = []
    for path in (listed or "").splitlines():
        folder = path.split("/", 1)[1]
        if folder.lower() == "readme.md" or folder == REQUESTS:
            continue
        meta = read_json(f"{path}/upload.json")
        out.append({"folder": folder, "restaurant": clean(meta.get("restaurant")), "area": clean(meta.get("area"))})
    return out


def requests_waiting():
    """The places asked for by name (inbox/requests/*.json on the uploads branch): file, name, area and website."""
    listed = git("ls-tree", "--name-only", BRANCH, f"inbox/{REQUESTS}/")
    out = []
    for path in (listed or "").splitlines():
        if not path.endswith(".json"):
            continue
        meta = read_json(path)
        url = str(meta.get("url") or "").strip()
        out.append({"file": path.split("/")[-1], "name": clean(meta.get("name")), "area": clean(meta.get("area")),
                    "url": url if url.startswith("https://") else ""})
    return out


def issue_body(u):
    what = " ".join(x for x in (u["restaurant"], u["area"]) if x) or "a menu"
    return (f"A menu is waiting in `inbox/{u['folder']}/` on the `uploads` branch ({what}).\n\n"
            "The scan follows `tools/SCAN_INSTRUCTIONS.md`: it reads the upload and opens a pull request for you to check. "
            "This issue closes once that pull request is open.\n\n"
            "_Opened automatically by `.github/workflows/upload-notice.yml` (`tools/upload_notice.py`)._")


def request_title(q):
    return REQUEST_TITLE + (q["name"] or "a place") + (f" ({q['area']})" if q["area"] else "")


def request_body(q):
    return (f"Someone asked for **{q['name'] or 'a place'}**{' in ' + q['area'] if q['area'] else ''} from the app, by name only"
            f"{' (website: ' + q['url'] + ')' if q['url'] else ''}. The request is `inbox/{REQUESTS}/{q['file']}` on the `uploads` branch.\n\n"
            "The scan follows the \"Places asked for by name\" section of `tools/SCAN_INSTRUCTIONS.md`: it looks for the place's "
            "own published allergen information, and opens a pull request for you to check if it finds some. If it finds none, "
            "it says so here and leaves this issue open for you.\n\n"
            "_Opened automatically by `.github/workflows/upload-notice.yml` (`tools/upload_notice.py`)._")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--github", action="store_true", help="open an issue for each upload and request without one")
    args = ap.parse_args()
    uploads, requests = waiting(), requests_waiting()
    if not uploads and not requests:
        print("No uploads or requests waiting.")
        return
    titles = gh.issue_titles() if args.github else set()

    def open_issue(title, body):
        if not args.github:
            return
        if title in titles:
            print("  issue already opened")
        else:
            made = gh.request("POST", "/issues", {"title": title, "body": body})
            print(f"  opened {made['html_url']}")

    for u in uploads:
        print(f"{u['folder']}: {u['restaurant'] or 'unnamed'}, {u['area'] or 'no area'}")
        open_issue(TITLE + u["folder"], issue_body(u))
    for q in requests:
        print(f"request {q['file']}: {q['name'] or 'unnamed'}, {q['area'] or 'no area'}")
        open_issue(request_title(q), request_body(q))


if __name__ == "__main__":
    main()
