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


if __name__ == "__main__":
    unittest.main()
