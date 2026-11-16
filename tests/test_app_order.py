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
        code = "\n".join(source(n) for n in ("listOr", "kindOf", "tagFor", "orderLine")) + """
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

    def test_the_known_orders_read_as_before(self):
        out = self.run_js([{"order": "asis"}, {"order": "except", "ok": ["soya"], "not": ["oat"]},
                           {"order": "modify", "note": "No croutons"}])
        self.assertEqual([o[0] for o in out], ["straight", "straight", "change"])
        self.assertEqual(out[1][1], ["t-any", "Any milk except oat"])
        self.assertEqual(out[2][2], "No croutons.")


if __name__ == "__main__":
    unittest.main()
