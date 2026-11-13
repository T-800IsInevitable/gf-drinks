"""
The backstops that stop a build rather than publish a menu a reader has misread: build.py's Avoid-share guard
(avoid_drop), the Pret reader's unknown-mark test (odd_mark) and the shared cereal pattern.

Run: python -m unittest discover -s tests
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build  # noqa: E402
from adapters.common import CEREAL, CEREAL_CAPS, cereal_code  # noqa: E402
from adapters.pret_uk_pdf import TICK, odd_mark  # noqa: E402


def menu(avoid, items, source="guide.pdf", src=None):
    row = (lambda n: {"name": f"row {n}", **({"src": src} if src is not None else {})})
    return {"source": source, "avoid": [row(n) for n in range(avoid)], "items": [row(n) for n in range(items)]}


def merged(*parts):
    """Several guides' rows in one menu, each part (avoid, items) carrying its guide's number as "src"."""
    out = {"source": "a.pdf and b.pdf", "avoid": [], "items": []}
    for n, (avoid, items) in enumerate(parts):
        m = menu(avoid, items, src=n)
        out["avoid"] += m["avoid"]
        out["items"] += m["items"]
    return out


class AvoidDrop(unittest.TestCase):
    def run_drop(self, prev, full, config=None):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "test-cafe"
            folder.mkdir()
            (folder / "restaurant.json").write_text(json.dumps(config or {}), encoding="utf-8")
            build.avoid_drop(prev, full, folder)

    def test_a_small_avoid_share_is_still_judged(self):
        # 15 of 189 rows to avoid (8% of the menu): every one turning green must stop the build
        with self.assertRaises(SystemExit) as stop:
            self.run_drop(menu(15, 174), menu(0, 189, source="new.pdf"))
        self.assertIn("avoidDropOk", str(stop.exception))
        self.assertIn("guide-watch/", str(stop.exception))

    def test_a_steady_share_and_a_first_build_pass(self):
        self.run_drop(menu(15, 174), menu(14, 180, source="new.pdf"))
        self.run_drop(None, menu(0, 50))
        self.run_drop(menu(3, 100), menu(0, 103, source="new.pdf"))  # under the floor: too few rows to judge by

    def test_one_guide_of_a_merged_menu_failing_isnt_hidden_by_the_other(self):
        # drinks lose every Avoid row, food keeps its 90: the whole menu's share falls only from 50% to 45%
        with self.assertRaises(SystemExit) as stop:
            self.run_drop(merged((10, 90), (90, 10)), merged((0, 100), (90, 10)))
        self.assertIn("guide 1", str(stop.exception))

    def test_the_owner_can_accept_a_real_fall_for_that_guide_only(self):
        self.run_drop(menu(15, 174), menu(0, 189, source="new.pdf"), {"avoidDropOk": "new.pdf"})
        with self.assertRaises(SystemExit):
            self.run_drop(menu(15, 174), menu(0, 189, source="newer.pdf"), {"avoidDropOk": "new.pdf"})


class Marks(unittest.TestCase):
    def test_a_mark_that_isnt_the_tick_is_odd(self):
        for text in ("(cid:3)", "(cid:3)(cid:3)", "Yes", "yes", "May", "X", "✓", "•", "*", "1"):
            self.assertTrue(odd_mark(text), text)

    def test_ticks_and_allergen_names_are_not(self):
        for text in (TICK, TICK + TICK, "Almond", "Nuts", "(Wheat)", "Kamut", "Sesame"):
            self.assertFalse(odd_mark(text), text)


class Cereals(unittest.TestCase):
    def test_malt_in_the_forms_that_mean_the_grain(self):
        for text, code in (("Maltesers Hot Chocolate", "MALT"), ("Malty Biscuit Latte", "MALT"), ("malt vinegar", "MALT"),
                           ("Malted milk", "MALT"), ("Bulgar Salad", "WHEAT"), ("Bulgur", "WHEAT"), ("OATMILK", "OAT")):
            self.assertEqual([cereal_code(m) for m in CEREAL.findall(text)], [code], text)
            self.assertTrue(CEREAL_CAPS.search(text.upper()), text)

    def test_sweeteners_and_other_words_stay_out(self):
        for text in ("maltodextrin", "maltitol", "Maltose syrup", "Malta", "goat cheese", "Emmental", "gluten free bread"):
            self.assertEqual(CEREAL.findall(text), [], text)


if __name__ == "__main__":
    unittest.main()
