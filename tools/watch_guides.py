#!/usr/bin/env python3
"""
Spot a new allergen guide on a restaurant's own website and propose it as a pull request.

A restaurant.json can say where the restaurant links its guide:
  "watch": {"page": "https://…", "link": "a pattern the guide's link matches"}
Each week this opens that page, downloads every PDF it links whose address matches, and compares each file's
fingerprint (sha256) with the guides already in guides/ and guides/archive/. A file it hasn't seen is tried with the
restaurant's reader: if the reader would build the menu from it, it's a new guide. Older editions still linked from the
page (Starbucks keeps last season's) are left alone, because the readers go by the date printed in each guide.

Each restaurant with a new guide gets a branch and a pull request: the new PDF in guides/, the one it replaces moved
to guides/archive/, and what changed according to the build. The usual checks run on it (started here, because a pull
request opened with the workflow's own token doesn't start them). Nothing is ever merged automatically. A page that
can't be checked (blocked, moved, no guide link) gets an issue instead, and so does a new guide for a restaurant whose
menu is kept by hand (manual_csv).

That runs in two steps, so the token that can push never sits beside a PDF from another site (V14):
  --plan DIR     reads the websites and the PDFs and builds each new guide, with no GitHub token; it saves what to
                 propose in DIR/plan.json and the new PDFs in DIR/<restaurant>/
  --propose DIR  opens the pull requests and issues saved in DIR; it reads no website and no PDF, and checks what the
                 plan says against this checkout, since the step that wrote it read other sites' files

Usage:
  python tools/watch_guides.py                  # report only; changes nothing
  python tools/watch_guides.py --plan DIR       # run tools/fetch_previous.py first
  python tools/watch_guides.py --propose DIR    # needs GITHUB_TOKEN and GITHUB_REPOSITORY
  python tools/watch_guides.py pret-uk          # only these restaurants (with --plan, or alone)
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
from gh import link, quoted  # noqa: E402

UA = "Mozilla/5.0 (compatible; gf-drinks guide watch; +https://github.com/T-800IsInevitable/gf-drinks)"
PAGE_LIMIT = 5_000_000
PDF_LIMIT = 60_000_000
RETRY_AFTER = 30
SCHEMES = ("https",)  # a guide is downloaded over https only (the tests add http for the website they serve themselves)
HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
BARE_PDF = re.compile(r"""https?://[^\s"'<>\\]+?\.pdf\b""", re.I)
WORKFLOW = "_Opened automatically by `.github/workflows/guide-watch.yml` (`tools/watch_guides.py`)._"


def get(url, limit, retry=True):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            if urllib.parse.urlsplit(res.geturl()).scheme not in SCHEMES:  # the address it ended at, redirects followed
                raise ValueError("not an https address")
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


def guide_links(page_html, page_url, pattern, refused=None):
    """Every PDF the page links whose (decoded) address matches the pattern, in page order. Also PDF addresses written
    anywhere in the page, for sites that build their links in JavaScript (PizzaExpress). Only https ones (SCHEMES):
    a matching link over plain http is left out, and added to the refused list when one is given."""
    out, seen = [], set()
    for h in HREF.findall(page_html) + BARE_PDF.findall(page_html.replace("\\/", "/")):
        url = urllib.parse.urljoin(page_url, html.unescape(h).strip())
        parts = urllib.parse.urlsplit(url)
        decoded = urllib.parse.unquote(url)
        bare = parts._replace(query="", fragment="").geturl()  # the same file, written with and without its query
        if parts.scheme in ("http", "https") and parts.path.lower().endswith(".pdf") and re.search(pattern, decoded, re.I):
            if bare not in seen:
                seen.add(bare)
                if parts.scheme in SCHEMES:
                    out.append(url)
                elif refused is not None:
                    refused.append(url)
    return out


def file_name(url):
    """The guide's own file name, tidied for the repository."""
    name = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
    # no dot or dash first (a hidden file, or one read as an option), and .pdf in small letters, as GUIDE_NAME expects
    name = re.sub(r"[^A-Za-z0-9._-]", "", re.sub(r"\s+", "_", name))
    stem = (name[:-4] if name.lower().endswith(".pdf") else name).lstrip(".-")
    return (stem or "guide") + ".pdf"


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
    refused = []
    links = guide_links(body.decode("utf-8", "replace"), page_url, watch["link"], refused)
    result["problems"] += [f"{url} is linked over http, not https, so it wasn't downloaded. Fetch it by hand." for url in refused]
    if not links and refused:
        return result
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
    """Build this restaurant with the new guide and say what changed since the live menu (tools/changes.py): the build's
    last lines if it failed, else its summary and what's now on the Avoid list. Plain text, quoted by changed_text."""
    run = subprocess.run([sys.executable, str(ROOT / "tools" / "build.py"), rid], cwd=ROOT, capture_output=True, text=True)
    if run.returncode:
        return {"failed": (run.stdout + run.stderr).strip().splitlines()[-15:]}
    built = json.loads((ROOT / "site" / "data" / "r" / f"{rid}.json").read_text(encoding="utf-8"))
    c = built.get("changes")
    return {"summary": changes.summary(c), "nowAvoid": [x["name"] + " (" + x["section"] + ")" for x in (c or {}).get("nowAvoid") or []]}


