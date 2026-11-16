"""
The backstops that stop a build rather than publish a menu a reader has misread: build.py's Avoid-share guard
(avoid_drop), the readers' unknown-mark tests (Pret's odd_mark, Greggs' and Five Guys' odd_marks) and the shared
cereal pattern.

Run: python -m unittest discover -s tests
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build  # noqa: E402
from adapters import blank_street_uk_pdf, caffe_nero_uk_pdf, common, five_guys_uk_pdf, greggs_uk_pdf, pret_uk_pdf, starbucks_uk_pdf  # noqa: E402
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

    def test_five_avoid_rows_turning_green_stop_it_however_many_stay(self):
        live = menu(60, 100)
        moved = lambda k: {"source": "new.pdf", "avoid": live["avoid"][k:], "items": live["items"] + live["avoid"][:k]}
        for k in (5, 6, 19):  # a twelfth to a third of the Avoid rows: under the share test, over the floor
            with self.assertRaises(SystemExit) as stop:
                self.run_drop(live, moved(k))
            self.assertIn(f"{k} of the 60 Avoid rows", str(stop.exception))
        for k in (1, 4):  # a recipe change or a few
            self.run_drop(live, moved(k))
        self.run_drop(live, moved(6), {"avoidDropOk": "new.pdf"})  # still the owner's to accept, for that guide

    def test_renamed_and_blind_at_once_stops_it(self):
        # every Avoid row gone under its old name and nothing to avoid under the new ones
        with self.assertRaises(SystemExit) as stop:
            self.run_drop(menu(15, 174), menu(0, [f"renamed {n}" for n in range(189)], source="new.pdf"))
        self.assertIn("left the menu", str(stop.exception))

    def test_one_guide_of_a_merged_menu_failing_isnt_hidden_by_the_other(self):
        # four drinks rows: under the whole menu's stop at five, so only the drinks guide's own share can stop it
        drinks, food = menu(4, 133), menu(90, 10)
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


def char(text, x, y=100):
    """A character as pdfplumber gives it, 4pt square, centred on (x, y)."""
    return {"text": text, "x0": x - 2, "x1": x + 2, "top": y - 2, "bottom": y + 2}


class UnknownMarks(unittest.TestCase):
    """Greggs and Five Guys: a character in the gluten columns that isn't one of the guide's marks stops the build,
    where it used to be read as an empty cell (and the row listed)."""

    def test_greggs_only_the_tick_and_the_bullet_are_marks(self):
        xs = [300, 320, 340]  # three cereal columns, 20pt apart
        marks = [char(greggs_uk_pdf.TICK, 300), char(greggs_uk_pdf.BULLET, 341), char(" ", 320)]
        self.assertEqual(greggs_uk_pdf.odd_marks(marks, xs, 10), [])
        for text in ("†", "*", "x", "Y", "✔", "●", "1"):
            self.assertEqual(greggs_uk_pdf.odd_marks(marks + [char(text, 322)], xs, 10), [text])
        # the same character under another allergen's column (the GF column's own letters) isn't this test's to judge
        self.assertEqual(greggs_uk_pdf.odd_marks(marks + [char("G", 360), char("F", 364)], xs, 10), [])

    def test_five_guys_only_the_dot_and_the_two_numbers_are_marks(self):
        bars = [{"top": 190, "bottom": 215}]
        marks = [char("•", 500, 120), char("1", 501, 140), char("2", 499, 160)]
        self.assertEqual(five_guys_uk_pdf.odd_marks(marks, 500, 12, bars), [])
        for text in ("3", "†", "*", "x", "●"):
            self.assertEqual(five_guys_uk_pdf.odd_marks(marks + [char(text, 503, 180)], 500, 12, bars), [text])
        # a section bar's title runs across the column; the next column's marks are its own
        self.assertEqual(five_guys_uk_pdf.odd_marks(marks + [char("S", 500, 200), char("x", 530, 120)], 500, 12, bars), [])


class Repeats(unittest.TestCase):
    """The same item twice: a clean copy never hides a copy that names gluten."""
    row = {"section": "Hot", "sub": None, "page": 1}

    def test_starbucks_a_gluten_row_with_no_milk_is_avoid(self):
        for second in ("Toffee Nut Latte", "Toffee Nut Latte - skimmed milk"):
            ok, avoid = starbucks_uk_pdf.group([{**self.row, "name": "Toffee Nut Latte", "gluten": ["WHEAT"]},
                                                {**self.row, "name": second, "gluten": []}])
            self.assertEqual((ok, [a["name"] for a in avoid]), ([], ["Toffee Nut Latte"]), second)

    def test_pret_a_gluten_row_with_no_milk_is_avoid(self):
        ok, avoid = pret_uk_pdf.group([{**self.row, "name": "Mocha", "gluten": []}, {**self.row, "name": "Mocha", "gluten": ["WHEAT"]}])
        self.assertEqual((ok, [a["name"] for a in avoid]), ([], ["Mocha"]))

    def test_a_gluten_base_row_wins_over_milk_rows_that_differ(self):
        # one milk-less row with wheat, an oat row and a clean row: the wheat can't be ordered away, whatever the oat row says
        for reader, oat, skimmed in ((starbucks_uk_pdf, "Latte - oat drink", "Latte - skimmed milk"),
                                     (pret_uk_pdf, "Latte - Oat", "Latte - Skimmed milk")):  # each guide's own wording
            ok, avoid = reader.group([{**self.row, "name": "Latte", "gluten": ["WHEAT"]},
                                      {**self.row, "name": oat, "gluten": ["OAT"]},
                                      {**self.row, "name": skimmed, "gluten": []}])
            self.assertEqual((ok, [a["name"] for a in avoid]), ([], ["Latte"]), reader.__name__)

    def test_one_of_each_keeps_the_same_name_in_two_sections(self):
        ok, avoid = common.one_of_each([{"section": "Meat", "name": "Hot Dog"}],
                                       [{"section": "Hot Dogs", "name": "Hot Dog", "gluten": ["WHEAT"]}], [])
        self.assertEqual((len(ok), len(avoid)), (1, 1))

    def test_one_of_each_keeps_every_cereal_of_two_avoid_copies(self):
        _, avoid = common.one_of_each([], [{"section": "S", "name": "Bun", "gluten": ["PREPARATION"]},
                                           {"section": "S", "name": "Bun", "gluten": ["WHEAT"]}], [])
        self.assertEqual([a["gluten"] for a in avoid], [["PREPARATION", "WHEAT"]])

    def test_five_guys_and_caffe_nero_use_one_of_each(self):
        # the readers themselves, fed a clean copy and a gluten copy of one item, list it only under Avoid
        fg_rows = [{"section": "SHAKES", "name": "Shake", "marks": [], "info": "", "stars": 0},
                   {"section": "SHAKES", "name": "Shake", "marks": ["dot"], "info": "", "stars": 0}]
        with mock.patch.object(five_guys_uk_pdf, "newest_pdf", lambda folder: Path("g.pdf")), \
                mock.patch.object(five_guys_uk_pdf.pdfplumber, "open", mock.MagicMock()), \
                mock.patch.object(five_guys_uk_pdf, "parse", lambda pdf, path: (fg_rows, {}, "2026-01-01", [], [])):
            out = five_guys_uk_pdf.build("x", {})
        self.assertEqual(([i["name"] for i in out["items"]], [a["name"] for a in out["avoid"]]), ([], ["Shake"]))

        food = [(1, "Cakes", "Lemon Slice", "sugar, butter (MILK)"), (1, "Cakes", "Lemon Slice", "WHEAT flour, sugar")]
        pdf = mock.MagicMock()
        pdf.__enter__.return_value.pages = [object()]
        with mock.patch.object(caffe_nero_uk_pdf, "newest_pdf", lambda folder: Path("g.pdf")), \
                mock.patch.object(caffe_nero_uk_pdf.pdfplumber, "open", lambda p: pdf), \
                mock.patch.object(caffe_nero_uk_pdf, "kind_of", lambda page: "food"), \
                mock.patch.object(caffe_nero_uk_pdf, "food_rows", lambda page, n, section: iter(food)), \
                mock.patch.object(caffe_nero_uk_pdf, "page_notices", lambda pdf, pages: []), \
                mock.patch.object(caffe_nero_uk_pdf, "guide_info", lambda pdf: {"title": "x", "runs": None, "version": "2026-01-01"}), \
                mock.patch.multiple(caffe_nero_uk_pdf, MIN_FOOD=0, MIN_DRINKS=0):
            out = caffe_nero_uk_pdf.build("x", {})
        self.assertEqual(([i["name"] for i in out["items"]], [a["name"] for a in out["avoid"]]), ([], ["Lemon Slice"]))

    def test_one_of_each_moves_a_clean_copy_off_the_list(self):
        ok = [{"section": "Shakes", "name": "Shake"}, {"section": "Shakes", "name": "Malt"}, {"section": "Shakes", "name": "malt"}]
        avoid = [{"section": "Shakes", "name": "Shake", "gluten": ["GLUTEN"]}]
        warnings = []
        ok, avoid = common.one_of_each(ok, avoid, warnings)
        self.assertEqual(([i["name"] for i in ok], [a["name"] for a in avoid]), (["Malt"], ["Shake"]))
        self.assertEqual(len(warnings), 2)


class BlankStreetLowerCase(unittest.TestCase):
    """Blank Street writes allergens in capitals, but a cereal in ordinary case is still a cereal."""

    def classify(self, text):
        return blank_street_uk_pdf.classify({"name": "X", "section": "Bakes", "page": 1, "text": text}, [])

    def test_a_cereal_not_in_capitals_is_avoid(self):
        kind, item = self.classify("Rolled oats, butter, golden syrup. May Contain - MILK")
        self.assertEqual((kind, item["gluten"]), ("avoid", ["OAT"]))

    def test_may_contain_with_a_colon(self):
        kind, item = self.classify("With DAIRY: MILK, coffee. May Contain: Oat (Gluten)")
        self.assertEqual((kind, item.get("tag")), ("avoid", "May contain gluten"))

    def test_capitals_alone_still_read_as_before(self):
        self.assertEqual(self.classify("MILK, coffee, sugar. May Contain - SOYA")[1].get("order"), "asis")


class Cereals(unittest.TestCase):
    def test_malt_in_the_forms_that_mean_the_grain(self):
        for text, code in (("Maltesers Hot Chocolate", "MALT"), ("Malty Biscuit Latte", "MALT"), ("malt vinegar", "MALT"),
                           ("Malted milk", "MALT"), ("Bulgar Salad", "WHEAT"), ("Bulgur", "WHEAT"), ("OATMILK", "OAT"),
                           ("Wholewheat Pasta", "WHEAT"), ("WHOLEWHEAT flour", "WHEAT"), ("wholeoats", "OAT")):
            self.assertEqual([cereal_code(m) for m in CEREAL.findall(text)], [code], text)
            self.assertTrue(CEREAL_CAPS.search(text.upper()), text)

    def test_sweeteners_and_other_words_stay_out(self):
        for text in ("maltodextrin", "maltitol", "Maltose syrup", "Malta", "goat cheese", "Emmental", "gluten free bread", "Buckwheat",
                     "wholemeal rice", "whole milk"):
            self.assertEqual(CEREAL.findall(text), [], text)


if __name__ == "__main__":
    unittest.main()
