"""
The app must show a way of ordering it doesn't know as something to check, never as fine. Menus load fresher than
the app's own code, so a phone on an older app.js can meet an order value added later.

Runs kindOf, tagFor and orderLine taken from site/app.js in Node. Needs Node.js (it's on GitHub's runners).
"""
import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def source(name):
    """One function from site/app.js: a one-line const arrow, or a function up to its closing brace at two spaces."""
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    m = re.search(rf"^  const {name} = .*?;$", app, re.M) or re.search(rf"^  function {name}\(.*?^  }}$", app, re.M | re.S)
    if not m:
        raise AssertionError(f"{name} not found in site/app.js")
    return m.group(0)


@unittest.skipUnless(NODE, "needs Node.js")
class UnknownOrder(unittest.TestCase):
    def run_js(self, items):
        code = "\n".join(source(n) for n in ("ORDERS", "listOr", "kindOf", "tagFor", "orderLine")) + """
const r = { optionLabel: "milk" };
const items = JSON.parse(process.argv[1]);
process.stdout.write(JSON.stringify(items.map((i) => [kindOf(i), tagFor(r, i), orderLine(r, i)])));
"""
        out = subprocess.run([NODE, "-e", code, json.dumps(items)], capture_output=True, text=True, encoding="utf-8", check=True)
        return json.loads(out.stdout)

    def test_an_unknown_order_is_something_to_check(self):
        for item in ({"name": "X", "order": "ask", "not": ["oat"]}, {"name": "X", "order": "ask"}):
            kind, tag, line = self.run_js([item])[0]
            self.assertEqual(kind, "gluten", item)  # counted and filtered with the Avoid list, not as fine
            self.assertEqual(tag, ["t-bad", "Check in store"], item)
            self.assertEqual(line, "Please check this with staff.", item)

    def test_safe_menu_moves_an_unknown_order_to_the_avoid_list(self):
        # every screen (list, order builder, staff cards, Your usuals, counts) reads items and avoid, so the move is made
        # once, as the menu comes in
        code = source("ORDERS") + "\n" + source("safeMenu") + """
const menus = JSON.parse(process.argv[1]);
process.stdout.write(JSON.stringify(menus.map((r) => [safeMenu(r), safeMenu(r) === r])));
"""
        menu = {"id": "x", "stats": {"rows": 4, "items": 2, "ingredients": 1, "avoid": 1},
                "items": [{"name": "Latte", "section": "S", "order": "asis"},
                          {"name": "Mystery", "section": "S", "order": "ask", "ok": ["soya"], "not": ["oat"],
                           "decided": "Listed because…", "info": "Fine with any milk."},
                          {"name": "Odd milk", "section": "S", "order": "ask", "role": "ingredient"}],
                "avoid": [{"name": "Bun", "section": "S", "gluten": ["WHEAT"]}],
                # the build's What changed, worked out from the menu as published
                "changes": {"nowOk": [{"name": "Mystery", "section": "S"}], "added": [{"name": "Odd milk", "section": "S"}],
                            "changed": [{"name": "Mystery", "section": "S"}, {"name": "Latte", "section": "S"}],
                            "nowAvoid": [], "removed": []}}
        plain = {"id": "y", "stats": {"items": 1, "avoid": 0}, "items": [{"name": "Tea", "order": "asis"}], "avoid": []}
        out = subprocess.run([NODE, "-e", code, json.dumps([menu, plain])], capture_output=True, text=True, encoding="utf-8", check=True)
        (moved, same), (_, untouched) = json.loads(out.stdout)
        self.assertFalse(same)
        self.assertEqual([i["name"] for i in moved["items"]], ["Latte"])
        odd = {a["name"]: a for a in moved["avoid"]}
        self.assertEqual(sorted(odd), ["Bun", "Mystery", "Odd milk"])
        for name in ("Mystery", "Odd milk"):
            self.assertEqual((odd[name]["tag"], odd[name]["gluten"]), ("Check in store", []))
            self.assertTrue(odd[name]["reason"].startswith("Note from this app"))
            for key in ("order", "ok", "note", "decided", "info", "role"):  # nothing that explained it as fine
                self.assertNotIn(key, odd[name])
        self.assertEqual(moved["stats"], {"rows": 4, "items": 1, "ingredients": 0, "avoid": 3})
        # nothing in What changed may still call a moved item fine, new or ordered differently
        self.assertEqual((moved["changes"]["nowOk"], moved["changes"]["added"]), ([], []))
        self.assertEqual(moved["changes"]["changed"], [{"name": "Latte", "section": "S"}])
        self.assertTrue(untouched)  # a menu with nothing unknown is passed through as it is

    def test_every_menu_is_shown_through_safe_menu_and_saved_as_published(self):
        # both ways a menu comes in: the copy saved on the phone at startup, and a fresh load
        app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
        load = re.search(r"^  async function loadNow\(.*?^  }$", app, re.M | re.S).group(0)
        self.assertIn("const show = shown(fresh);", load)
        self.assertIn("data = show;", load)
        self.assertIn("setLooked(show.restaurants", load)  # what you last looked at is what was shown, moves included
        self.assertIn("saveMenus(DATA_KEY, JSON.stringify(fresh));", load)  # the published copy, not the moved one
        self.assertIn("const prev = raw;", load)  # reused by fingerprint from the published copy
        self.assertIn("raw = JSON.parse(saved); data = shown(raw);", app)
        self.assertEqual(len(re.findall(r"(?<![.\w])data = (?!null)", app)), 2, "data is set only from shown(...)")

    def test_an_avoid_row_without_a_gluten_list_still_reads(self):
        # check.py allows an Avoid row with a reason and no gluten list; it mustn't blank the page or read "contains ."
        code = source("cap") + "\n" + source("avoidTag") + "\n" + source("avoidWhy") + """
const rows = JSON.parse(process.argv[1]);
process.stdout.write(JSON.stringify(rows.map((a) => [avoidTag(a), avoidWhy(a)])));
"""
        rows = [{"reason": "Made with beer batter."}, {"gluten": []}, {"gluten": ["WHEAT", "OAT"]}, {"tag": "Check in store", "gluten": []}]
        out = subprocess.run([NODE, "-e", code, json.dumps(rows)], capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertEqual(json.loads(out.stdout), [
            ["Avoid", "Made with beer batter."], ["Avoid", "The guide lists gluten."],
            ["Wheat & Oat", "Every version contains wheat and oat."], ["Check in store", "The guide lists gluten."]])

    def test_today_is_the_phones_own_date(self):
        # 23:30 UTC on 1 July is 00:30 on 2 July in the UK: a guide valid until 1 July is out of date by then
        code = source("today") + "\nprocess.stdout.write(today(new Date(Date.UTC(2026, 6, 1, 23, 30))));"
        out = subprocess.run([NODE, "-e", code], capture_output=True, text=True, encoding="utf-8", check=True,
                             env={**os.environ, "TZ": "Europe/London"})
        self.assertEqual(out.stdout, "2026-07-02")

    def test_the_known_orders_read_as_before(self):
        out = self.run_js([{"order": "asis"}, {"order": "except", "ok": ["soya"], "not": ["oat"]},
                           {"order": "modify", "note": "No croutons"}])
        self.assertEqual([o[0] for o in out], ["straight", "straight", "change"])
        self.assertEqual(out[1][1], ["t-any", "Any milk except oat"])
        self.assertEqual(out[2][2], "No croutons.")


if __name__ == "__main__":
    unittest.main()
