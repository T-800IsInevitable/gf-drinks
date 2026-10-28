#!/usr/bin/env python3
"""
A routine's pull request may change only its own files (run by .github/workflows/guard.yml, which comes from main
whatever the pull request changes, so a pull request can't loosen the rule that judges it).

The scan routine names its branches by what it does (tools/SCAN_INSTRUCTIONS.md):
  scan/<id>-<date>      one restaurant: files under restaurants/<id>/ only
  city/<id>-<date>      one city added: site/cities.json only
  recheck/<id>-<date>   one city re-checked: site/cities.json only
Any other branch is the owner's, with no limit here. The workflow then builds and checks every pull request's menus
and cities with main's own tools.

Usage (in guard.yml): PR=<number> HEAD_REF=<branch> python tools/guard.py   (GITHUB_TOKEN, GITHUB_REPOSITORY set)
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gh  # noqa: E402

CITY_FILES = {"site/cities.json"}


def scope(ref, paths):
    """What's wrong with a pull request from branch ref changing these paths: a list of problems, empty if fine."""
    if ref.startswith("scan/"):
        ids = {m[1] for p in paths if (m := re.fullmatch(r"restaurants/([a-z0-9][a-z0-9-]*)/.+", p))}
        outside = [p for p in paths if not re.fullmatch(r"restaurants/[a-z0-9][a-z0-9-]*/.+", p)]
        if outside:
            return [f"a scan/ pull request may change only one restaurant's folder, not {', '.join(sorted(outside))}"]
        if len(ids) > 1:
            return [f"a scan/ pull request changes one restaurant, not {', '.join(sorted(ids))}"]
        return []
    if ref.startswith(("city/", "recheck/")):
        outside = sorted(set(paths) - CITY_FILES)
        return [f"a {ref.split('/')[0]}/ pull request may change only site/cities.json, not {', '.join(outside)}"] if outside else []
    return []


def changed(pr, pages=30):
    """Every path the pull request touches, both names of a renamed file included."""
    paths = []
    for page in range(1, pages + 1):
        batch = gh.request("GET", f"/pulls/{pr}/files?per_page=100&page={page}")
        for f in batch:
            paths += [f["filename"]] + ([f["previous_filename"]] if f.get("previous_filename") else [])
        if len(batch) < 100:
            return paths
    raise SystemExit("ERROR: more files than the guard reads; split the pull request")


def main():
    ref = os.environ["HEAD_REF"]
    problems = scope(ref, changed(os.environ["PR"]))
    for p in problems:
        print("GUARD:", p)
    if problems:
        sys.exit(1)
    print(f"guard: {ref} changes only what it may")


if __name__ == "__main__":
    main()
