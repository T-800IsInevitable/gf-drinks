"""
Food or drink for every row (build.set_courses), so the app can show a restaurant's food and its drinks apart and count
each: "Food 104 · Drinks 114" rather than one total that is mostly drinks.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build  # noqa: E402

CONFIG = {"courses": {"drinks": ["Coffee", "Syrups"], "food": ["Breakfast", "Dips"], "addons": ["Syrups", "Dips"],
                     "mixed": ["Snacks & Bottled Drinks"]}}


def menu(items, avoid=()):
    return {"items": [dict(i) for i in items], "avoid": [dict(a) for a in avoid],
            "stats": {"rows": len(items) + len(avoid), "items": len(items), "avoid": len(avoid)}}


class Courses(unittest.TestCase):
    def test_sections_decide_and_addons_and_parts_are_left_out_of_the_counts(self):
        d = menu([{"name": "Latte", "section": "Coffee"}, {"name": "Vanilla", "section": "Syrups"},
                  {"name": "Toast", "section": "Breakfast"}, {"name": "Salsa", "section": "Dips"},
                  {"name": "Bun", "section": "Breakfast", "role": "part"}],
                 [{"name": "Mocha", "section": "Coffee", "gluten": ["OAT"]}])
        build.set_courses(d, CONFIG, "x")
        self.assertEqual([(i["name"], i["course"], i.get("addon", False)) for i in d["items"] + d["avoid"]], [
            ("Latte", "drink", False), ("Vanilla", "drink", True), ("Toast", "food", False), ("Salsa", "food", True),
            ("Bun", "food", False), ("Mocha", "drink", False)])
        self.assertEqual((d["stats"]["food"], d["stats"]["drinks"]), (1, 1))  # Toast and Latte: things to order

    def test_a_mixed_section_is_sorted_by_the_first_food_or_drink_word(self):
        names = {"Kettle Lightly Salted Crisps": "food", "Cloudy Apple Juice": "drink", "One Water (Still/ Sparkling)": "drink",
                 "Starbucks® Chocolate Gold Coin": "food", "Ginger shot": "drink", "Karma Organic Cola": "drink",
                 "Starbucks® Iced Gingerbread Cookie - Bearista or Latte": "both", "Strawberry and Watermelon Vitwater": "drink",
                 "Starbucks Tripleshot™ Espresso": "drink", "Peach Iced Tea": "drink"}
        d = menu([{"name": n, "section": "Snacks & Bottled Drinks"} for n in names])
        build.set_courses(d, CONFIG, "x")
        self.assertEqual({i["name"]: i["course"] for i in d["items"]}, names)

    def test_a_mixed_item_with_no_food_or_drink_word_stops_the_build(self):
        with self.assertRaises(SystemExit):
            build.set_courses(menu([{"name": "Mystery Thing", "section": "Snacks & Bottled Drinks"}]), CONFIG, "x")

    def test_a_named_item_overrides_its_section(self):
        cfg = {"courses": {"food": ["Extras", "Kids"], "items": {"Extras|Whipped Cream": "drink", "Kids|Semi-skimmed Milk": "drink"}}}
        d = menu([{"name": "Whipped Cream", "section": "Extras"}, {"name": "Jam", "section": "Extras"},
                  {"name": "Semi-skimmed Milk", "section": "Kids"}])
        build.set_courses(d, cfg, "x")
        self.assertEqual([i["course"] for i in d["items"]], ["drink", "food", "drink"])

    def test_more_drink_and_food_words(self):
        names = {"Cappuccino": "drink", "Flat White": "drink", "Americano Black": "drink", "Little Sausage Sandwich": "food",
                 "Hot Chocolate": "drink", "Milk Chocolate Buttons": "food", "Semi-skimmed Milk": "drink",
                 # a drink named after a food shows under both halves, so it's never hidden from Drinks
                 "Chocolate Milkshake": "both", "Cookie Frappe": "both"}
        d = menu([{"name": n, "section": "Snacks & Bottled Drinks"} for n in names])
        build.set_courses(d, CONFIG, "x")
        self.assertEqual({i["name"]: i["course"] for i in d["items"]}, names)

    def test_a_section_in_neither_list_shows_under_both_and_warns(self):
        # a new guide's section the setting doesn't name (seasonal drinks, say) is never hidden from either half
        d = menu([{"name": "Gingerbread Frappuccino", "section": "Winter Warmers"}, {"name": "Toast", "section": "Breakfast"}],
                 [{"name": "Matcha Cookie Latte", "section": "Winter Warmers", "gluten": ["WHEAT"]}])
        with mock.patch("builtins.print") as out:
            build.set_courses(d, CONFIG, "x")
        self.assertEqual([r["course"] for r in d["items"] + d["avoid"]], ["both", "food", "both"])
        self.assertIn("Winter Warmers", " ".join(str(c) for c in out.call_args_list))
        self.assertEqual((d["stats"]["food"], d["stats"]["drinks"]), (2, 1))  # counted in each half it shows in

    def test_no_setting_means_both_halves_and_a_gone_section_only_warns(self):
        # a new restaurant added without a courses setting: nothing hidden from either half until it gets one
        d = menu([{"name": "Flat White", "section": "Coffee"}], [{"name": "Oat Latte", "section": "Coffee", "gluten": ["OAT"]}])
        with mock.patch("builtins.print") as out:
            build.set_courses(d, {}, "x")
        self.assertEqual([r["course"] for r in d["items"] + d["avoid"]], ["both", "both"])
        self.assertEqual((d["stats"]["food"], d["stats"]["drinks"]), (1, 1))
        self.assertIn("Coffee", " ".join(str(c) for c in out.call_args_list))
        build.set_courses(menu([{"name": "Burger", "section": "Burgers"}]), {"courses": {"drinks": ["Festive"]}}, "x")  # no stop


if __name__ == "__main__":
    unittest.main()
