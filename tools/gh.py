"""
GitHub's API for the tools that open pull requests and issues (watch_guides, reminders, upload_notice).

Reads GITHUB_TOKEN and GITHUB_REPOSITORY from the environment, and GITHUB_API_URL where set (the tests point it
at a fake). Nothing here merges anything.
"""
import json
import os
import re
import urllib.request


def request(method, path, body=None, accept="application/vnd.github+json"):
    """One call to /repos/<repository><path>, answered as JSON (None for an empty answer). accept: GitHub's media
    type; the raw one gives a JSON file's own contents instead of GitHub's wrapping of it."""
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    req = urllib.request.Request(
        f"{api}/repos/{os.environ['GITHUB_REPOSITORY']}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": accept,
                 "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read() or "null")


def quoted(text):
    """Text from another site (a reader's message, a dish's name, build output) as it goes into a pull request or an
    issue: one line with no backticks, so it can't end a code span or a code fence and turn into markdown, links or
    instructions. A new line, even a single one, can start a list item or heading before a code span is read."""
    return re.sub(r"\s*[\r\n]\s*", " ", str(text)).replace("`", "'")


def link(url):
    """An address from another site as a plain autolink (<https://…>): nothing in it can become markdown. A control
    character would stop it being an autolink, and the rest would then be read as markdown, so those go too."""
    return "<" + re.sub(r"[\x00-\x20\x7f\s<>`]", "", str(url)) + ">"


BOT = "github-actions[bot]"


def issue_titles(state="all", pages=10):
    """The titles of the issues (pull requests included, as GitHub lists them) that the workflows opened. Only theirs:
    anyone can open an issue on a public repository, and one copying a title mustn't stop the real one opening."""
    titles = set()
    for page in range(1, pages + 1):
        batch = request("GET", f"/issues?state={state}&per_page=100&page={page}")
        titles |= {i["title"] for i in batch if (i.get("user") or {}).get("login") == BOT}
        if len(batch) < 100:
            break
    return titles
