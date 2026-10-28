"""
GitHub's API for the tools that open pull requests and issues (watch_guides, reminders, upload_notice).

Reads GITHUB_TOKEN and GITHUB_REPOSITORY from the environment, and GITHUB_API_URL where set (the tests point it
at a fake). Nothing here merges anything.
"""
import json
import os
import urllib.request


def request(method, path, body=None):
    """One call to /repos/<repository><path>, answered as JSON (None for an empty answer)."""
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    req = urllib.request.Request(
        f"{api}/repos/{os.environ['GITHUB_REPOSITORY']}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read() or "null")


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
