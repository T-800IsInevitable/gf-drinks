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


AUTOMATED = ("scan", "city", "recheck", "guide-watch")


def scope(ref, paths):
    """What's wrong with a pull request from branch ref changing these paths: a list of problems, empty if fine."""
    # the prefix is read whatever its case, so "Scan/x" can't step round the limits below (the owner's own branches,
    # such as city-requests, have no slash after the word)
    kind = next((k for k in AUTOMATED if re.match(rf"{k}/", ref, re.I)), None)
    if kind and not ref.startswith(kind + "/"):
        return [f"branch {ref!r} looks like a {kind}/ branch but isn't named exactly {kind}/<id>-...; rename it"]
    if kind == "scan":
        # scan/<id>-<YYYY-MM-DD>, perhaps with a retry's suffix (-b): the restaurant the branch names, and only that one
        m = re.fullmatch(r"scan/([a-z0-9][a-z0-9-]*?)-\d{4}-\d{2}-\d{2}(?:-[a-z0-9]{1,8})?", ref)
        if not m:
            return [f"a scan/ branch is named scan/<id>-<YYYY-MM-DD>, not {ref!r}"]
        outside = sorted(p for p in paths if not p.startswith(f"restaurants/{m[1]}/"))
        return [f"a scan/ pull request for {m[1]} may change only restaurants/{m[1]}/, not {', '.join(outside)}"] if outside else []
    if kind == "guide-watch":
        # guide-watch/<id>-<hash>: a new guide PDF, and the old one moved to archive/, in that restaurant's guides/ only
        m = re.fullmatch(r"guide-watch/([a-z0-9][a-z0-9-]*?)-[0-9a-f]{10}", ref)
        if not m:
            return [f"a guide-watch/ branch is named guide-watch/<id>-<hash>, not {ref!r}"]
        outside = sorted(p for p in paths if not p.startswith(f"restaurants/{m[1]}/guides/"))
        return [f"a guide-watch/ pull request may change only restaurants/{m[1]}/guides/, not {', '.join(outside)}"] if outside else []
    if kind in ("city", "recheck"):
        outside = sorted(set(paths) - CITY_FILES)
        return [f"a {kind}/ pull request may change only site/cities.json, not {', '.join(outside)}"] if outside else []
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
