"""
The readers' own decisions, on made-up rows that need no PDF: which guide is the newest, how a row is classified
(Pho, PizzaExpress, Blank Street, Greggs, Nando's, Starbucks, a hand-kept menu.csv), and build.py's end dates, merge
and settings. The snapshots hold the same decisions for today's guides; these hold them for any guide.

Run: python -m unittest discover -s tests
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build  # noqa: E402
from adapters import (blank_street_uk_pdf, common, greggs_uk_pdf, manual_csv, nandos_uk_json, pho_uk_pdf,  # noqa: E402
                      pizza_express_uk_pdf, starbucks_uk_food_pdf, starbucks_uk_pdf)


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def fake_pdf(*pages):
    """A PDF as the guide_info functions read it: pages of text."""
    return SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda text=text: text) for text in pages])


class NewestGuide(unittest.TestCase):
    """common.newest_by: the guide's own date decides, never the file's time, and never a guess."""

    def pick(self, versions, keep=None):
        """versions: {file name: version or None}, written in that order (so the last has the latest file time)."""
        with tempfile.TemporaryDirectory() as tmp:
            for n, name in enumerate(versions):
                (Path(tmp) / name).write_bytes(b"")
                os.utime(Path(tmp) / name, (1_700_000_000 + n * 60, 1_700_000_000 + n * 60))
            opened = lambda p: contextlib.nullcontext(Path(p).name)  # the "pdf" is just its file name
            with mock.patch.object(common.pdfplumber, "open", opened):
                return quiet(common.newest_by, tmp, lambda pdf, p: versions[pdf],
                             (lambda pdf: keep(pdf)) if keep else None).name

    def test_the_newest_version_wins_whatever_the_file_times(self):
        self.assertEqual(self.pick({"new.pdf": "2026-10-26", "old.pdf": "2026-09-18"}), "new.pdf")
        self.assertEqual(self.pick({"old.pdf": "2026-09-18", "new.pdf": "2026-10-26"}), "new.pdf")

    def test_two_guides_with_the_same_newest_version_stop_the_build(self):
        with self.assertRaises(SystemExit) as stop:
            self.pick({"guide_V2.pdf": "2026-09-01", "guide_V1.pdf": "2026-09-01"})
        self.assertIn("guide_V1.pdf and guide_V2.pdf both read as version 2026-09-01", str(stop.exception))
        # a tie between older guides doesn't matter: the newest is still plain
        self.assertEqual(self.pick({"a.pdf": "2026-01-01", "b.pdf": "2026-01-01", "c.pdf": "2026-09-01"}), "c.pdf")

    def test_a_guide_whose_date_cant_be_read_stops_the_build_when_there_is_another(self):
        with self.assertRaises(SystemExit) as stop:
            self.pick({"old.pdf": "2026-09-18", "reworded.pdf": None})
        self.assertIn("reworded.pdf: couldn't read its date", str(stop.exception))

    def test_a_single_guide_is_the_one_to_build_even_undated(self):
        # check.py then fails the menu for having no end date, unless the restaurant sets one
        self.assertEqual(self.pick({"only.pdf": None}), "only.pdf")

    def test_another_kind_of_guide_in_the_folder_doesnt_count(self):
        food = lambda name: name.startswith("food")
        self.assertEqual(self.pick({"food-a.pdf": "2026-10-05", "drinks.pdf": None, "food-b.pdf": "2026-10-29"}, keep=food), "food-b.pdf")
        with self.assertRaises(SystemExit):
            self.pick({"food-a.pdf": "2026-10-05", "food-b.pdf": "2026-10-05", "drinks.pdf": "2026-10-26"}, keep=food)

    def test_no_guide_at_all_stops_the_build(self):
        with self.assertRaises(SystemExit):
            self.pick({})

    def test_pizza_express_counts_the_v_number_within_a_month(self):
        v1 = fake_pdf("Allergen Information England September 2026 V1")
        v2 = fake_pdf("Allergen Information England September 2026 V2")
        v10 = fake_pdf("Allergen Information England September 2026 V10")
        october = fake_pdf("Allergen Information England October 2026 V1")
        edition = pizza_express_uk_pdf.edition
        self.assertLess(edition(v1), edition(v2))
        self.assertLess(edition(v2), edition(v10))
        self.assertLess(edition(v10), edition(october))
        self.assertIsNone(edition(fake_pdf("Allergen Information England, autumn")))
        # the published version is still the month alone, so the menu file and its fingerprint don't change
        self.assertEqual(pizza_express_uk_pdf.guide_info(v2), {"title": "Allergen guide", "runs": None, "version": "2026-09-01"})


class EndDates(unittest.TestCase):
    def test_a_season_ends_on_the_last_day_of_its_last_month(self):
        self.assertEqual(build.end_date("September to November 2026"), "2026-11-30")
        self.assertEqual(build.end_date("November 2026 to January 2027"), "2027-01-31")
        self.assertEqual(build.end_date("January to February 2028"), "2028-02-29")
        for none in (None, "", "Autumn 2026", "Foo to Bar 2026"):
            self.assertIsNone(build.end_date(none))

    def test_a_guide_with_no_season_is_looked_at_again_after_recheck_days(self):
        self.assertEqual(common.valid_until("2026-10-01", {}), "2026-12-31")
        self.assertEqual(common.valid_until("2026-10-01", {"recheckDays": 30}), "2026-10-31")
        self.assertIsNone(common.valid_until(None, {"recheckDays": 30}))

    def test_starbucks_reads_a_season_that_crosses_the_new_year(self):
        cover = "Holiday 2026 {}\nNutrition & Allergen Guide\n{}\nVersion: 26/10/26"
        for reader, kind in ((starbucks_uk_pdf, "Beverages"), (starbucks_uk_food_pdf, "Food")):
            info = reader.guide_info(fake_pdf(cover.format(kind, "November 2026 - January 2027")))
            self.assertEqual(info["runs"], "November 2026 to January 2027", kind)
            self.assertEqual(info["version"], "2026-10-26")
            self.assertEqual(build.end_date(info["runs"]), "2027-01-31")
            info = reader.guide_info(fake_pdf(cover.format(kind, "September – November 2026")))
            self.assertEqual(info["runs"], "September to November 2026", kind)
            self.assertIsNone(reader.guide_info(fake_pdf(cover.format(kind, "All year")))["runs"])


class Merge(unittest.TestCase):
    def part(self, name, until):
        return {"source": f"{name}.pdf", "guide": {"title": name, "validUntil": until}, "rule": f"{name} rule.", "sections": [name],
                "items": [{"name": f"{name} item", "section": name}], "avoid": [{"name": f"{name} avoid", "section": name}],
                "stats": {"rows": 2, "items": 1, "avoid": 1}}

    def test_a_merged_menu_is_out_of_date_when_its_first_guide_to_end_is(self):
        out = build.merge([self.part("drinks", "2027-01-31"), self.part("food", "2026-12-15")])
        self.assertEqual(out["guide"]["validUntil"], "2026-12-15")
        self.assertEqual([g["validUntil"] for g in out["guides"]], ["2027-01-31", "2026-12-15"])
        self.assertEqual(out["source"], "drinks.pdf and food.pdf")
        self.assertEqual(out["stats"], {"rows": 4, "items": 2, "avoid": 2})
        self.assertEqual([(r["name"], r["src"]) for r in out["items"] + out["avoid"]],
                         [("drinks item", 0), ("food item", 1), ("drinks avoid", 0), ("food avoid", 1)])

    def test_one_guide_is_left_as_it_is(self):
        part = self.part("drinks", "2027-01-31")
        self.assertIs(build.merge([part]), part)


class Settings(unittest.TestCase):
    def data(self):
        return {"items": [{"name": "Hot Dog", "section": "Meat"}, {"name": "Whole Milk", "section": "Milks"}],
                "avoid": [{"name": "Hot Dog", "section": "Hot Dogs"}], "stats": {"rows": 3, "items": 2, "avoid": 1}}

    def test_a_rename_and_a_role_are_applied(self):
        d = self.data()
        build.apply_config(d, {"rename": {"Meat|Hot Dog": "Hot dog sausage"}, "roles": {"Milks": "ingredient", "Meat|Hot dog sausage": "part"}}, "x")  # a role is matched after the rename
        self.assertEqual([(i["name"], i.get("role")) for i in d["items"]], [("Hot dog sausage", "part"), ("Whole Milk", "ingredient")])
        self.assertEqual(d["avoid"][0]["name"], "Hot Dog")
        self.assertEqual(d["stats"], {"rows": 3, "items": 1, "avoid": 1, "ingredients": 1})

    def test_a_setting_that_matches_nothing_stops_the_build(self):
        for config in ({"rename": {"Meat|Sausage": "Hot dog sausage"}}, {"roles": {"Toppings": "part"}},
                       {"roles": {"Milks|Oat": "ingredient"}}, {"roles": {"Milks": "garnish"}}):
            with self.assertRaises(SystemExit, msg=config):
                build.apply_config(self.data(), config, "x")


class HandKeptMenu(unittest.TestCase):
    HEAD = "section,name,order,ok,not,standard,contains,note,page\n"

    def build(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "menu.csv").write_text(self.HEAD + rows, encoding="utf-8")
            return manual_csv.build(tmp, {"guide": {"source": "guide.pdf", "version": "2026-01-01"}})

    def test_each_order_lands_in_its_list(self):
        out = self.build("Drinks,Hot Chocolate,asis,,,,,,1\n"
                         "Drinks,Latte,except,whole;soya,oat,,,,1\n"
                         "Drinks,Oat Flat White,swap,whole,oat,,,,1\n"
                         "Food,Soup,modify,,,,,No wheat croutons,2\n"
                         "Food,Brownie,avoid,,,,wheat;barley,,2\n"
                         "Food,Flapjack,avoid,,,,,,2\n"
                         "Food,Cannoli,doubt,,,,,The shell is usually wheat.,2\n")
        self.assertEqual([(i["name"], i["order"]) for i in out["items"]],
                         [("Hot Chocolate", "asis"), ("Latte", "except"), ("Oat Flat White", "swap"), ("Soup", "modify")])
        self.assertEqual(out["items"][2]["standard"], "oat")
        self.assertEqual(out["items"][3]["note"], "No wheat croutons")  # a change to ask for may name the cereal it leaves out
        avoid = {a["name"]: a for a in out["avoid"]}
        self.assertEqual(avoid["Brownie"]["gluten"], ["WHEAT", "BARLEY"])
        self.assertEqual(avoid["Flapjack"]["gluten"], ["GLUTEN"])  # an Avoid row with nothing named still says why
        # the app's own doubt goes on the Avoid list, labelled as the app's, never on the list with a note
        self.assertEqual(avoid["Cannoli"], {"name": "Cannoli", "section": "Food", "sub": None, "pages": ["2"], "gluten": [],
                                            "tag": "Check in store", "reason": "Note from this app: The shell is usually wheat."})
        self.assertFalse(any("order" in a for a in out["avoid"]))
        self.assertEqual(out["stats"], {"rows": 7, "items": 4, "avoid": 3})

    def test_a_row_the_reader_cant_place_stops_the_build(self):
        for rows in ("Drinks,Latte,fine,,,,,,1\n",          # not one of the orders
                     "Drinks,Latte,,,,,,,1\n",              # no order at all
                     "Drinks,Latte,swap,,oat,,,,1\n",       # a swap with nothing to swap to
                     "Drinks,Latte,any,,,,,,1\n",
                     "Food,Soup,modify,,,,,,2\n",           # a change with no words for it
                     "Food,Cannoli,doubt,,,,,,2\n",         # a doubt with no reason
                     "Food,Lemon drizzle,asis,,,,wheat,,2\n",            # what it contains, on a row listed as fine
                     "Food,Flapjack,asis,,,,,Made with rolled oats,2\n",  # a note naming a cereal on a listed row
                     ""):                                   # nothing at all
            with self.assertRaises(SystemExit, msg=rows):
                self.build(rows)


class Pho(unittest.TestCase):
    def classify(self, **marks):
        r = {"note": False, "name": "Pho Bo", "section": "Pho", "sub": None, "page": 3, "sectionOriginal": None, "star": False,
             "footnotes": [], "labels": [], "marks": [], "pink": False, **marks}
        warnings = []
        kind, item = pho_uk_pdf.classify(r, {}, warnings)
        return kind, item, warnings

    def test_a_clean_gluten_column_is_listed(self):
        kind, item, warnings = self.classify()
        self.assertEqual((kind, item["order"], warnings), ("ok", "asis", []))

    def test_a_dot_is_avoid_unless_the_guide_says_it_can_be_removed(self):
        kind, item, _ = self.classify(marks=["dot"])
        self.assertEqual((kind, item["gluten"]), ("avoid", ["GLUTEN"]))
        kind, item, _ = self.classify(marks=["dot"], labels=["wheat", "barley"])
        self.assertEqual((kind, item["gluten"]), ("avoid", ["BARLEY", "WHEAT"]))
        kind, item, _ = self.classify(marks=["dot"], pink=True)
        self.assertEqual((kind, item["order"], item["note"]), ("ok", "modify", "Without gluten, please"))
        self.assertNotIn("gluten", item)

    def test_a_shared_fryer_mark_is_avoid_even_on_pink(self):
        for marks in (["fried"], ["dot", "fried"]):
            for pink in (False, True):
                kind, item, _ = self.classify(marks=marks, pink=pink)
                self.assertEqual((kind, item["tag"]), ("avoid", "Shared fryer"), (marks, pink))

    def test_two_dots_on_pink_isnt_the_removable_case(self):
        kind, item, _ = self.classify(marks=["dot", "dot"], pink=True)
        self.assertEqual(kind, "avoid")

    def test_a_cereal_word_or_a_pink_cell_without_a_mark_is_avoid(self):
        kind, item, warnings = self.classify(labels=["wheat"])
        self.assertEqual((kind, item["gluten"]), ("avoid", ["WHEAT"]))
        self.assertIn("without its usual mark", item["decided"])
        self.assertEqual(len(warnings), 1)
        kind, item, warnings = self.classify(pink=True)
        self.assertEqual((kind, item["gluten"], len(warnings)), ("avoid", ["GLUTEN"], 1))

    def test_a_note_row_is_not_a_dish(self):
        self.assertEqual(self.classify(note=True)[:2], ("note", None))


class PizzaExpress(unittest.TestCase):
    def classify(self, name="Pollo Salad", gluten=(), coeliacs=True, **more):
        marks = {**({"gluten": set(gluten)} if gluten else {}), **({"coeliacs": {"tick"}} if coeliacs else {})}
        r = {"name": name, "section": "Salads", "page": 4, "marks": marks, "gluten_words": "", "across": "", "note": "", **more}
        warnings = []
        kind, item = pizza_express_uk_pdf.classify(r, [], warnings)
        return kind, item, warnings

    def test_no_gluten_mark_and_ticked_for_coeliacs_is_listed(self):
        kind, item, warnings = self.classify()
        self.assertEqual((kind, item["order"], warnings), ("ok", "asis", []))

    def test_no_coeliac_tick_is_avoid_even_with_no_gluten_mark(self):
        kind, item, _ = self.classify(coeliacs=False)
        self.assertEqual((kind, item["tag"], item["gluten"]), ("avoid", "Not marked for coeliacs", []))
        self.assertTrue(item["reason"])

    def test_a_gluten_mark_is_avoid_even_when_ticked_for_coeliacs(self):
        kind, item, warnings = self.classify(gluten={"tick"}, gluten_words="Wheat")
        self.assertEqual((kind, item["gluten"], item["reason"]), ("avoid", ["WHEAT"], "Contains wheat."))
        self.assertIn("ticks this as suitable for coeliacs but also marks gluten", item["decided"])
        self.assertEqual(len(warnings), 1)
        kind, item, _ = self.classify(gluten={"star"}, coeliacs=False)
        self.assertEqual((kind, item["gluten"], item["tag"]), ("avoid", ["GLUTEN"], "May contain gluten"))

    def test_a_gluten_mark_is_listed_only_with_the_change_the_guide_gives(self):
        kind, item, _ = self.classify(gluten={"tick"}, coeliacs=False, note="Suitable for coeliacs on a gluten-free base")
        self.assertEqual((kind, item["order"], item["note"]), ("ok", "modify", "On the GF base, please"))
        self.assertIn('PizzaExpress says: "Suitable for coeliacs on a gluten-free base"', item["info"])
        # the words alone, with no change to ask for, change nothing
        kind, item, _ = self.classify(gluten={"tick"}, coeliacs=False, note="Suitable for coeliacs")
        self.assertEqual(kind, "avoid")

    def test_cannot_guarantee_is_avoid_whatever_the_ticks(self):
        kind, item, _ = self.classify(across="We cannot guarantee any allergen or dietary requirements")
        self.assertEqual((kind, item["tag"], item["gluten"]), ("avoid", "Not guaranteed", ["GLUTEN"]))
        self.assertTrue(item["reason"].startswith('The guide says: "'))

    def test_oat_in_the_name_is_avoid_whatever_the_ticks(self):
        kind, item, _ = self.classify(name="Oat Flat White")
        self.assertEqual((kind, item["gluten"], item["tag"]), ("avoid", ["OAT"], "Oats"))


class BlankStreet(unittest.TestCase):
    def classify(self, text):
        return blank_street_uk_pdf.classify({"name": "Flat White", "section": "Coffee", "page": 1, "text": text}, [])

    def test_no_cereal_anywhere_is_listed(self):
        kind, item = self.classify("Grounded Coffee Bean, Water. Vegan, Vegetarian, Contains Caffeine")
        self.assertEqual((kind, item["order"]), ("ok", "asis"))

    def test_a_may_contain_line_is_avoid(self):
        for may, code in (("Oat (Gluten)", "OAT"), ("Cereals containing Gluten", "GLUTEN"), ("Wheat", "WHEAT")):
            kind, item = self.classify(f"MILK, Water, Grounded Coffee Bean. May Contain - {may} | Vegetarian")
            self.assertEqual((kind, item["gluten"], item["tag"]), ("avoid", [code], "May contain gluten"), may)
            self.assertTrue(item["reason"].startswith("May contain"), item["reason"])
        kind, item = self.classify("MILK, Water. May Contain - Nuts | Vegetarian")
        self.assertEqual(kind, "ok")

    def test_milk_versions_are_judged_one_by_one(self):
        oat = "With OAT: OAT Drink [(Water, OAT/GLUTEN (10%))], Grounded Coffee Bean. May Contain - Milk | Vegan"
        kind, item = self.classify("With DAIRY: MILK, Water, Grounded Coffee Bean. Vegetarian " + oat)
        self.assertEqual((kind, item["order"], item["ok"], item["not"]), ("ok", "except", ["dairy"], ["oat"]))
        # the guide's real Flat White: the dairy version may contain oats, so no version is fine
        kind, item = self.classify("With DAIRY: MILK, Water, Grounded Coffee Bean. May Contain - Oat (Gluten) | Vegetarian " + oat)
        self.assertEqual((kind, item["gluten"], item["tag"]), ("avoid", ["OAT"], "May contain gluten"))
        self.assertNotIn("order", item)

    def test_versions_that_dont_belong_to_one_drink_stop_the_build(self):
        for text in ("With DAIRY: MILK, Water. With DAIRY: MILK, Cocoa.", "Water, Cocoa. With DAIRY: MILK, Water.", ""):
            with self.assertRaises(SystemExit, msg=text):
                self.classify(text)


class Greggs(unittest.TestCase):
    def classify(self, marks=None, gf=False):
        warnings = []
        kind, item = greggs_uk_pdf.classify({"name": "Sausage Roll", "section": "Savouries", "page": 5, "marks": marks or {}, "gf": gf},
                                            warnings)
        return kind, item, warnings

    def test_no_cereal_mark_is_listed(self):
        for marks in ({}, {"Milk": "tick", "Soya": "bullet"}):
            kind, item, _ = self.classify(marks)
            self.assertEqual((kind, item["order"]), ("ok", "asis"))

    def test_a_tick_or_a_bullet_under_any_cereal_is_avoid(self):
        for head, code in greggs_uk_pdf.CEREALS.items():
            kind, item, _ = self.classify({head: "tick"})
            self.assertEqual((kind, item["gluten"]), ("avoid", [code]), head)
            self.assertTrue(item["reason"].startswith("Contains "))
            self.assertNotIn("tag", item)
            kind, item, _ = self.classify({head: "bullet"})
            self.assertEqual((kind, item["gluten"], item["tag"]), ("avoid", [code], "May contain gluten"), head)

    def test_the_guides_gf_mark_is_quoted_as_greggs_claim_and_loses_to_a_cereal(self):
        kind, item, _ = self.classify(gf=True)
        self.assertEqual(kind, "ok")
        self.assertIn("Greggs calls this gluten free", item["info"])
        kind, item, warnings = self.classify({"Oats": "bullet"}, gf=True)
        self.assertEqual((kind, item["gluten"]), ("avoid", ["OAT"]))
        self.assertIn("this app counts as gluten", item["decided"])
        self.assertEqual(len(warnings), 1)


class Nandos(unittest.TestCase):
    def build(self, *dishes, plain=nandos_uk_json.MIN_DISHES):
        dish = lambda n, **more: {"name": f"Dish {n}", "variant": "", "slug": f"dish-{n}", "category": "Mains", "contains": [],
                                  "mayContain": [], "notes": {}, "ingredients": "Chicken, salt.", "summary": "", "fullTable": True, **more}
        every = [dish(n) for n in range(plain)] + [dish(f"x{n}", **d) for n, d in enumerate(dishes)]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "guides").mkdir()
            (Path(tmp) / "guides" / "nandos-allergens-2026-10-26.json").write_text(
                json.dumps({"fetched": "2026-10-26", "dishes": every}), encoding="utf-8")
            out = quiet(nandos_uk_json.build, tmp, {})
        return ({i["name"]: i for i in out["items"] if i["name"].startswith("Dish x")},
                {a["name"]: a for a in out["avoid"] if a["name"].startswith("Dish x")}, out)

    def test_each_source_of_gluten_is_enough(self):
        ok, avoid, out = self.build(
            {"contains": ["gluten"], "summary": "Contains gluten.", "notes": {"gluten": "Pitta bread contains gluten from wheat."}},
            {"mayContain": ["gluten"]},
            {"summary": "Contains gluten, sesame."},           # the line above the table, which the table doesn't repeat
            {"ingredients": "Wheat flour, water, Oats."},      # no mark at all, but the ingredients name cereals
            {"contains": ["milk"], "summary": "Contains milk.", "ingredients": "Milk, maltodextrin."})
        self.assertEqual(sorted(ok), ["Dish x4"])
        self.assertEqual(avoid["Dish x0"]["reason"], 'Nando\'s says: "Pitta bread contains gluten from wheat."')
        self.assertEqual((avoid["Dish x1"]["tag"], avoid["Dish x1"]["gluten"]), ("May contain gluten", ["GLUTEN"]))
        self.assertEqual(avoid["Dish x2"]["gluten"], ["GLUTEN"])
        self.assertEqual(avoid["Dish x3"]["gluten"], ["OAT", "WHEAT"])
        self.assertIn("so the app treats it as containing gluten", avoid["Dish x3"]["decided"])
        self.assertEqual(len(out["warnings"]), 2)  # the disagreeing summary, and the unmarked ingredients
        self.assertEqual(out["guide"]["version"], "2026-10-26")

    def test_too_few_dishes_or_a_dish_listed_twice_stops_the_build(self):
        with self.assertRaises(SystemExit):
            self.build(plain=nandos_uk_json.MIN_DISHES - 1)
        with self.assertRaises(SystemExit):
            self.build({"name": "Dish 1"})


class Starbucks(unittest.TestCase):
    def read(self, allergens, ingredients, name="Latte - whole milk"):
        r = {"page": 7, "name": name, "allergens": allergens, "ingredients": ingredients}
        warnings = []
        starbucks_uk_pdf.read_gluten(r, warnings, f"p.7 {name}")
        return r["gluten"], r["decided"], warnings

    def test_capitals_in_either_column_are_gluten(self):
        self.assertEqual(self.read("OATS", "OAT drink (water, OATS)"), (["OAT"], None, []))
        gluten, decided, warnings = self.read("MILK", "MILK, WHEAT flour")
        self.assertEqual(gluten, ["WHEAT"])
        self.assertIn("disagree about gluten", decided)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(self.read("MILK", "MILK, coffee, maltodextrin"), ([], None, []))

    def test_a_cereal_word_without_its_capitals_is_still_gluten(self):
        for allergens, ingredients, codes in (("Oats, MILK", "Oat drink (water, oats)", ["OAT"]),
                                              ("MILK", "MILK, Wheat flour, Barley malt extract", ["BARLEY", "MALT", "WHEAT"]),
                                              ("Contains: Oats", "", ["OAT"]),
                                              ("", "Rye flakes", ["RYE"])):
            gluten, decided, warnings = self.read(allergens, ingredients)
            self.assertEqual(gluten, codes, (allergens, ingredients))
            self.assertIn("without its usual capitals, so the app treats it as containing gluten", decided)
            self.assertTrue(any("without the guide's usual capitals" in w for w in warnings), warnings)

    def test_the_backstop_reads_the_two_columns_not_the_name(self):
        # the milk versions of an Oat Shaken Espresso are the one allowed swap: "Oat" in the name isn't an ingredient
        self.assertEqual(self.read("MILK", "MILK, coffee", name="Iced Brown Sugar Oat Shaken Espresso - whole milk"), ([], None, []))
        self.assertEqual(self.read("MILK", "MILK, Gluten free flour blend (rice)")[0], [])

    def test_the_food_reader_uses_the_same_step(self):
        self.assertIs(starbucks_uk_food_pdf.read_gluten, starbucks_uk_pdf.read_gluten)


if __name__ == "__main__":
    unittest.main()
