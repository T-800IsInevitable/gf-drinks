#!/usr/bin/env python3
"""
Open a GitHub issue for each upload waiting in inbox/ on the `uploads` branch, so the Claude scan can start the moment
a menu arrives instead of waiting for its daily run.

The scan routine can't watch a branch (GitHub triggers on routines cover pull requests, releases and issues only), but it
can start when an issue opens. This runs every 15 minutes (.github/workflows/upload-notice.yml), reads the branch, and
opens "Upload waiting: <folder>" once per folder. A folder that already has an issue, open or closed, gets no second one,
so a processed upload doesn't come back. Only the folder name and the restaurant and area from upload.json go in the
issue; the uploader's free-text notes don't.

Usage:
  python tools/upload_notice.py            # list uploads waiting; changes nothing
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


def git(*args):
    run = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 else None


def waiting():
    """The upload folders on the uploads branch, each with the restaurant and area its upload.json names."""
    listed = git("ls-tree", "--name-only", BRANCH, "inbox/")
    out = []
    for path in (listed or "").splitlines():
        folder = path.split("/", 1)[1]
        if folder.lower() == "readme.md":
            continue
        meta = {}
        try:
            meta = json.loads(git("show", f"{BRANCH}:{path}/upload.json") or "{}")
        except ValueError:
            pass
        clean = lambda v: re.sub(r"[`\s]+", " ", str(v or "")).strip()[:80]
        out.append({"folder": folder, "restaurant": clean(meta.get("restaurant")), "area": clean(meta.get("area"))})
    return out


def issue_body(u):
    what = " ".join(x for x in (u["restaurant"], u["area"]) if x) or "a menu"
    return (f"A menu is waiting in `inbox/{u['folder']}/` on the `uploads` branch ({what}).\n\n"
            "The scan follows `tools/SCAN_INSTRUCTIONS.md`: it reads the upload and opens a pull request for you to check. "
            "This issue closes once that pull request is open.\n\n"
            "_Opened automatically by `.github/workflows/upload-notice.yml` (`tools/upload_notice.py`)._")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--github", action="store_true", help="open an issue for each upload without one")
    args = ap.parse_args()
    uploads = waiting()
    if not uploads:
        print("No uploads waiting.")
        return
    titles = gh.issue_titles() if args.github else set()
    for u in uploads:
        title = TITLE + u["folder"]
        print(f"{u['folder']}: {u['restaurant'] or 'unnamed'}, {u['area'] or 'no area'}")
        if args.github:
            if title in titles:
                print("  issue already opened")
            else:
                made = gh.request("POST", "/issues", {"title": title, "body": issue_body(u)})
                print(f"  opened {made['html_url']}")


if __name__ == "__main__":
    main()
