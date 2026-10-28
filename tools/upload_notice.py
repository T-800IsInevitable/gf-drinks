#!/usr/bin/env python3
"""
Open a GitHub issue for each upload waiting in inbox/ on the `uploads` branch, and for each place asked for by name
(inbox/requests/<file>.json), so the Claude scan can start the moment something arrives instead of waiting for its
weekly run.

The scan routine can't watch a branch (GitHub triggers on routines cover pull requests, releases and issues only), but it
can start when an issue opens. This runs every 15 minutes (.github/workflows/upload-notice.yml), reads the branch, and
opens "Upload waiting: <folder>" once per folder, "Place requested: <name> (<area>)" once per request, and "City
requested: <city> (<country>)" once per city asked for (a request with "kind": "city"). A folder or
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
CITY_TITLE = "City requested: "
REQUESTS = "requests"  # inbox/requests/<when>-<name>-<area>.json: a place (or, with "kind": "city", a city) asked for by name
URL = re.compile(r"https://[^\s/<>()\[\]`'\"]+\.[^\s<>()\[\]`'\"]+")  # a website as passed on to the issue: no markdown, no second line


def git(*args):
    run = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 else None


def clean(v):
    return re.sub(r"[`\s]+", " ", str(v or "")).strip()[:80]


def clean_name(v):
    """A folder or file name as it goes into an issue (in backticks): the app's names are letters, digits, dots, dashes and
    underscores, so anything else is dropped rather than let it end the code span and become markdown."""
    return re.sub(r"[^A-Za-z0-9._-]", "", str(v or ""))[:80] or "upload"


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
        out.append({"folder": clean_name(folder), "restaurant": clean(meta.get("restaurant")), "area": clean(meta.get("area"))})
    return out


def requests_waiting():
    """The places and cities asked for by name (inbox/requests/*.json on the uploads branch): file, kind, name, area
    (a city's country) and website."""
    listed = git("ls-tree", "--name-only", BRANCH, f"inbox/{REQUESTS}/")
    out = []
    for path in (listed or "").splitlines():
        if not path.endswith(".json"):
            continue
        meta = read_json(path)
        url = str(meta.get("url") or "").strip()[:200]
        out.append({"file": clean_name(path.split("/")[-1]), "kind": "city" if meta.get("kind") == "city" else "place",
                    "name": clean(meta.get("name")), "area": clean(meta.get("area")),
                    "url": url if URL.fullmatch(url) else ""})  # one plain https address, or nothing
    return out


def issue_body(u):
    # in code spans, as request_body has them: no @mention or link from the uploader's words
    what = " ".join(f"`{x.replace('`', '')}`" for x in (u["restaurant"], u["area"]) if x) or "a menu"
    return (f"A menu is waiting in `inbox/{u['folder']}/` on the `uploads` branch ({what}).\n\n"
            "The scan follows `tools/SCAN_INSTRUCTIONS.md`: it reads the upload and opens a pull request for you to check. "
            "This issue closes once that pull request is open.\n\n"
            "_Opened automatically by `.github/workflows/upload-notice.yml` (`tools/upload_notice.py`)._")


def request_title(q):
    # the request's own time from its file name, so asking again after an earlier request's issue was closed (nothing
    # found, or its pull request turned down) still gets an issue, and the scan starts
    when = re.match(r"\d{4}-\d{2}-\d{2}T\d{4}", q["file"])
    stamp = f" [{when.group(0)}]" if when else ""
    if q["kind"] == "city":
        return CITY_TITLE + (q["name"] or "a city") + (f" ({q['area']})" if q["area"] else "") + stamp
    return REQUEST_TITLE + (q["name"] or "a place") + (f" ({q['area']})" if q["area"] else "") + stamp


def request_body(q):
    if q["kind"] == "city":  # as for a place: someone's typing, shown as code
        return (f"Someone asked from the app for the places in `{q['name'] or 'a city'}`{' (`' + q['area'] + '`)' if q['area'] else ''}. "
                f"The request is `inbox/{REQUESTS}/{q['file']}` on the `uploads` branch.\n\n"
                "The scan follows the \"Cities asked for\" section of `tools/SCAN_INSTRUCTIONS.md`: it finds the places there "
                "that say everything they serve is gluten free (or that have a separate gluten free kitchen), checks each one "
                "against its own website, and opens a pull request for you to check. If it finds none, it says so here and "
                "leaves this issue open for you.\n\n"
                "_Opened automatically by `.github/workflows/upload-notice.yml` (`tools/upload_notice.py`)._")
    # the name, area and website are someone's typing: shown as code, so they can't become markdown or a link
    return (f"Someone asked for `{q['name'] or 'a place'}`{' in `' + q['area'] + '`' if q['area'] else ''} from the app, by name only"
            f"{' (website: `' + q['url'] + '`)' if q['url'] else ''}. The request is `inbox/{REQUESTS}/{q['file']}` on the `uploads` branch.\n\n"
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
        print(f"{q['kind']} request {q['file']}: {q['name'] or 'unnamed'}, {q['area'] or 'no area'}")
        open_issue(request_title(q), request_body(q))


if __name__ == "__main__":
    main()
