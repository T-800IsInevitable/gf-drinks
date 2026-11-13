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
    """A menu from two lists of names (or a count, for names made up here: "avoid 0", "item 0"...)."""
    names = lambda v, word: [f"{word} {n}" for n in range(v)] if isinstance(v, int) else list(v)
    row = lambda name: {"name": name, **({"src": src} if src is not None else {})}
    return {"source": source, "avoid": [row(n) for n in names(avoid, "avoid")], "items": [row(n) for n in names(items, "item")]}


def blind(m, source="new.pdf"):
    """The same menu as a reader that misses every gluten mark would build it: each Avoid row on the list instead."""
    return {"source": source, "avoid": [], "items": m["items"] + m["avoid"]}


def merged(*parts):
    """Several guides' menus in one, each row carrying its guide's number as "src"."""
    out = {"source": "a.pdf and b.pdf", "avoid": [], "items": []}
    for n, part in enumerate(parts):
        for key in ("avoid", "items"):
            out[key] += [{**r, "name": f"g{n} {r['name']}", "src": n} for r in part[key]]
    return out


class AvoidDrop(unittest.TestCase):
    def run_drop(self, prev, full, config=None):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "test-cafe"
            folder.mkdir()
            (folder / "restaurant.json").write_text(json.dumps(config or {}), encoding="utf-8")
            build.avoid_drop(prev, full, folder)

    def test_avoid_rows_turning_green_stop_the_build_however_small_their_share(self):
        live = menu(15, 174)  # 15 of 189 rows to avoid: 8% of the menu
        with self.assertRaises(SystemExit) as stop:
            self.run_drop(live, blind(live))
        self.assertIn("avoidDropOk", str(stop.exception))
        self.assertIn("guide-watch/", str(stop.exception))
        self.assertIn("avoid 0", str(stop.exception))  # it names what moved
        with self.assertRaises(SystemExit):
            self.run_drop(menu(3, 12), blind(menu(3, 12)))  # few rows, but a fifth of the menu

    def test_a_seasons_avoid_rows_leaving_the_menu_is_not_a_reader_failing(self):
        # six to avoid, two of them seasonal drinks that go; new seasonal drinks arrive on the list: the Avoid share
        # falls from 4% to under 3%, and nothing that was to avoid is now listed
        live = menu(["pumpkin cake pop latte", "ghost frappe", "a", "b", "c", "d"], 133)
        self.run_drop(live, menu(["a", "b", "c", "d"], 146, source="new.pdf"))

    def test_a_first_build_a_steady_menu_and_one_recipe_change_pass(self):
        self.run_drop(None, menu(0, 50))
        self.run_drop(menu(15, 174), menu(15, 180, source="new.pdf"))
        live = menu(15, 174)  # one of fifteen is no longer to avoid: a recipe change, shown in What changed
        self.run_drop(live, {"source": "new.pdf", "avoid": live["avoid"][1:], "items": live["items"] + live["avoid"][:1]})
        small = menu(2, 100)  # and one of two, on a menu too small to judge by
        self.run_drop(small, {"source": "new.pdf", "avoid": small["avoid"][1:], "items": small["items"] + small["avoid"][:1]})

    def test_a_third_of_the_avoid_rows_moving_stops_it(self):
        live = menu(6, 100)
        with self.assertRaises(SystemExit):
            self.run_drop(live, {"source": "new.pdf", "avoid": live["avoid"][3:], "items": live["items"] + live["avoid"][:3]})

    def test_renamed_and_blind_at_once_stops_it(self):
        # every Avoid row gone under its old name and nothing to avoid under the new ones
        with self.assertRaises(SystemExit) as stop:
            self.run_drop(menu(15, 174), menu(0, [f"renamed {n}" for n in range(189)], source="new.pdf"))
        self.assertIn("left the menu", str(stop.exception))

    def test_one_guide_of_a_merged_menu_failing_isnt_hidden_by_the_other(self):
        drinks, food = menu(6, 133), menu(90, 10)
        with self.assertRaises(SystemExit) as stop:
            self.run_drop(merged(drinks, food), merged(blind(drinks), food))
        self.assertIn("guide 1 of 2", str(stop.exception))
        self.run_drop(merged(drinks, food), merged(drinks, food))

    def test_the_owner_can_accept_a_real_change_for_that_guide_only(self):
        live = menu(15, 174)
        self.run_drop(live, blind(live), {"avoidDropOk": "new.pdf"})
        with self.assertRaises(SystemExit):
            self.run_drop(live, blind(live, source="newer.pdf"), {"avoidDropOk": "new.pdf"})


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
