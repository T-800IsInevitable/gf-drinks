#!/usr/bin/env python3
"""
Spot a new allergen guide on a restaurant's own website and propose it as a pull request.

A restaurant.json can say where the restaurant links its guide:
  "watch": {"page": "https://…", "link": "a pattern the guide's link matches"}
Each week this opens that page, downloads every PDF it links whose address matches, and compares each file's
fingerprint (sha256) with the guides already in guides/ and guides/archive/. A file it hasn't seen is tried with the
restaurant's reader: if the reader would build the menu from it, it's a new guide. Older editions still linked from the
page (Starbucks keeps last season's) are left alone, because the readers go by the date printed in each guide.

With --github, each restaurant with a new guide gets a branch and a pull request: the new PDF in guides/, the one it
replaces moved to guides/archive/, and what changed according to the build. The usual checks run on it (started here,
because a pull request opened with the workflow's own token doesn't start them). Nothing is ever merged automatically.
A page that can't be checked (blocked, moved, no guide link) gets an issue instead, and so does a new guide for a
restaurant whose menu is kept by hand (manual_csv).

Usage:
  python tools/watch_guides.py                  # report only; changes nothing
  python tools/watch_guides.py --github         # also open pull requests and issues
                                                # (needs GITHUB_TOKEN and GITHUB_REPOSITORY; run tools/fetch_previous.py first)
  python tools/watch_guides.py pret-uk          # only these restaurants
"""
import argparse
import contextlib
import hashlib
import html
import importlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import changes  # noqa: E402
import gh  # noqa: E402

UA = "Mozilla/5.0 (compatible; gf-drinks guide watch; +https://github.com/T-800IsInevitable/gf-drinks)"
PAGE_LIMIT = 5_000_000
PDF_LIMIT = 60_000_000
RETRY_AFTER = 30
HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
BARE_PDF = re.compile(r"""https?://[^\s"'<>\\]+?\.pdf\b""", re.I)
WORKFLOW = "_Opened automatically by `.github/workflows/guide-watch.yml` (`tools/watch_guides.py`)._"


def get(url, limit, retry=True):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            body = res.read(limit + 1)
            if len(body) > limit:
                raise ValueError(f"larger than {limit // 1_000_000} MB")
            return body, res.geturl()
    except urllib.error.HTTPError as e:
        if not (retry and (e.code == 429 or e.code >= 500)):
            raise
    except urllib.error.URLError:
        if not retry:
            raise
    time.sleep(RETRY_AFTER)  # busy, or a passing fault: once more, politely, before calling it a problem
    return get(url, limit, retry=False)


def why(e):
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, urllib.error.URLError):
        return f"no answer: {e.reason}"
    return str(e) or e.__class__.__name__


def guide_links(page_html, page_url, pattern):
    """Every PDF the page links whose (decoded) address matches the pattern, in page order. Also PDF addresses written
    anywhere in the page, for sites that build their links in JavaScript (PizzaExpress)."""
    out, seen = [], set()
    for h in HREF.findall(page_html) + BARE_PDF.findall(page_html.replace("\\/", "/")):
        url = urllib.parse.urljoin(page_url, html.unescape(h).strip())
        parts = urllib.parse.urlsplit(url)
        decoded = urllib.parse.unquote(url)
        bare = parts._replace(query="", fragment="").geturl()  # the same file, written with and without its query
        if parts.scheme in ("http", "https") and parts.path.lower().endswith(".pdf") and re.search(pattern, decoded, re.I):
            if bare not in seen:
                seen.add(bare)
                out.append(url)
    return out


def file_name(url):
    """The guide's own file name, tidied for the repository."""
    name = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
    name = re.sub(r"[^A-Za-z0-9._-]", "", re.sub(r"\s+", "_", name)) or "guide.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def fingerprint(body):
    return hashlib.sha256(body).hexdigest()


def known(folder):
    """Fingerprints of every guide the repository already has for this restaurant, archived ones included."""
    return {fingerprint(p.read_bytes()): p for p in (folder / "guides").rglob("*") if p.suffix.lower() == ".pdf"}


def readers_of(config):
    return config.get("readers") or ([config["reader"]] if config.get("reader") else [])


