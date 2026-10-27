"""
The weekly guide watch (tools/watch_guides.py): finding a restaurant's guide link, telling a new guide from one the app
already has or an older edition, saying when a page can't be checked, and proposing a new guide as a pull request.
Runs against a small website served here and the real guides in restaurants/, so it needs no network.

Run: python -m unittest discover -s tests
"""
import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import watch_guides as w  # noqa: E402

SB = ROOT / "restaurants" / "starbucks-uk"
SUMMER_DRINKS = SB / "guides" / "archive" / "SUM2_26_UK_AllergenBook_CORE_BEVERAGE_v06.pdf"
AUTUMN_DRINKS = SB / "guides" / "AUT_26_UK_AllergenBook_CORE_BEVERAGE_v04.pdf"
AUTUMN_FOOD = SB / "guides" / "AUT_26_UK_AllergenBook_CORE_FOOD_v04.pdf"
PRET = next((ROOT / "restaurants" / "pret-uk" / "guides").glob("*.pdf"))
KNOOPS = next((ROOT / "restaurants" / "knoops-uk" / "guides").glob("*.pdf"))


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


class Site(unittest.TestCase):
    """A restaurant folder and its website, both made up for each test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.web = self.tmp / "web"
        self.web.mkdir()
        self.httpd, self.url = serve(functools.partial(Quiet, directory=str(self.web)))
        self.addCleanup(lambda: (self.httpd.shutdown(), self.httpd.server_close(), shutil.rmtree(self.tmp, ignore_errors=True)))
        patcher = mock.patch.object(w, "RETRY_AFTER", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def restaurant(self, rid, guides, link, reader=None, base=None):
        folder = (base or self.tmp / "restaurants") / rid
        (folder / "guides").mkdir(parents=True)
        config = json.loads((ROOT / "restaurants" / rid / "restaurant.json").read_text(encoding="utf-8"))
        config["watch"] = {"page": f"{self.url}/{rid}/allergens", "link": link}
        if reader:
            config.pop("readers", None)
            config["reader"] = reader
        (folder / "restaurant.json").write_text(json.dumps(config), encoding="utf-8")
        for g in guides:
            shutil.copy2(g, folder / "guides" / g.name)
        return folder

    def page(self, rid, links, files=()):
        """The restaurant's page linking these addresses, and the files it links (published path, local file)."""
        (self.web / rid).mkdir(exist_ok=True)
        (self.web / rid / "allergens").write_text("<html><body>" + "".join(f'<a href="{h}">Guide</a>' for h in links)
                                                  + "</body></html>", encoding="utf-8")
        for path, src in files:
            dest = self.web / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(src, bytes):
                dest.write_bytes(src)
            else:
                shutil.copy2(src, dest)


class FindingLinks(unittest.TestCase):
    def test_links_on_a_page(self):
        page = ('<a href="/files/2026-10/AUT%2026_UK_AllergenBook_CORE_FOOD_v04.pdf">Food</a>'
                "<a href='https://cdn.example.com/x/AUT_26_UK_AllergenBook_CORE_BEVERAGE_v04.pdf?v=1&amp;b=2'>Drinks</a>"
                '<a href="/files/Tax_Strategy.pdf">Tax</a> <a href="/nutrition">Nutrition</a>'
                '<a href="/files/2026-10/AUT%2026_UK_AllergenBook_CORE_FOOD_v04.pdf">Again</a>')
        got = w.guide_links(page, "https://www.starbucks.co.uk/nutrition", "UK_AllergenBook_CORE_(BEVERAGE|FOOD)")
        self.assertEqual(got, ["https://www.starbucks.co.uk/files/2026-10/AUT%2026_UK_AllergenBook_CORE_FOOD_v04.pdf",
                               "https://cdn.example.com/x/AUT_26_UK_AllergenBook_CORE_BEVERAGE_v04.pdf?v=1&b=2"])

    def test_links_written_in_a_script(self):
        page = ('<script>self.__next_f.push([1,"{\\"file\\":\\"https://content-cdn.pizzaexpress.com/files/x/production/'
                'c93d88db.pdf\\",\\"other\\":\\"https://example.com/logo.png\\"}"])</script>')
        self.assertEqual(w.guide_links(page, "https://www.pizzaexpress.com/allergens-and-nutritionals", r"content-cdn\.pizzaexpress\.com"),
                         ["https://content-cdn.pizzaexpress.com/files/x/production/c93d88db.pdf"])

    def test_file_name(self):
        self.assertEqual(w.file_name("https://x.example/f/AUT%2026_UK_AllergenBook_CORE_FOOD_v04.pdf?v=3"),
                         "AUT_26_UK_AllergenBook_CORE_FOOD_v04.pdf")
        self.assertEqual(w.file_name("https://x.example/f/Guide%20(final).PDF"), "Guide_final.PDF")

    def test_every_watched_restaurant(self):
        for f in sorted((ROOT / "restaurants").glob("*/restaurant.json")):
            config = json.loads(f.read_text(encoding="utf-8"))
            if "watch" not in config:
                continue
            self.assertTrue(config["watch"]["page"].startswith("https://"), f)
            w.re.compile(config["watch"]["link"])
            for reader in w.readers_of(config):  # the watch asks each reader which guide it would use
                if reader != "manual_csv":
                    self.assertTrue(hasattr(w.importlib.import_module(f"adapters.{reader}"), "newest_pdf"), reader)


