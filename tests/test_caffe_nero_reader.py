"""Caffè Nero drinks tables: a table whose header leaves out PRODUCT (the Festive Gingerbread Latte, October 2026) is
read, but only while every drink's name stays left of the ALLERGENS column."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from adapters import caffe_nero_uk_pdf as nero  # noqa: E402


def word(text, x0, x1, top):
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 8}


class Page:
    """Just enough of a pdfplumber page: one dark header bar, one row under it and the rule that closes the row."""
    height, width, lines = 800, 600, []

    def __init__(self, headings, name_end):
        self.rects = [{"top": 100, "bottom": 120, "width": 500, "height": 20, "non_stroking_color": (0.1, 0.1, 0.1)},
                      {"top": 140, "bottom": 140.5, "width": 500, "height": 0.5}]
        self.words = [word(h, x, x + 60, 105) for h, x in headings]
        self.words += [word("Gingerbread", 100, 150, 126), word("Latte", 155, name_end, 126), word("-", 185, 188, 126),
                       word("Oat", 190, 205, 126), word("OAT,", 300, 325, 126), word("MILK", 330, 355, 126)]
        self.words += [word(n, 400 + 20 * i, 415 + 20 * i, 126) for i, n in enumerate(("394", "95", "6.0", "3.6", "7.3"))]

    def extract_text(self):
        return "Iced Beverage Nutritional & Allergen Information\nFESTIVE"

    def extract_words(self):
        return self.words


class NoProductHeading(unittest.TestCase):
    def test_read_when_the_names_sit_left_of_allergens(self):
        rows = list(nero.drink_rows(Page([("ALLERGENS", 300), ("DIETARY", 380)], 180), 24))
        self.assertEqual([(r["name"], r["gluten"]) for r in rows], [("Gingerbread Latte - Oat", ["OAT"])])

    def test_stops_when_a_name_reaches_allergens(self):
        with self.assertRaises(SystemExit) as stop:
            list(nero.drink_rows(Page([("ALLERGENS", 300), ("DIETARY", 380)], 310), 24))
        self.assertIn("no PRODUCT heading", str(stop.exception))

    def test_a_table_without_allergens_still_stops(self):
        with self.assertRaises(SystemExit):
            list(nero.drink_rows(Page([("PRODUCT", 100), ("DIETARY", 380)], 180), 24))


class AllergenTableCrossCheck(unittest.TestCase):
    """The allergen table is a second source for some food: where it marks gluten and the ingredients name none, the
    item goes on the Avoid list; an item only the table lists is placed by the table alone."""

    def build(self, food, grid):
        from unittest import mock
        pdf = mock.MagicMock()
        pdf.__enter__.return_value.pages = [object(), object()]
        with mock.patch.object(nero, "newest_pdf", lambda folder: Path("g.pdf")), \
                mock.patch.object(nero.pdfplumber, "open", lambda p: pdf), \
                mock.patch.object(nero, "kind_of", lambda page: "food" if page is pdf.__enter__.return_value.pages[0] else "grid"), \
                mock.patch.object(nero, "food_rows", lambda page, n, section: iter(food)), \
                mock.patch.object(nero, "grid_rows", lambda page, n: grid), \
                mock.patch.object(nero, "page_notices", lambda pdf, pages: []), \
                mock.patch.object(nero, "guide_info", lambda pdf: {"title": "x", "runs": None, "version": "2026-01-01"}), \
                mock.patch.multiple(nero, MIN_FOOD=0, MIN_DRINKS=0):
            out = nero.build("x", {})
        return {i["name"]: i for i in out["items"]}, {a["name"]: a for a in out["avoid"]}, out["warnings"]

    def test_the_table_marking_gluten_moves_food_to_avoid(self):
        food = [(1, "Cakes", "Lemon Slice", "sugar, butter (MILK)"), (1, "Cakes", "Apple Pie", "WHEAT flour, apples")]
        ok, avoid, warnings = self.build(food, [("CAKES", "Lemon Slice", True, 2), ("CAKES", "Apple Pie", False, 2),
                                                ("SAUCES", "Caramel Sauce", True, 2), ("SAUCES", "Vanilla Syrup", False, 2)])
        self.assertEqual(sorted(ok), ["Vanilla Syrup"])
        self.assertEqual(avoid["Lemon Slice"]["gluten"], ["GLUTEN"])  # the table wins over clean ingredients
        self.assertIn("treats it as containing gluten", avoid["Lemon Slice"]["decided"])
        self.assertEqual(avoid["Apple Pie"]["gluten"], ["WHEAT"])  # clean in the table, but the ingredients name wheat
        self.assertEqual(avoid["Caramel Sauce"]["gluten"], ["GLUTEN"])  # only in the table: placed by it alone
        self.assertTrue(any("Lemon Slice" in w for w in warnings) and any("Apple Pie" in w for w in warnings))


class Likeness(unittest.TestCase):
    """How surely an allergen-table name and a food page's name are one product: an exact name wins, a close spelling
    counts, and one word inside another only counts within its own section ("Cinnamon" isn't the "Cinnamon Bun")."""

    def test_exact_close_and_one_word(self):
        self.assertEqual(nero.likeness("Lemon Slice", "lemon slice", False), 10)
        self.assertGreater(nero.likeness("Banan and Walnut Loaf Cake", "Banana and Walnut Loaf Cake", False), 0)
        self.assertEqual(nero.likeness("Cinnamon", "Cinnamon Bun", False), 0)
        self.assertGreater(nero.likeness("Cinnamon", "Cinnamon Bun", True), 0)
        self.assertEqual(nero.likeness("Carrot Cake", "Chocolate Brownie", True), 0)

    def test_a_close_match_is_logged_and_an_item_only_in_the_table_is_left_alone(self):
        food = [(1, "Cakes", "Banana and Walnut Loaf Cake", "sugar, butter (MILK)")]
        grid = [("CAKES", "Banan and Walnut Loaf Cake", True, 2), ("SAUCES", "Caramel Sauce", False, 2),
                ("SAUCES", "Caramel Sauce Drizzle", True, 2)]
        ok, avoid, warnings = AllergenTableCrossCheck.build(AllergenTableCrossCheck(), food, grid)
        self.assertIn("Banana and Walnut Loaf Cake", avoid)  # matched despite the typo, and the table marks gluten
        self.assertTrue(any("read as 'Banana and Walnut Loaf Cake'" in w for w in warnings), warnings)
        # an item only the table lists isn't matched by a later table row: each stands on its own
        self.assertIn("Caramel Sauce", ok)
        self.assertIn("Caramel Sauce Drizzle", avoid)


if __name__ == "__main__":
    unittest.main()