def changed_text(c):
    """what_changed as it goes into the pull request. It comes from the step that read the PDF, so every line is quoted
    here, and anything not shaped as what_changed writes it counts as nothing said."""
    if not isinstance(c, dict):
        return "**What changed:** see the **Menu build** summary on the checks."
    if "failed" in c:
        tail = "\n".join(quoted(x) for x in list(c["failed"] or [])[-15:])  # lines, inside a fence
        return ("**The build couldn't read it**, so the checks will fail and the live menus stay as they are until the reader "
                "is updated for it. That fix (the reader, its snapshot, or `avoidDropOk` in `restaurant.json`) goes in a pull "
                "request of your own, merged first: the guard lets this branch change only the guides. Then re-run this "
                f"pull request's checks.\n\n```\n{tail}\n```")
    # dish names come from the PDF: in code spans, where nothing in them can become a link, a mention or emphasis
    text = f"**What changed, from the build:** `{quoted(c.get('summary', ''))}`."
    if c.get("nowAvoid"):
        text += "\n\n**Now on the Avoid list (contain gluten):** " + ", ".join(f"`{quoted(x)}`" for x in c["nowAvoid"]) + "."
    return text


def trial_build(r):
    """Build the restaurant with its new guides in place, as its pull request will have them, then put the folder back."""
    guides = ROOT / "restaurants" / r["id"] / "guides"
    archive = guides / "archive"
    made, moved, written = not archive.exists(), [], []
    try:
        archive.mkdir(exist_ok=True)
        # each new guide is tried on its own, so two can replace the same old one: move each old guide once
        for old in sorted({old for u in r["new"] for old in u.get("replaces", [])}):
            if (archive / old).exists():
                raise SystemExit(f"ERROR: {old} is already in guides/archive/, so it can't be moved there")
            shutil.move(guides / old, archive / old)
            moved.append(old)
        for u in r["new"]:
            (guides / u["name"]).write_bytes(u["body"])
            written.append(guides / u["name"])
        return what_changed(r["id"])
    finally:
        for f in written:
            f.unlink(missing_ok=True)
        for old in moved:
            shutil.move(archive / old, guides / old)
        if made and not any(archive.iterdir()):
            archive.rmdir()


GUIDE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*\.pdf\Z")  # as file_name makes them: no folder, no dot or dash first


def from_plan(e, plan_dir):
    """One restaurant's entry in the plan, as the pull request or issue will use it. The step that wrote the plan read
    other sites' files, so nothing in it is taken on trust: the restaurant must be one here, its name and page come from
    this checkout, each new file must be a PDF the restaurant doesn't have yet under a plain new name, and each guide it
    replaces must be one in use. Anything else stops this restaurant (ValueError), so nothing of it is pushed."""
    folders = {p.name: p for p in (ROOT / "restaurants").iterdir() if (p / "restaurant.json").exists()}
    rid = e.get("id") if isinstance(e, dict) else None
    if rid not in folders:
        raise ValueError(f"the plan names {quoted(rid)!r}, which isn't a restaurant here")
    folder = folders[rid]
    config = json.loads((folder / "restaurant.json").read_text(encoding="utf-8"))
    if "watch" not in config:
        raise ValueError(f"{rid} isn't watched")
    have, in_use = known(folder), {p.name for p in (folder / "guides").glob("*.pdf")}
    taken = {p.name for p in (folder / "guides").rglob("*")}
    new = []
    for u in e.get("new") or []:
        name, url, replaces = str(u.get("name")), str(u.get("url")), [str(x) for x in u.get("replaces") or []]
        if not GUIDE_NAME.match(name) or name in taken or any(n["name"] == name for n in new):
            raise ValueError(f"{quoted(name)!r} isn't a new guide's file name")
        body = (plan_dir / rid / name).read_bytes()
        if not body.startswith(b"%PDF-") or fingerprint(body) in have:
            raise ValueError(f"{name} isn't a PDF this restaurant doesn't have yet")
        if not set(replaces) <= in_use:
            raise ValueError(f"{name} replaces a guide that isn't in use")
        # the address must be one the page check would have downloaded: https, a PDF, matching the restaurant's pattern
        parts = urllib.parse.urlsplit(url)
        if (parts.scheme not in SCHEMES or not parts.path.lower().endswith(".pdf")
                or not re.search(config["watch"]["link"], urllib.parse.unquote(url), re.I)):
            raise ValueError(f"{name} doesn't come from an address the restaurant's page links")
        new.append({"name": name, "url": url, "sha": fingerprint(body), "body": body, "replaces": replaces,
                    **({"unreadable": str(u["unreadable"])} if u.get("unreadable") else {})})
    return {"id": rid, "name": config.get("name", rid), "page": config["watch"]["page"], "new": new,
            "manual": config.get("reader") == "manual_csv", "problems": [str(p) for p in e.get("problems") or []],
            "changed": e.get("changed"), "crash": None if e.get("crash") is None else str(e["crash"])}


