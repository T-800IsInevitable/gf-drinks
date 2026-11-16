"""
The app must show a way of ordering it doesn't know as something to check, never as fine. Menus load fresher than
the app's own code, so a phone on an older app.js can meet an order value added later.

Runs kindOf, tagFor and orderLine taken from site/app.js in Node. Needs Node.js (it's on GitHub's runners).
"""
import json
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
                          {"name": "Mystery", "section": "S", "order": "ask", "ok": ["soya"], "not": ["oat"]},
                          {"name": "Odd milk", "section": "S", "order": "ask", "role": "ingredient"}],
                "avoid": [{"name": "Bun", "section": "S", "gluten": ["WHEAT"]}]}
        plain = {"id": "y", "stats": {"items": 1, "avoid": 0}, "items": [{"name": "Tea", "order": "asis"}], "avoid": []}
        out = subprocess.run([NODE, "-e", code, json.dumps([menu, plain])], capture_output=True, text=True, encoding="utf-8", check=True)
        (moved, same), (_, untouched) = json.loads(out.stdout)
        self.assertFalse(same)
        self.assertEqual([i["name"] for i in moved["items"]], ["Latte"])
        odd = {a["name"]: a for a in moved["avoid"]}
        self.assertEqual(sorted(odd), ["Bun", "Mystery", "Odd milk"])
        for name in ("Mystery", "Odd milk"):
            self.assertEqual((odd[name]["tag"], odd[name]["gluten"]), ("Check in store", []))
            self.assertNotIn("order", odd[name])
            self.assertNotIn("ok", odd[name])
        self.assertEqual(moved["stats"], {"rows": 4, "items": 1, "ingredients": 0, "avoid": 3})
        self.assertTrue(untouched)  # a menu with nothing unknown is passed through as it is

    def test_the_known_orders_read_as_before(self):
        out = self.run_js([{"order": "asis"}, {"order": "except", "ok": ["soya"], "not": ["oat"]},
                           {"order": "modify", "note": "No croutons"}])
        self.assertEqual([o[0] for o in out], ["straight", "straight", "change"])
        self.assertEqual(out[1][1], ["t-any", "Any milk except oat"])
        self.assertEqual(out[2][2], "No croutons.")


if __name__ == "__main__":
    unittest.main()