def picks(folder, config, extra=()):
    """The guide each reader would build the menu from (its own newest_pdf: by the date printed in each guide), among
    the folder's guides plus the extra (name, body) files. A reader that stops on a file gives the reason instead."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        guides = Path(tmp)
        for f in (folder / "guides").glob("*.pdf"):
            shutil.copy2(f, guides / f.name)
        for name, body in extra:
            (guides / name).write_bytes(body)
        out = {}
        for reader in readers_of(config):
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    out[reader] = importlib.import_module(f"adapters.{reader}").newest_pdf(guides).name
            except (SystemExit, Exception) as e:  # stopped by the reader, or a PDF it can't open
                out[reader] = str(e) or e.__class__.__name__
        return out


def check(folder):
    """What the restaurant's page links now: new guides (each with what it replaces), ones left alone, and problems."""
    config = json.loads((folder / "restaurant.json").read_text(encoding="utf-8"))
    watch = config["watch"]
    result = {"id": folder.name, "name": config.get("name", folder.name), "page": watch["page"], "new": [], "ignored": [],
              "problems": [], "manual": config.get("reader") == "manual_csv"}
    try:
        body, page_url = get(watch["page"], PAGE_LIMIT)
    except Exception as e:
        result["problems"].append(f"Couldn't open {watch['page']} ({why(e)}).")
        return result
    links = guide_links(body.decode("utf-8", "replace"), page_url, watch["link"])
    if not links:
        result["problems"].append(f"No link matching `{watch['link']}` on {watch['page']}. The page may have changed.")
        return result
    have = known(folder)
    taken = {p.name for p in (folder / "guides").rglob("*")}
    unseen = []
    for url in links:
        try:
            pdf, _ = get(url, PDF_LIMIT)
        except Exception as e:
            result["problems"].append(f"Couldn't download {url} ({why(e)}).")
            continue
        if not pdf.startswith(b"%PDF-"):
            result["problems"].append(f"{url} isn't a PDF.")
            continue
        sha = fingerprint(pdf)
        if sha in have or any(sha == u["sha"] for u in unseen):
            continue
        name = file_name(url)
        if name in taken:
            name = name[:-4] + "_" + sha[:8] + ".pdf"
        taken.add(name)
        unseen.append({"url": url, "name": name, "sha": sha, "body": pdf})
    if not unseen:
        return result
    if result["manual"]:  # a menu kept by hand: say so, there's no reader to try it with
        result["new"] = unseen
        return result
    before = picks(folder, config)
    names = {p.name for p in (folder / "guides").glob("*.pdf")}
    for u in unseen:
        after = picks(folder, config, [(u["name"], u["body"])])
        used = [r for r, s in after.items() if s == u["name"]]
        failed = [r for r, s in after.items() if s not in names and s != u["name"] and before.get(r) in names]
        if used:
            u["replaces"] = sorted({before[r] for r in used if before.get(r) in names})
            result["new"].append(u)
        elif failed:  # the reader stopped on it: maybe a new layout. Propose it anyway, so the pull request shows why
            u["replaces"], u["unreadable"] = [], "; ".join(after[r] for r in failed)
            result["new"].append(u)
        else:
            result["ignored"].append(f"{u['name']}: not newer than the guide in use")
    return result


# ---------- GitHub ----------
github = gh.request


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def branch_name(r):
    return f"guide-watch/{r['id']}-" + hashlib.sha256("".join(sorted(u["sha"] for u in r["new"])).encode()).hexdigest()[:10]


def what_changed(rid):
    """Build this restaurant with the new guide and say what changed since the live menu (tools/changes.py)."""
    run = subprocess.run([sys.executable, str(ROOT / "tools" / "build.py"), rid], cwd=ROOT, capture_output=True, text=True)
    if run.returncode:
        tail = "\n".join((run.stdout + run.stderr).strip().splitlines()[-15:])
        return ("**The build couldn't read it**, so the checks will fail and the live menus stay as they are until the reader "
                f"is updated for it:\n\n```\n{tail}\n```")
    built = json.loads((ROOT / "site" / "data" / "r" / f"{rid}.json").read_text(encoding="utf-8"))
    c = built.get("changes")
    text = f"**What changed, from the build:** {changes.summary(c)}."
    if c and c.get("nowAvoid"):
        text += "\n\n**Now on the Avoid list (contain gluten):** " + ", ".join(f"{x['name']} ({x['section']})" for x in c["nowAvoid"]) + "."
    return text


def pr_body(r, changed):
    lines = [f"**{r['name']}** has a new allergen guide on its website ({r['page']}).", ""]
    for u in r["new"]:
        lines.append(f"- New: `{u['name']}` ([as published]({u['url']}))")
        for old in u.get("replaces", []):
            lines.append(f"  - It replaces `{old}`, which moves to `guides/archive/`.")
        if u.get("unreadable"):
            lines.append(f"  - The reader stopped on it: {u['unreadable']}")
    lines += ["", changed, "",
              "Before merging, read the **Menu build** summary on the checks and look over what changed: the app shows it once "
              "this is merged. Nothing here merges by itself.", "",
              "If no checks show below, close this pull request and reopen it: that starts them.", "", WORKFLOW]
    return "\n".join(lines)


