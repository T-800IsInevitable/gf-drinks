#!/usr/bin/env python3
"""
A routine's or a workflow's pull request may change only its own files (run by .github/workflows/guard.yml, which
comes from main whatever the pull request changes, so a pull request can't loosen the rule that judges it).

The scan routine and the guide watch name their branches by what they do (tools/SCAN_INSTRUCTIONS.md,
tools/watch_guides.py):
  scan/<id>-<date>          one restaurant: files under restaurants/<id>/ only
  city/<id>-<date>          one city added: site/cities.json only
  recheck/<id>-<date>       one city re-checked: site/cities.json only
  guide-watch/<id>-<hash>   a new guide: files under restaurants/<id>/guides/ only (so a reader fix, a snapshot or
                            avoidDropOk for that guide goes in a pull request of the owner's own, merged first)
A branch's name is chosen by whoever opens the pull request, so the name alone isn't trusted: a pull request that
carries a commit made by the routine (author Claude) or by a workflow (github-actions[bot]) must be on one of those
branches. Only a pull request whose commits are all the owner's own (or Dependabot's) has no limit here. The
workflow then builds and checks every pull request's menus and cities with main's own tools.

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
# who made a commit, as GitHub records it: the scan routine commits as Claude, a workflow as github-actions[bot]
MACHINE_EMAILS = {"noreply@anthropic.com"}
MACHINE_LOGINS = {"claude", "github-actions[bot]"}


def machine_made(commits):
    """Whether any of the pull request's commits (GitHub's list) was made by the routine or a workflow."""
    for c in commits:
        people = [(c.get("commit") or {}).get(k) or {} for k in ("author", "committer")]
        logins = {(c.get(k) or {}).get("login") for k in ("author", "committer")}
        if logins & MACHINE_LOGINS or {str(p.get("email") or "").lower() for p in people} & MACHINE_EMAILS:
            return True
    return False


def scope(ref, paths, machine=False):
    """What's wrong with a pull request from branch ref changing these paths: a list of problems, empty if fine.
    machine: one of its commits was made by the routine or a workflow."""
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
        return [f"a guide-watch/ pull request may change only restaurants/{m[1]}/guides/, not {', '.join(outside)}. A reader fix, "
                "a snapshot or avoidDropOk goes in a pull request of your own, merged first"] if outside else []
    if kind in ("city", "recheck"):
        outside = sorted(set(paths) - CITY_FILES)
        return [f"a {kind}/ pull request may change only site/cities.json, not {', '.join(outside)}"] if outside else []
    if machine:
        return [f"branch {ref!r} carries a commit made by the routine or a workflow, so it must be a scan/, city/, recheck/ or "
                "guide-watch/ branch and keep to that branch's files. If the work is your own, make the commits yourself"]
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


def commits(pr, pages=3):
    """The pull request's commits as GitHub lists them (it lists 250 at most)."""
    out = []
    for page in range(1, pages + 1):
        batch = gh.request("GET", f"/pulls/{pr}/commits?per_page=100&page={page}")
        out += batch
        if len(batch) < 100:
            break
    return out


def main():
    ref = os.environ["HEAD_REF"]
    problems = scope(ref, changed(os.environ["PR"]), machine_made(commits(os.environ["PR"])))
    for p in problems:
        print("GUARD:", p)
    if problems:
        sys.exit(1)
    print(f"guard: {ref} changes only what it may")


if __name__ == "__main__":
    main()