def source(url, page):
    """Where a guide came from, as a pull request or issue shows it: a link only on the restaurant's own site (the page
    in this checkout's restaurant.json). Elsewhere, such as a file host, it's text that can't be clicked, since the
    address came from the step that read other sites' files."""
    if urllib.parse.urlsplit(str(url)).hostname == urllib.parse.urlsplit(str(page)).hostname:
        return link(url)
    return f"`{quoted(url)}`, on another site"


def pr_body(r, changed):
    lines = [f"**{r['name']}** has a new allergen guide on its website ({r['page']}).", ""]
    for u in r["new"]:
        lines.append(f"- New: `{u['name']}` (as published: {source(u['url'], r['page'])})")
        for old in u.get("replaces", []):
            lines.append(f"  - It replaces `{quoted(old)}`, which moves to `guides/archive/`.")
        if u.get("unreadable"):
            lines.append(f"  - The reader stopped on it: `{quoted(u['unreadable'])}`")
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
            # each new guide is tried on its own, so two can replace the same old one: move each old guide once
            for old in sorted({old for u in r["new"] for old in u.get("replaces", [])}):
                (guides / "archive").mkdir(exist_ok=True)
                git("mv", str(guides / old), str(guides / "archive" / old))
            for u in r["new"]:
                (guides / u["name"]).write_bytes(u["body"])
            changed = changed_text(r.get("changed"))
            git("add", "-A", str(guides))
            git("-c", "user.name=github-actions[bot]", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "commit", "-q", "-m", f"New {r['name']} allergen guide: " + ", ".join(u["name"] for u in r["new"]))
            git("push", "-q", "origin", branch)
        finally:
            git("switch", "-q", "-f", *back)
            git("branch", "-D", branch)
    else:
        changed = changed_text(None)
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
            + "\n".join(f"- `{quoted(p)}`" for p in r["problems"]) +
            f"\n\nUntil it can, look for a new guide by hand ({r['page']}); the guide reminders still say when the one in "
            "the app is due to end. If the restaurant moved its guide, update `watch` in "
            f"`{folder}restaurant.json`. If its site blocks the check for good, remove `watch` there and keep checking by hand. "
            "Close this issue once it's sorted; it opens again if the next check fails too.\n\n" + WORKFLOW)


def crash_issue(name, page, what):
    """The watch itself stopped on a restaurant (a reader that failed, a refused pull request): its own title, so an
    open "couldn't check" issue for the same restaurant doesn't swallow it, and its own advice."""
    return (f"Guide watch: stopped on {name}",
            f"The weekly guide watch stopped while checking **{name}** ({page}):\n\n- `{quoted(what)}`\n\nThe other "
            "restaurants were still checked. This is the watch's own failure, not a moved page: read the run's log (the "
            "Actions tab) and fix the cause, or look for a new guide by hand until it's fixed. Close this issue once "
            "it's sorted; it opens again if the next run stops too.\n\n" + WORKFLOW)


def manual_issue(r):
    folder = f"restaurants/{r['id']}/"
    names = ", ".join(u["name"] for u in r["new"])
    return (f"Guide watch: new {r['name']} guide ({names})",
            f"**{r['name']}** links a guide the app hasn't seen before:\n\n"
            + "\n".join(f"- `{u['name']}`: {source(u['url'], r['page'])}" for u in r["new"]) +
            f"\n\nIts menu is kept by hand, so read the guide and update `{folder}menu.csv` and the dates in "
            f"`{folder}restaurant.json`, adding the PDF to `{folder}guides/`. If it isn't actually newer, close this issue.\n\n"
            + WORKFLOW)


