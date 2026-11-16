#!/usr/bin/env python3
"""
A routine's or a workflow's pull request may change only its own files (run by .github/workflows/guard.yml, which
comes from main whatever the pull request changes, so a pull request can't loosen the rule that judges it).

The scan routine and the guide watch name their branches by what they do (tools/SCAN_INSTRUCTIONS.md,
tools/watch_guides.py):
  scan/<id>-<date>          one restaurant: files under restaurants/<id>/ only. When main already has that restaurant
                            and a reader builds it, only its guides/ and source/ (as for guide-watch/ below)
  city/<id>-<date>          one city added: site/cities.json only, and in it only the new entry <id>
  recheck/<id>-<date>       one city re-checked: site/cities.json only, and in it only the entry <id>
  guide-watch/<id>-<hash>   a new guide: files under restaurants/<id>/guides/ only (so a reader fix, a snapshot or
                            avoidDropOk for that guide goes in a pull request of the owner's own, merged first)
A branch's name is chosen by whoever opens the pull request, so the name alone isn't trusted: a pull request that
carries a commit made by the routine (author Claude) or by a workflow (github-actions[bot]) must be on one of those
branches. Only a pull request whose commits are all the owner's own (or Dependabot's) has no limit here. The
workflow then builds and checks every pull request's menus and cities with main's own tools.

Usage (in guard.yml): PR=<number> HEAD_REF=<branch> python tools/guard.py   (GITHUB_TOKEN, GITHUB_REPOSITORY set)
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gh  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CITY_FILES = {"site/cities.json"}
# scan/<id>-<YYYY-MM-DD>, perhaps with a retry's suffix (-b); city/ and recheck/ branches are named the same way
SCAN_REF = re.compile(r"scan/([a-z0-9][a-z0-9-]*?)-\d{4}-\d{2}-\d{2}(?:-[a-z0-9]{1,8})?")
CITY_REF = re.compile(r"(city|recheck)/([a-z0-9][a-z0-9-]*?)-\d{4}-\d{2}-\d{2}(?:-[a-z0-9]{1,8})?")


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


def reader_built(ref, root=None):
    """Whether a scan/ branch names a restaurant that main already has and a reader builds (anything but a menu kept
    by hand, manual_csv). The guard runs in main's checkout, so the restaurant.json read here is main's copy, not the
    pull request's. One that can't be read counts as reader-built: the narrower limit."""
    m = SCAN_REF.fullmatch(ref)
    config = (root or ROOT) / "restaurants" / (m[1] if m else "") / "restaurant.json"
    if not m or not config.is_file():
        return False
    try:
        c = json.loads(config.read_text(encoding="utf-8"))
        return bool(c.get("readers")) or c.get("reader") != "manual_csv"
    except (ValueError, AttributeError):
        return True


def scope(ref, paths, machine=False, reader_built=False):
    """What's wrong with a pull request from branch ref changing these paths: a list of problems, empty if fine.
    machine: one of its commits was made by the routine or a workflow.
    reader_built: main already has the restaurant a scan/ branch names, built by a reader."""
    # the prefix is read whatever its case, so "Scan/x" can't step round the limits below (the owner's own branches,
    # such as city-requests, have no slash after the word)
    kind = next((k for k in AUTOMATED if re.match(rf"{k}/", ref, re.I)), None)
    if kind and not ref.startswith(kind + "/"):
        return [f"branch {ref!r} looks like a {kind}/ branch but isn't named exactly {kind}/<id>-...; rename it"]
    if kind == "scan":
        # the restaurant the branch names, and only that one
        m = SCAN_REF.fullmatch(ref)
        if not m:
            return [f"a scan/ branch is named scan/<id>-<YYYY-MM-DD>, not {ref!r}"]
        if reader_built:
            # a restaurant a reader already builds: a new guide and the upload it came from, nothing else. Its
            # restaurant.json holds the reader's name and avoidDropOk, which switches off the build's Avoid guard
            inside = (f"restaurants/{m[1]}/guides/", f"restaurants/{m[1]}/source/")
            outside = sorted(p for p in paths if not p.startswith(inside))
            return [f"a scan/ pull request for {m[1]}, which a reader builds, may change only restaurants/{m[1]}/guides/ and "
                    f"restaurants/{m[1]}/source/, not {', '.join(outside)}. A reader fix, a snapshot, restaurant.json or "
                    "avoidDropOk goes in a pull request of your own, merged first"] if outside else []
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
        # which city is read from the name too: one_city() holds the pull request to that entry
        if not CITY_REF.fullmatch(ref):
            return [f"a {kind}/ branch is named {kind}/<id>-<YYYY-MM-DD>, not {ref!r}"]
        outside = sorted(set(paths) - CITY_FILES)
        return [f"a {kind}/ pull request may change only site/cities.json, not {', '.join(outside)}"] if outside else []
    if machine:
        return [f"branch {ref!r} carries a commit made by the routine or a workflow, so it must be a scan/, city/, recheck/ or "
                "guide-watch/ branch and keep to that branch's files. If the work is your own, make the commits yourself"]
    return []


def one_city(kind, cid, base, head):
    """What's wrong with a city/ or recheck/ pull request for city cid, given site/cities.json where the branch left
    main (base) and at the pull request's head, both parsed: a list of problems, empty if fine. Every other city must
    be as it was; a city/ branch adds cid, a recheck/ branch changes one that's already there."""
    if not isinstance(base, dict) or not isinstance(head, dict):
        return ["site/cities.json isn't a list of cities by id"]
    problems = []
    others = sorted(k for k in set(base) | set(head) if k != cid and (k not in base or k not in head or base[k] != head[k]))
    if others:
        problems.append(f"a {kind}/ pull request for {cid} may change only that city's entry in site/cities.json, not "
                        + ", ".join(others))
    if cid not in head:
        problems.append(f"a {kind}/ pull request for {cid} has no {cid} in site/cities.json (the branch is named for the city's id)")
    elif kind == "city" and cid in base:
        problems.append(f"{cid} is already in site/cities.json: a city/ branch adds a new city, and a recheck/ branch changes one")
    elif kind == "recheck" and cid not in base:
        problems.append(f"{cid} isn't in site/cities.json yet: a recheck/ branch changes a city that's there, and a city/ branch adds one")
    return problems


