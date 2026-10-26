#!/usr/bin/env python3
"""
Make sure the release number goes up whenever the app's own code changes.

Phones only pick up new app code when the service worker (site/sw.js) changes,
and the app reloads itself for a new release (see "new app code without a
restart" in site/app.js). So a pull request that changes the app's code must
raise CACHE in site/sw.js, and APP_VERSION in site/app.js with it (check.py
holds the two equal). Menus, cities and phrases don't need it: they're always
checked for a newer copy.

Usage (in the pull request check, after fetching the base branch):
  python tools/check_release.py FETCH_HEAD
  python tools/check_release.py origin/main
"""
import re
import subprocess
import sys

# the app's own files, plus the chains' logos: the service worker serves them from the release's saved copy, so a
# change to any of them reaches phones only with a new release
CODE = ["site/app.js", "site/compare.js", "site/theme.js", "site/styles.css", "site/index.html", "site/sw.js", "site/manifest.webmanifest",
        "site/icons", "site/vendor", "restaurants/*/logo.png"]
APP_VERSION = re.compile(r"const APP_VERSION = (\d+);")
CACHE = re.compile(r'const CACHE = "gf-menus-v(\d+)"')


def cache_number(text):
    """The release number in site/sw.js's text."""
    m = CACHE.search(text)
    if not m:
        raise SystemExit("ERROR: couldn't find CACHE in site/sw.js")
    return int(m.group(1))


def app_number(text):
    """The release number in site/app.js's text."""
    m = APP_VERSION.search(text)
    if not m:
        raise SystemExit("ERROR: couldn't find APP_VERSION in site/app.js")
    return int(m.group(1))


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    changed = subprocess.run(["git", "diff", "--name-only", base, "--", *CODE], capture_output=True, text=True, check=True).stdout.split()
    if not changed:
        print("release: no app code changed")
        return
    old = cache_number(subprocess.run(["git", "show", f"{base}:site/sw.js"], capture_output=True, text=True, check=True).stdout)
    with open("site/sw.js", encoding="utf-8") as f:
        new = cache_number(f.read())
    if new <= old:
        raise SystemExit(f"ERROR: {', '.join(changed)} changed but the release is still {new}. Raise CACHE in site/sw.js "
                         f"and APP_VERSION in site/app.js to {old + 1}, so phones load the new code.")
    print(f"release: {old} -> {new} for {', '.join(changed)}")


if __name__ == "__main__":
    main()
