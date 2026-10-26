"""
The service worker's side of notifications (site/sw.js), run in Node with stand-ins (tests/sw_push_harness.js):
the notification says what tools/push.py sent, warns first when one of the phone's favourites now contains gluten,
sets the badge, and a tap opens the app at the restaurant the message names.

Run: python -m unittest discover -s tests
"""
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SW = ROOT / "site" / "sw.js"
HARNESS = ROOT / "tests" / "sw_push_harness.js"
MSG = {"title": "New menus in Treat Temple", "body": "Pret A Manger: November 2026 guide: 2 now contain gluten, 5 new.", "tag": "gf-menus",
       "url": "#pret-uk", "nowAvoid": ["pret-uk|Hot drinks|Oat latte", "pret-uk|Food|Granola pot"], "badge": 1}


def run(favs, msg=MSG, open_client=False):
    env = {**os.environ, "OPEN_CLIENT": "1" if open_client else ""}
    done = subprocess.run(["node", str(HARNESS), str(SW), json.dumps(favs), json.dumps(msg)], capture_output=True, text=True, env=env)
    if done.returncode:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


@unittest.skipUnless(shutil.which("node"), "needs Node")
class Push(unittest.TestCase):
    def test_plain_message_and_badge(self):
        out = run(["pret-uk|Soup|Pea soup"])
        self.assertEqual(len(out["notifications"]), 1)
        n = out["notifications"][0]
        self.assertEqual((n["title"], n["body"], n["tag"]), (MSG["title"], MSG["body"], "gf-menus"))
        self.assertEqual(out["badge"], 1)
        self.assertNotIn("gluten free", n["body"])

    def test_a_favourite_that_now_contains_gluten_comes_first(self):
        out = run(["pret-uk|Food|Granola pot", "city:berlin|Oshione"])
        body = out["notifications"][0]["body"]
        self.assertTrue(body.startswith("A favourite now contains gluten: Granola pot. "), body)
        self.assertIn(MSG["body"], body)
        self.assertTrue(out["notifications"][0]["renotify"])

    def test_a_tap_opens_the_app_at_the_restaurant(self):
        out = run([])
        self.assertEqual(out["opened"], "https://example.test/gf-drinks/#pret-uk")
        out = run([], open_client=True)
        self.assertTrue(out["focused"])
        self.assertEqual(out["navigated"], "https://example.test/gf-drinks/#pret-uk")

    def test_a_message_without_json_still_shows(self):
        out = run([], msg={"body": "plain"})
        self.assertEqual(out["notifications"][0]["title"], "Treat Temple")


if __name__ == "__main__":
    unittest.main()