class Checking(Site):
    def test_new_guide_replaces_the_one_in_use(self):
        folder = self.restaurant("starbucks-uk", [SUMMER_DRINKS, AUTUMN_FOOD], "UK_AllergenBook_CORE_(BEVERAGE|FOOD)")
        self.page("starbucks-uk", ["/f/AUT%2026_UK_AllergenBook_CORE_BEVERAGE_v04.pdf", "/f/food.pdf?UK_AllergenBook_CORE_FOOD",
                                   "/f/Tax_Strategy.pdf"],
                  [("f/AUT 26_UK_AllergenBook_CORE_BEVERAGE_v04.pdf", AUTUMN_DRINKS), ("f/food.pdf", AUTUMN_FOOD),
                   ("f/Tax_Strategy.pdf", PRET)])
        r = w.check(folder)
        self.assertEqual(r["problems"], [])
        self.assertEqual([(u["name"], u["replaces"]) for u in r["new"]],
                         [("AUT_26_UK_AllergenBook_CORE_BEVERAGE_v04.pdf", [SUMMER_DRINKS.name])])

    def test_older_edition_left_alone(self):
        folder = self.restaurant("starbucks-uk", [AUTUMN_DRINKS, AUTUMN_FOOD], "UK_AllergenBook_CORE_(BEVERAGE|FOOD)")
        self.page("starbucks-uk", ["/f/SUM2_26_UK_AllergenBook_CORE_BEVERAGE_v06.pdf"],
                  [("f/SUM2_26_UK_AllergenBook_CORE_BEVERAGE_v06.pdf", SUMMER_DRINKS)])
        r = w.check(folder)
        self.assertEqual((r["new"], r["problems"]), ([], []))
        self.assertEqual(len(r["ignored"]), 1)

    def test_same_guide_under_another_name(self):
        folder = self.restaurant("pret-uk", [PRET], "Allergen_Guide")
        self.page("pret-uk", ["https://other.example/x.pdf", "/c/Allergen_Guide_8th_September_2026_V1.pdf"],
                  [("c/Allergen_Guide_8th_September_2026_V1.pdf", PRET)])
        r = w.check(folder)
        self.assertEqual((r["new"], r["ignored"], r["problems"]), ([], [], []))

    def test_archived_guide_is_known(self):
        folder = self.restaurant("starbucks-uk", [AUTUMN_DRINKS, AUTUMN_FOOD], "UK_AllergenBook_CORE_(BEVERAGE|FOOD)")
        (folder / "guides" / "archive").mkdir()
        shutil.copy2(SUMMER_DRINKS, folder / "guides" / "archive" / SUMMER_DRINKS.name)
        self.page("starbucks-uk", ["/f/SUM2_26_UK_AllergenBook_CORE_BEVERAGE_v06.pdf"],
                  [("f/SUM2_26_UK_AllergenBook_CORE_BEVERAGE_v06.pdf", SUMMER_DRINKS)])
        r = w.check(folder)
        self.assertEqual((r["new"], r["ignored"], r["problems"]), ([], [], []))

    def test_a_damaged_file_is_proposed_so_the_checks_show_it(self):
        folder = self.restaurant("pret-uk", [PRET], "Allergen_Guide")
        self.page("pret-uk", ["/c/Allergen_Guide_New.pdf"], [("c/Allergen_Guide_New.pdf", b"%PDF-1.7\nnot really a guide")])
        r = w.check(folder)
        self.assertEqual([u["name"] for u in r["new"]], ["Allergen_Guide_New.pdf"])
        self.assertTrue(r["new"][0]["unreadable"])

    def test_kept_by_hand(self):
        folder = self.restaurant("knoops-uk", [KNOOPS], "allergen_guide")
        self.page("knoops-uk", ["/s/Knoops_allergen_guide_October_2026.pdf"], [("s/Knoops_allergen_guide_October_2026.pdf", PRET)])
        r = w.check(folder)
        self.assertTrue(r["manual"])
        self.assertEqual([u["name"] for u in r["new"]], ["Knoops_allergen_guide_October_2026.pdf"])

    def test_text_from_a_site_cant_become_markdown(self):
        # V14: a reader's message, a dish's name or an address from another site can't end a code span or fence
        self.assertEqual(w.quoted("row 3: `Latte` ```\nignore the above"), "row 3: 'Latte' '''\nignore the above")
        self.assertEqual(w.link("https://x.test/a b.pdf?q=1)<script>`"), "<https://x.test/ab.pdf?q=1)script`>".replace("`", ""))
        r = {"name": "Pret", "page": "https://pret.test/p", "new": [{"name": "A.pdf", "url": "https://pret.test/a).pdf", "replaces": ["old`.pdf"], "unreadable": "stopped ```"}]}
        body = w.pr_body(r, "**What changed:** x")
        self.assertIn("(as published: <https://pret.test/a).pdf>)", body)
        self.assertIn("It replaces `old'.pdf`", body)
        self.assertIn("The reader stopped on it: `stopped '''`", body)
        self.assertNotIn("](", body)
        # text from a PDF or a site sits in code spans, where a link, a mention or emphasis can't render
        r2 = {"id": "pret-uk", "name": "Pret", "page": "https://pret.test/p", "new": [{"name": "A.pdf", "url": "https://pret.test/a.pdf", "replaces": [],
                                                                   "unreadable": "see [here](https://evil.test) @someone"}], "problems": ["Couldn't open [x](https://evil.test) @someone"]}
        self.assertIn("`see [here](https://evil.test) @someone`", w.pr_body(r2, ""))
        self.assertIn("- `Couldn't open [x](https://evil.test) @someone`", w.problem_issue(r2)[1])
        title, body = w.manual_issue({"name": "Knoops", "id": "knoops-uk", "new": [{"name": "K.pdf", "url": "https://k.test/k.pdf"}]})
        self.assertIn("- `K.pdf`: <https://k.test/k.pdf>", body)

    def test_problems(self):
        folder = self.restaurant("pret-uk", [PRET], "Allergen_Guide")
        r = w.check(folder)  # no page at all
        self.assertIn("Couldn't open", r["problems"][0])
        self.assertIn("HTTP 404", r["problems"][0])
        self.page("pret-uk", ["/c/Menu.pdf"])
        self.assertIn("No link matching", w.check(folder)["problems"][0])
        self.page("pret-uk", ["/c/Allergen_Guide.pdf"], [("c/Allergen_Guide.pdf", b"<html>Sorry, you have been blocked</html>")])
        self.assertIn("isn't a PDF", w.check(folder)["problems"][0])