def propose(r):
    branch = branch_name(r)
    owner = os.environ["GITHUB_REPOSITORY"].split("/")[0]
    if github("GET", f"/pulls?state=all&head={owner}:{urllib.parse.quote(branch, safe='')}"):
        print(f"  pull request for {branch} already opened (it may have been closed); not opening another")
        return
    start = git("rev-parse", "--abbrev-ref", "HEAD")
    back = [start] if start != "HEAD" else ["--detach", git("rev-parse", "HEAD")]  # where to return to
    if not git("ls-remote", "--heads", "origin", branch):
        git("switch", "-c", branch)
        try:
            guides = ROOT / "restaurants" / r["id"] / "guides"
            for u in r["new"]:
                for old in u.get("replaces", []):
                    (guides / "archive").mkdir(exist_ok=True)
                    git("mv", str(guides / old), str(guides / "archive" / old))
                (guides / u["name"]).write_bytes(u["body"])
            changed = what_changed(r["id"])
            git("add", "-A", str(guides))
            git("-c", "user.name=github-actions[bot]", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "commit", "-q", "-m", f"New {r['name']} allergen guide: " + ", ".join(u["name"] for u in r["new"]))
            git("push", "-q", "origin", branch)
        finally:
            git("switch", "-q", "-f", *back)
            git("branch", "-D", branch)
    else:
        changed = "**What changed:** see the **Menu build** summary on the checks."
    made = github("POST", "/pulls", {"title": f"New {r['name']} allergen guide", "head": branch, "base": "main",
                                     "body": pr_body(r, changed)})
    print(f"  opened {made['html_url']}")
    # a pull request opened with the workflow's token doesn't start other workflows, so start the checks on it here
    github("POST", "/actions/workflows/checks.yml/dispatches", {"ref": branch})
    print("  started the checks on it")


def open_issues():
    return gh.issue_titles("open")


def issue(title, body, existing):
    if title in existing:
        print(f"  issue already open: {title}")
        return
    made = github("POST", "/issues", {"title": title, "body": body})
    existing.add(title)
    print(f"  opened {made['html_url']}")


def problem_issue(r):
    folder = f"restaurants/{r['id']}/"
    return (f"Guide watch: couldn't check {r['name']}",
            f"The weekly guide watch couldn't check **{r['name']}** for a new allergen guide:\n\n"
            + "\n".join(f"- {p}" for p in r["problems"]) +
            f"\n\nUntil it can, look for a new guide by hand ({r['page']}); the guide reminders still say when the one in "
            "the app is due to end. If the restaurant moved its guide, update `watch` in "
            f"`{folder}restaurant.json`. If its site blocks the check for good, remove `watch` there and keep checking by hand. "
            "Close this issue once it's sorted; it opens again if the next check fails too.\n\n" + WORKFLOW)


def manual_issue(r):
    folder = f"restaurants/{r['id']}/"
    names = ", ".join(u["name"] for u in r["new"])
    return (f"Guide watch: new {r['name']} guide ({names})",
            f"**{r['name']}** links a guide the app hasn't seen before:\n\n"
            + "\n".join(f"- [{u['name']}]({u['url']})" for u in r["new"]) +
            f"\n\nIts menu is kept by hand, so read the guide and update `{folder}menu.csv` and the dates in "
            f"`{folder}restaurant.json`, adding the PDF to `{folder}guides/`. If it isn't actually newer, close this issue.\n\n"
            + WORKFLOW)


def main():
    ap = argparse.ArgumentParser(description="Look for new allergen guides on the restaurants' own websites.")
    ap.add_argument("ids", nargs="*", help="only these restaurants")
    ap.add_argument("--github", action="store_true", help="open pull requests and issues")
    args = ap.parse_args()
    folders = sorted(p for p in (ROOT / "restaurants").iterdir()
                     if (p / "restaurant.json").exists() and not p.name.startswith(("_", "."))
                     and (not args.ids or p.name in args.ids))
    existing = open_issues() if args.github else set()
    for folder in folders:
        if "watch" not in json.loads((folder / "restaurant.json").read_text(encoding="utf-8")):
            print(f"{folder.name}: not watched")
            continue
        r = check(folder)
        new = ", ".join(u["name"] + (" (the reader stopped on it)" if u.get("unreadable") else "") for u in r["new"])
        print(f"{r['name']}: " + (f"new guide {new}" if new else "nothing new"))
        for line in r["ignored"]:
            print(f"  left alone: {line}")
        for p in r["problems"]:
            print(f"  PROBLEM: {p}")
        if not args.github:
            continue
        if r["new"]:
            if r["manual"]:
                issue(*manual_issue(r), existing)
            else:
                propose(r)
        if r["problems"]:
            issue(*problem_issue(r), existing)


if __name__ == "__main__":
    main()