def main():
    ap = argparse.ArgumentParser(description="Look for new allergen guides on the restaurants' own websites.")
    ap.add_argument("ids", nargs="*", help="only these restaurants")
    step = ap.add_mutually_exclusive_group()
    step.add_argument("--plan", type=Path, metavar="DIR", help="also build each new guide, and save what to propose in DIR")
    step.add_argument("--propose", type=Path, metavar="DIR", help="open the pull requests and issues saved in DIR by --plan")
    args = ap.parse_args()
    if args.propose:
        return propose_plan(args.propose)
    if args.plan:
        args.plan.mkdir(parents=True, exist_ok=True)
    folders = sorted(p for p in (ROOT / "restaurants").iterdir()
                     if (p / "restaurant.json").exists() and not p.name.startswith(("_", "."))
                     and (not args.ids or p.name in args.ids))
    plan = []
    for folder in folders:
        # one restaurant's failure (a broken page, a reader that stops) mustn't leave the restaurants after it unchecked:
        # it goes in the plan, so --propose opens an issue for it and fails the run at the end
        try:
            entry = watch_one(folder, args.plan)
        except (Exception, SystemExit) as e:
            what = why(e) if isinstance(e, Exception) else str(e)
            print(f"{folder.name}: FAILED ({what})")
            entry = {"id": folder.name, "crash": what}
        if entry:
            plan.append(entry)
    if args.plan:
        (args.plan / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
        print(f"plan saved in {args.plan}: {len(plan)} restaurant(s) to act on")
    elif any(e.get("crash") for e in plan):
        raise SystemExit("ERROR: the guide watch stopped on " + ", ".join(e["id"] for e in plan if e.get("crash")))


def watch_one(folder, plan_dir=None):
    """Check one restaurant's page. With plan_dir, save its new PDFs there and return what to propose for it, if any."""
    if "watch" not in json.loads((folder / "restaurant.json").read_text(encoding="utf-8")):
        print(f"{folder.name}: not watched")
        return None
    r = check(folder)
    new = ", ".join(u["name"] + (" (the reader stopped on it)" if u.get("unreadable") else "") for u in r["new"])
    print(f"{r['name']}: " + (f"new guide {new}" if new else "nothing new"))
    for line in r["ignored"]:
        print(f"  left alone: {line}")
    for p in r["problems"]:
        print(f"  PROBLEM: {p}")
    if plan_dir is None or not (r["new"] or r["problems"]):
        return None
    for u in r["new"]:
        (plan_dir / r["id"]).mkdir(parents=True, exist_ok=True)
        (plan_dir / r["id"] / u["name"]).write_bytes(u["body"])
    return {"id": r["id"], "problems": r["problems"], "changed": trial_build(r) if r["new"] and not r["manual"] else None,
            "new": [{k: u[k] for k in ("name", "url", "replaces", "unreadable") if k in u} for u in r["new"]]}


def propose_plan(plan_dir):
    """Open the pull requests and issues the plan asks for. Reads no website and no PDF (the plan's step did that)."""
    plan = json.loads((plan_dir / "plan.json").read_text(encoding="utf-8"))
    if not isinstance(plan, list):
        raise SystemExit("ERROR: the plan isn't a list, so the step that wrote it went wrong")
    existing = open_issues()
    failed, done = [], set()
    for e in plan:
        rid = e.get("id") if isinstance(e, dict) else None
        try:
            if rid in done:
                raise ValueError(f"{quoted(rid)} is in the plan twice")
            done.add(rid)
            r = from_plan(e, plan_dir)
        except (Exception, SystemExit) as err:  # a plan this checkout doesn't agree with: nothing of it is used
            what = "its plan was refused: " + (why(err) if isinstance(err, Exception) else str(err))
            failed.append(quoted(rid))
            print(f"{quoted(rid)}: {what}")
            # a restaurant here gets an issue, named and linked from this checkout; anything else only fails the run
            folder = ROOT / "restaurants" / str(rid)
            if isinstance(rid, str) and rid in {p.name for p in (ROOT / "restaurants").iterdir()} and (folder / "restaurant.json").exists():
                try:
                    config = json.loads((folder / "restaurant.json").read_text(encoding="utf-8"))
                    issue(*crash_issue(config.get("name", rid), (config.get("watch") or {}).get("page", ""), what), existing)
                except Exception as e2:
                    print(f"  couldn't open an issue for it ({why(e2)})")
            continue
        try:
            if r["crash"] is not None:
                raise SystemExit(r["crash"])
            if r["new"]:
                if r["manual"]:
                    issue(*manual_issue(r), existing)
                else:
                    propose(r)
            if r["problems"]:
                issue(*problem_issue(r), existing)
        except (Exception, SystemExit) as err:
            # the watch stopped on it (while checking, or here with a refused pull request): an issue of its own
            failed.append(r["id"])
            what = why(err) if isinstance(err, Exception) else str(err)
            print(f"{r['id']}: FAILED ({what})")
            try:
                issue(*crash_issue(r["name"], r["page"], what), existing)
            except Exception as e2:  # the issue itself failed: the run's own failure still reports it
                print(f"  couldn't open an issue for it ({why(e2)})")
    if failed:
        raise SystemExit(f"ERROR: the guide watch stopped on {', '.join(failed)}; the other restaurants were checked")


if __name__ == "__main__":
    main()