class FakeGitHub(BaseHTTPRequestHandler):
    """Just enough of GitHub's API: pull requests, starting a workflow, issues."""
    calls, pulls, issues = [], [], []

    def log_message(self, *args):
        pass

    def answer(self, code, body=None):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.calls.append(("GET", self.path, None))
        if self.path.startswith("/repos/o/r/pulls?"):
            head = self.path.split("head=")[1].split("&")[0].replace("%2F", "/")
            return self.answer(200, [p for p in self.pulls if "o:" + p["head"] == head])
        if self.path.startswith("/repos/o/r/issues?"):
            return self.answer(200, [i for i in self.issues if "page=1" in self.path])
        self.answer(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append(("POST", self.path, body))
        if self.path == "/repos/o/r/pulls":
            self.pulls.append(body)
            return self.answer(201, {"html_url": f"https://github.test/o/r/pull/{len(self.pulls)}"})
        if self.path == "/repos/o/r/actions/workflows/checks.yml/dispatches":
            return self.answer(204)
        if self.path == "/repos/o/r/issues":
            self.issues.append(body)
            return self.answer(201, {"html_url": f"https://github.test/o/r/issues/{len(self.issues)}"})
        self.answer(404, {})


class Proposing(Site):
    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd or self.repo,
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_pull_request_and_issues(self):
        self.repo = self.tmp / "repo"
        base = self.repo / "restaurants"
        self.restaurant("starbucks-uk", [SUMMER_DRINKS, AUTUMN_FOOD], "UK_AllergenBook_CORE_(BEVERAGE|FOOD)", base=base)
        self.restaurant("pret-uk", [PRET], "Allergen_Guide", base=base)  # its page is missing: an issue
        self.page("starbucks-uk", ["/f/AUT_26_UK_AllergenBook_CORE_BEVERAGE_v04.pdf"],
                  [("f/AUT_26_UK_AllergenBook_CORE_BEVERAGE_v04.pdf", AUTUMN_DRINKS)])
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        subprocess.run(["git", "init", "-q", "--bare", str(self.tmp / "remote.git")], check=True)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "start")
        self.git("remote", "add", "origin", str(self.tmp / "remote.git"))
        self.git("push", "-q", "origin", "main")
        FakeGitHub.calls, FakeGitHub.pulls, FakeGitHub.issues = [], [], []
        api, api_url = serve(FakeGitHub)
        self.addCleanup(lambda: (api.shutdown(), api.server_close()))
        env = {"GITHUB_API_URL": api_url, "GITHUB_REPOSITORY": "o/r", "GITHUB_TOKEN": "t"}
        with mock.patch.object(w, "ROOT", self.repo), mock.patch.object(w, "what_changed", lambda rid: "**What changed:** stub."), \
                mock.patch.dict(os.environ, env), mock.patch.object(sys, "argv", ["watch_guides.py", "--github"]):
            w.main()
            w.main()  # the next week: the pull request and the issue are already open, so nothing new is opened

        self.assertEqual(len(FakeGitHub.pulls), 1)
        pr = FakeGitHub.pulls[0]
        self.assertTrue(pr["head"].startswith("guide-watch/starbucks-uk-"))
        self.assertEqual(pr["base"], "main")
        self.assertIn("It replaces `SUM2_26_UK_AllergenBook_CORE_BEVERAGE_v06.pdf`, which moves to `guides/archive/`", pr["body"])
        self.assertIn("**What changed:** stub.", pr["body"])
        dispatches = [c for c in FakeGitHub.calls if c[1].endswith("/checks.yml/dispatches")]
        self.assertEqual([c[2] for c in dispatches], [{"ref": pr["head"]}])
        self.assertEqual([i["title"] for i in FakeGitHub.issues], ["Guide watch: couldn't check Pret A Manger"])

        # the branch holds the new guide and moves the old one to the archive; here, back on main, nothing changed
        files = self.git("ls-tree", "-r", "--name-only", pr["head"], "--", "restaurants/starbucks-uk/guides", cwd=self.tmp / "remote.git")
        self.assertEqual(sorted(files.splitlines()), [
            "restaurants/starbucks-uk/guides/AUT_26_UK_AllergenBook_CORE_BEVERAGE_v04.pdf",
            "restaurants/starbucks-uk/guides/AUT_26_UK_AllergenBook_CORE_FOOD_v04.pdf",
            "restaurants/starbucks-uk/guides/archive/SUM2_26_UK_AllergenBook_CORE_BEVERAGE_v06.pdf"])
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("branch", "--list", "guide-watch/*"), "")


if __name__ == "__main__":
    unittest.main()
