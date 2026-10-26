"""
The app's own comparison (site/compare.js) must give exactly the same answer as tools/changes.py, because a slip
there could hide an item that now contains gluten. Checked on a real pair of guides (Starbucks' summer and autumn
2026 drinks guides) and on made-up older versions of every restaurant's menu, in both directions.

Needs Node.js (it's on GitHub's runners). Run: python -m unittest discover -s tests
"""
import copy
import json
import os
import random
import shutil
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import changes  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "changes"
TODAY = date(2026, 10, 26)
NODE = shutil.which("node")
RUN = """
const compare = require(process.env.GF_COMPARE);
let s = "";
process.stdin.on("data", (d) => (s += d)).on("end", () => {
  const cases = JSON.parse(s);
  process.stdout.write(JSON.stringify(cases.map(([a, b, t]) => compare(a, b, t))));
});
"""


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def in_js(cases):
    out = subprocess.run([NODE, "-e", RUN], input=json.dumps([[a, b, TODAY.isoformat()] for a, b in cases]),
                         capture_output=True, text=True, encoding="utf-8", check=True,
                         env={**os.environ, "GF_COMPARE": str(ROOT / "site" / "compare.js")})
    return json.loads(out.stdout)


def older(menu, seed):
    """A made-up earlier edition of a real menu, with every kind of difference compare() has to notice: items new
    since, gone, moved on or off the Avoid list, ordered differently, sections renamed, names respaced and recased,
    empty options, and one name used twice."""
    rnd = random.Random(seed)
    items, avoid = [], []
    for i in copy.deepcopy(menu["items"]):
        roll = rnd.random()
        if roll < 0.08:
            continue                                                     # new since then
        if roll < 0.14:
            avoid.append({"name": i["name"], "section": i["section"], "gluten": ["WHEAT"]})  # was to avoid
            continue
        if roll < 0.22:                                                  # ordered differently
            i["order"], i["ok"], i["not"] = "except", ["Soya", "Almond"], ["Oat"]
        elif roll < 0.25:
            i["section"] = "Old " + i["section"]                         # section renamed since
        elif roll < 0.28:
            i["name"] = "  " + i["name"].upper().replace(" ", "  ") + " "  # same name, other spacing and capitals
        elif roll < 0.30:
            i["ok"], i["note"] = [], ""                                  # empty: counts as missing
        items.append(i)
    for a in copy.deepcopy(menu["avoid"]):
        roll = rnd.random()
        if roll < 0.10:
            continue                                                     # newly to avoid
        if roll < 0.18:
            items.append({"name": a["name"], "section": a["section"], "order": "asis"})  # now contains gluten
            continue
        avoid.append(a)
    items += [{"name": f"Gone item {seed}-{n}", "section": "Gone", "order": "asis"} for n in range(rnd.randint(1, 4))]
    if items:
        twin = dict(rnd.choice(items), section="Another section")       # one name in two sections
        items.append(twin)
    return {"source": f"older-{seed}.pdf", "guide": {"title": f"Older edition {seed}"}, "items": items, "avoid": avoid}


@unittest.skipUnless(NODE or os.environ.get("CI"), "Node.js isn't installed")
class SameAnswerInTheApp(unittest.TestCase):
    def check(self, pairs):
        self.assertIsNotNone(NODE, "Node.js is needed to check the app's comparison")
        got = in_js(pairs)
        for (a, b), js in zip(pairs, got):
            py = changes.compare(a, b, TODAY)
            self.assertEqual(js, py, f"{a['source']} -> {b['source']}")
        return got

    def test_real_pair_of_guides(self):
        summer, autumn = load("starbucks-drinks-summer-2026.json"), load("starbucks-drinks-autumn-2026.json")
        got = self.check([(summer, autumn), (autumn, summer)])
        self.assertTrue(got[0]["added"] and got[0]["removed"], "the real pair should have items new and gone")

    def test_made_up_older_menus(self):
        pairs = []
        for f in sorted(FIX.glob("menu-*.json")):
            now = json.loads(f.read_text(encoding="utf-8"))
            for seed in range(1, 7):
                was = older(now, f"{f.stem}-{seed}")
                pairs += [(was, now), (now, was)]
        got = self.check(pairs)
        # every kind of change came up somewhere, so none of them went untested
        for kind in ("nowAvoid", "nowOk", "changed", "added", "removed"):
            self.assertTrue(any(g[kind] for g in got), f"no case produced {kind}")
        self.assertTrue(any(g["newAvoid"] for g in got))

    def test_nothing_to_compare_with_and_same_guide(self):
        now = load("menu-pret-uk.json")
        self.assertEqual(in_js([(None, now)]), [None])
        live = dict(now, changes={"since": "x", "added": []})
        self.assertEqual(in_js([(live, now)]), [live["changes"]])


if __name__ == "__main__":
    unittest.main()
