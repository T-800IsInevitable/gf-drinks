"""
The guide reminders (tools/reminders.py): one issue per guide ending within three weeks and per city list due a
re-check, none twice, read from any restaurants.json (the workflow passes the live one). Runs against a fake GitHub.

Run: python -m unittest discover -s tests
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import reminders  # noqa: E402


class FakeGitHub(BaseHTTPRequestHandler):
    issues = []

    def log_message(self, *args):
        pass

    def answer(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.answer(200, list(self.issues) if "page=1" in self.path else [])

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.issues.append(body)
        self.answer(201, {"html_url": f"https://github.test/o/r/issues/{len(self.issues)}"})


class Reminders(unittest.TestCase):
    def setUp(self):
        FakeGitHub.issues = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.httpd.shutdown(), self.httpd.server_close()))
        env = {"GITHUB_API_URL": f"http://127.0.0.1:{self.httpd.server_address[1]}", "GITHUB_REPOSITORY": "o/r", "GITHUB_TOKEN": "t"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.index = Path(tempfile.mkdtemp()) / "restaurants.json"
        self.index.write_text(json.dumps({"built": "2026-10-26T00:00:00Z", "restaurants": [
            {"id": "pret-uk", "name": "Pret A Manger", "source": "pret.pdf", "guide": {"validUntil": "2026-11-10"}},
            {"id": "pho-uk", "name": "Pho", "source": "pho.pdf", "guide": {"validUntil": "2027-03-01"}},
        ]}), encoding="utf-8")

    def run_reminders(self, *extra):
        with mock.patch.object(sys, "argv", ["reminders.py", "--github", "--index", str(self.index), *extra]), \
                mock.patch("reminders.date") as d:  # today is fixed, so the test doesn't age
            d.today.return_value = date(2026, 10, 26)
            d.fromisoformat = date.fromisoformat
            reminders.main()

    def test_due_guides_and_city_lists_get_one_issue_each(self):
        self.run_reminders()
        titles = [i["title"] for i in FakeGitHub.issues]
        self.assertIn("Guide check: Pret A Manger (guide ends 2026-11-10)", titles)
        self.assertNotIn("Guide check: Pho (guide ends 2027-03-01)", titles)
        self.assertTrue(all(t.startswith(("Guide check:", "Places check:")) for t in titles))
        before = len(titles)
        self.run_reminders()  # the next morning: nothing opened twice
        self.assertEqual(len(FakeGitHub.issues), before)

    def test_cities_are_rechecked_monthly_one_a_day(self):
        cities = json.loads((ROOT / "site" / "cities.json").read_text(encoding="utf-8"))
        newest = max(date.fromisoformat(c["checked"]) for c in cities.values())
        oldest = sorted(cities.values(), key=lambda c: c["checked"])
        day = newest.fromordinal(newest.toordinal() + reminders.CITY_EVERY)  # every city a month old
        self.assertEqual(len([r for r, _, _ in reminders.due(day, self.index) if "city" in r]), len(cities))
        with mock.patch("reminders.date") as d:
            d.today.return_value = day
            d.fromisoformat = date.fromisoformat
            for n in (1, 2):  # a morning each: the longest unchecked city first, and one a day
                with mock.patch.object(sys, "argv", ["reminders.py", "--github", "--index", str(self.index)]):
                    reminders.main()
                titles = [i["title"] for i in FakeGitHub.issues if i["title"].startswith("Places check:")]
                self.assertEqual(len(titles), n)
                self.assertTrue(titles[-1].startswith(f"Places check: {oldest[n - 1]['name']} places"))
        self.assertIn("Re-checking a city", FakeGitHub.issues[-1]["body"])
        self.assertFalse([i for i in FakeGitHub.issues if i["title"].startswith("Places list ends:")])  # not near the end yet
        # no re-check merged by three weeks before the list's end: the owner is told, under a title of its own
        c = oldest[0]
        end = date.fromisoformat(c["checked"]).toordinal() + c.get("recheckDays", 90)
        with mock.patch("reminders.date") as d:
            d.today.return_value = date.fromordinal(end - 5)
            d.fromisoformat = date.fromisoformat
            with mock.patch.object(sys, "argv", ["reminders.py", "--github", "--index", str(self.index)]):
                reminders.main()
        ends = [i for i in FakeGitHub.issues if i["title"].startswith("Places list ends:")]
        self.assertIn(f"Places list ends: {c['name']} places ({date.fromordinal(end).isoformat()})", [i["title"] for i in ends])
        self.assertIn("merge it", ends[0]["body"])
        fresh = newest.fromordinal(newest.toordinal() + reminders.CITY_EVERY - 1)
        self.assertNotIn(oldest[-1]["name"] + " places", [r["name"] for r, _, _ in reminders.due(fresh, self.index)])

    def test_reads_the_index_it_is_given(self):
        items = reminders.due(date(2026, 10, 26), self.index)
        self.assertEqual([r["id"] for r, _, _ in items if "city" not in r], ["pret-uk"])


if __name__ == "__main__":
    unittest.main()