def cities_of(pr):
    """site/cities.json where the pull request's branch left its base branch (the merge base, so a city merged to main
    since then doesn't count against it) and at the pull request's head: (base, head), parsed. Read through the API."""
    pull = gh.request("GET", f"/pulls/{pr}")
    head, base_ref = pull["head"]["sha"], pull["base"]["ref"]
    fork = gh.request("GET", f"/compare/{base_ref}...{head}?per_page=1")["merge_base_commit"]["sha"]
    return tuple(gh.request("GET", f"/contents/site/cities.json?ref={sha}", accept="application/vnd.github.raw+json")
                 for sha in (fork, head))


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
    """The pull request's commits as GitHub lists them. It lists 250 at most, so a pull request that long is refused
    rather than judged on the part that can be seen."""
    out = []
    for page in range(1, pages + 1):
        batch = gh.request("GET", f"/pulls/{pr}/commits?per_page=100&page={page}")
        out += batch
        if len(batch) < 100:
            break
    if len(out) >= 250:
        raise SystemExit("ERROR: more commits than the guard can read (250); split the pull request")
    return out


def from_other_repo(pull, repo):
    """A pull request from someone else's copy of the repository (a fork): checks.yml runs its own copy of the tools, so
    it could loosen them, and it isn't the owner's work whatever its commits say. A deleted fork has no head repo."""
    head = (pull.get("head") or {}).get("repo") or {}
    if head.get("full_name") == repo:
        return []
    return [f"this pull request comes from {head.get('full_name') or 'a deleted copy'}, not from {repo}. Only branches "
            "of this repository are merged here; copy a change you want onto a branch of your own"]


def avoid_ok_changed(rid, base, head):
    """What's wrong with a scan/ pull request for a menu kept by hand, given its restaurant.json on main (base) and at
    the pull request's head, both parsed: it may change the guide's dates, but not avoidDropOk, which switches off the
    build's Avoid guard (tools/build.py avoid_drop) for the very menu it brings. The build accepts a drop when
    avoidDropOk equals the menu's source (adapters/manual_csv.py: guide.source, else the file's name, menu.csv), so
    renaming the source to match an avoidDropOk already on main counts as switching the guard off too."""
    base, head = base or {}, head or {}
    # the source rule below is manual_csv's, so which reader builds it may not change here either
    if any(base.get(k) != head.get(k) for k in ("reader", "readers")):
        return [f"a scan/ pull request for {rid} may not change which reader builds it (reader or readers in "
                f"restaurants/{rid}/restaurant.json): that goes in a pull request of your own"]
    source = lambda c: (c.get("guide") or {}).get("source") or "menu.csv"
    ok = head.get("avoidDropOk")
    if ok == base.get("avoidDropOk") and not (ok and source(head) != source(base) and ok == source(head)):
        return []
    return [f"a scan/ pull request for {rid} may not change avoidDropOk in restaurants/{rid}/restaurant.json, or rename "
            "the menu's source to the one avoidDropOk names: if the change to the Avoid list is real, set it in a pull "
            "request of your own, merged first"]


def main():
    ref = os.environ["HEAD_REF"]
    pull = gh.request("GET", f"/pulls/{os.environ['PR']}")
    problems = from_other_repo(pull, os.environ["GITHUB_REPOSITORY"])
    for p in problems:
        print("GUARD:", p)
    if problems:
        sys.exit(1)
    paths, built = changed(os.environ["PR"]), reader_built(ref)
    problems = scope(ref, paths, machine_made(commits(os.environ["PR"])), built)
    scan = SCAN_REF.fullmatch(ref)
    rj = f"restaurants/{scan[1]}/restaurant.json" if scan else None
    # only for a restaurant main already has: a new one has no live menu for the Avoid guard to protect
    if scan and not built and not problems and rj in paths and (ROOT / rj).is_file():
        # main's copy is this checkout's (the guard runs from main); the pull request's is read through the API
        base = json.loads((ROOT / rj).read_text(encoding="utf-8"))
        head = gh.request("GET", f"/contents/{rj}?ref={pull['head']['sha']}", accept="application/vnd.github.raw+json")
        problems = avoid_ok_changed(scan[1], base, head)
    city = CITY_REF.fullmatch(ref)
    if city and not problems:
        problems = one_city(city[1], city[2], *cities_of(os.environ["PR"]))
    for p in problems:
        print("GUARD:", p)
    if problems:
        sys.exit(1)
    print(f"guard: {ref} changes only what it may")


if __name__ == "__main__":
    main()
