"""
tools/check.py: the rules every built menu must keep (an end date, nothing marked as gluten on the list, counts that
match) and the rules for a city in site/cities.json (real dates, a real time zone, bounds the size of a city, times of
day, and an empty list of places only with a sentence to show instead).

The dates are built from today, because "not after today" depends on the day the check runs.

Run: python -m unittest discover -s tests
"""
import copy
import json
import sys
import tempfile
import unittest
import zoneinfo
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check  # noqa: E402

DAY = timedelta(days=1)
TODAY = date.today()


def menu(**changes):
    """A small menu that passes every rule, with changes on top."""
    m = {"items": [{"name": "Latte", "section": "Drinks", "order": "asis"}],
         "avoid": [{"name": "Carrot Cake", "section": "Food", "gluten": ["WHEAT"]}],
         "hash": "abc", "guide": {"validUntil": "2027-01-01"}, "stats": {"rows": 2, "items": 1, "avoid": 1}}
    m.update(changes)
    return m


def menu_errors(m):
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp)
        (site / "data" / "r").mkdir(parents=True)
        (site / "data" / "r" / "x.json").write_text(json.dumps(m), encoding="utf-8")
        errors = []
        with mock.patch.object(check, "SITE", site):
            check.check_restaurant({"id": "x", "file": "data/r/x.json", "hash": "abc"}, errors.append)
    return errors


class MenuRules(unittest.TestCase):
    def test_the_small_menu_passes(self):
        self.assertEqual(menu_errors(menu()), [])

    def test_a_guide_with_no_readable_end_date_fails(self):
        for bad in (None, "", "27 October 2026", "2026-02-30", "0000-00-00"):
            errors = menu_errors(menu(guide={"validUntil": bad}))
            self.assertEqual(len(errors), 1, (bad, errors))
            self.assertIn("no end date", errors[0])
        self.assertIn("no end date", menu_errors(menu(guide={}))[0])

    def test_each_guide_of_a_merged_menu_needs_its_end_date(self):
        guides = [{"validUntil": "2027-01-01", "source": "a.pdf"}, {"validUntil": None, "source": "b.pdf"}]
        errors = menu_errors(menu(guides=guides))
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("guide 2 has no end date", errors[0])
        guides[1]["validUntil"] = "2027-02-01"
        self.assertEqual(menu_errors(menu(guides=guides)), [])

    def test_a_row_marked_as_gluten_cant_be_on_the_list(self):
        for extra in ({"gluten": ["WHEAT"]}, {"tag": "May contain gluten"}, {"reason": "Contains wheat."}):
            errors = menu_errors(menu(items=[{"name": "Latte", "section": "Drinks", "order": "asis", **extra}]))
            self.assertEqual(len(errors), 1, (extra, errors))
            self.assertIn("carries an Avoid row's", errors[0])
        # an empty gluten list and a reason that isn't about containing something are what a listed row may carry
        self.assertEqual(menu_errors(menu(items=[{"name": "Latte", "section": "Drinks", "order": "asis", "gluten": []}])), [])

    def test_an_option_cant_be_both_fine_and_to_avoid(self):
        item = {"name": "Latte", "section": "Drinks", "order": "except", "ok": ["whole", "soya"], "not": ["soya"]}
        errors = menu_errors(menu(items=[item]))
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("['soya'] are among both", errors[0])

    def test_a_swaps_standard_option_cant_be_a_fine_one(self):
        item = {"name": "Latte", "section": "Drinks", "order": "swap", "ok": ["whole", "soya"], "not": ["almond"], "standard": "soya"}
        errors = menu_errors(menu(items=[item]))
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("standard option 'soya'", errors[0])
        self.assertEqual(menu_errors(menu(items=[{**item, "standard": "almond"}])), [])

    def test_an_avoid_row_carries_no_way_to_order_it(self):
        errors = menu_errors(menu(avoid=[{"name": "Carrot Cake", "section": "Food", "gluten": ["WHEAT"], "order": "asis"}]))
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("carries a way to order it", errors[0])

    def test_an_empty_avoid_list_fails(self):
        errors = menu_errors(menu(avoid=[], stats={"rows": 1, "items": 1, "avoid": 0}))
        self.assertEqual(errors, ["x: nothing on the Avoid list"])

    def test_the_counts_must_match_the_lists(self):
        self.assertIn("don't match the lists", menu_errors(menu(stats={"rows": 2, "items": 2, "avoid": 1}))[0])
        self.assertIn("don't match the lists", menu_errors(menu(stats={"rows": 2, "items": 1, "avoid": 0}))[0])
        # an ingredient listed on its own is counted apart from the things to order
        items = [{"name": "Latte", "section": "Drinks", "order": "asis"},
                 {"name": "Whole Milk", "section": "Milks", "order": "asis", "role": "ingredient"}]
        self.assertEqual(menu_errors(menu(items=items, stats={"rows": 3, "items": 1, "ingredients": 1, "avoid": 1})), [])
        self.assertEqual(len(menu_errors(menu(items=items, stats={"rows": 3, "items": 1, "avoid": 1}))), 1)


def city(**changes):
    """A city that passes every rule (checked ten days ago), with changes on top."""
    c = {"name": "Testville", "language": "de", "checked": (TODAY - 10 * DAY).isoformat(), "country": "Testland",
         "timeZone": "Europe/Berlin", "recheckDays": 90, "sections": ["Cafés"],
         "bounds": {"lat": [52.3, 52.7], "lon": [13.0, 13.8]}, "tips": ["x"], "list": {"url": "https://example.de", "by": "someone"},
         "places": [{"name": "A", "section": "Cafés", "claim": "place-all", "says": {"lang": "en", "text": "all gf"},
                     "status": "confirmed", "url": "https://a.example",
                     "locations": [{"address": "1 Street", "area": "Mitte", "lat": 52.5, "lon": 13.4}]}]}
    c.update(copy.deepcopy(changes))
    return c


def city_errors(c):
    errors = []
    check.check_city("testville", c, {"de": {}}, errors.append)
    return errors


def with_place(**changes):
    c = city()
    c["places"][0].update(copy.deepcopy(changes))
    return c


def with_location(**changes):
    c = city()
    c["places"][0]["locations"][0].update(copy.deepcopy(changes))
    return c


class CityRules(unittest.TestCase):
    def one(self, c, words):
        errors = city_errors(c)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn(words, errors[0])

    def test_the_city_passes(self):
        self.assertEqual(city_errors(city()), [])
        self.assertEqual(city_errors(city(checked=TODAY.isoformat())), [])

    def test_checked_must_be_a_real_date_not_after_today(self):
        for bad in (TODAY.strftime("%d/%m/%Y"), (TODAY + 3 * DAY).isoformat(), (TODAY + 366 * DAY).isoformat(),
                    f"{TODAY.year - 1}-02-30", f"{TODAY.year - 1}-13-01"):
            self.one(city(checked=bad), "must be a real date")

    def test_a_places_own_checked_date_isnt_after_today_either(self):
        self.assertEqual(city_errors(with_place(checked=TODAY.isoformat())), [])
        self.one(with_place(checked=(TODAY + 3 * DAY).isoformat()), "is after today")
        self.one(with_place(checked=(TODAY - 11 * DAY).isoformat()), "isn't a date on or after the city's")
        self.one(with_place(checked=f"{TODAY.year + 1}-02-30"), "isn't a date on or after the city's")

    def test_recheck_days_is_a_whole_number_of_days(self):
        for bad in ("90", 0, -5, 500, 90.5, True, None):
            self.one(city(recheckDays=bad), "recheckDays")
        c = city()
        del c["recheckDays"]  # the app and the reminders have their own default
        self.assertEqual(city_errors(c), [])

    def test_every_city_needs_a_time_zone_the_phone_knows(self):
        c = city()
        del c["timeZone"]
        self.one(c, "missing timeZone")
        if check.zone_known("Europe/London") is None:
            self.skipTest("no time zone list on this computer")
        self.one(city(timeZone="Europe/Berlinn"), "isn't a time zone name")
        self.one(city(timeZone="Berlin time"), "isn't a time zone name")
        self.one(city(group="uk", bounds={"lat": [53.9, 54.02], "lon": [-1.2, -0.98]}, timeZone="Europe/Paris",
                      places=[]) | {"none": "No places found yet."}, "must be Europe/London")

    def test_without_a_time_zone_list_the_zone_isnt_judged(self):
        with mock.patch.object(check.zoneinfo, "ZoneInfo", side_effect=zoneinfo.ZoneInfoNotFoundError("none here")):
            self.assertIsNone(check.zone_known("Europe/Berlinn"))
            self.assertEqual(city_errors(city(timeZone="Europe/Berlinn")), [])

    def test_bounds_are_a_box_the_size_of_a_city(self):
        self.one(city(bounds={"lat": [-90, 90], "lon": [13.0, 13.8]}), "span more than")
        self.one(city(bounds={"lat": [52.3, 52.7], "lon": [12.0, 13.8]}), "span more than")
        self.one(city(bounds={"lat": [52.7, 52.3], "lon": [13.0, 13.8]}), "must run from low to high")
        for bad in ({"lat": ["52.3", "52.7"], "lon": [13.0, 13.8]}, {"lat": [52.3, 52.7]}, {"lat": [52.3], "lon": [13.0, 13.8]},
                    [52.3, 52.7, 13.0, 13.8], {"lat": [True, 52.7], "lon": [13.0, 13.8]}):
            self.one(city(bounds=bad), "bounds must be")

    def test_a_uk_citys_bounds_are_in_the_uk(self):
        york = {"group": "uk", "timeZone": "Europe/London", "bounds": {"lat": [53.9, 54.02], "lon": [-1.2, -0.98]}}
        c = city(**york)
        c["places"][0].update({"says": {"lang": "en", "text": "all gf"}})
        c["places"][0]["locations"][0].update({"lat": 53.96, "lon": -1.08})
        self.assertEqual(city_errors(c), [])
        # lat and lon swapped in both the bounds and the place: the place sits "inside", so only the bounds can tell
        c["bounds"] = {"lat": [-1.2, -0.98], "lon": [53.9, 54.02]}
        c["places"][0]["locations"][0].update({"lat": -1.08, "lon": 53.96})
        errors = city_errors(c)
        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(all("aren't in the UK" in e for e in errors), errors)

    def test_coordinates_are_numbers_inside_the_bounds(self):
        self.one(with_location(lat="52.5"), "lat and lon must be numbers")
        self.one(with_location(lon=True), "lat and lon must be numbers")
        self.one(with_location(lat=48.1), "has no coordinates inside testville")
        c = with_location()
        del c["places"][0]["locations"][0]["lat"]
        self.one(c, "has no coordinates inside testville")

    def test_opening_hours_are_times_of_day(self):
        week = lambda x: [x] + ["10:00–17:00"] * 6
        for good in ("10:00–17:00", "9:00–24:00", "00:00–23:59", "12:00–14:30, 17:00–21:30", "", None):
            self.assertEqual(city_errors(with_location(hours=week(good))), [], good)
        for bad in ("29:00–99:99", "10:00–71:00", "10:00–17:60", "10:00–24:30", "24:00–25:00", "12:00–14:30, 17:00–27:00"):
            self.one(with_location(hours=week(bad)), "isn't a time of day")
        self.one(with_location(hours=week("17:00–10:00")), "closes before it opens")
        self.one(with_location(hours=week("ten till five")), "aren't HH:MM")

    def test_kitchen_closes_is_a_time_of_day(self):
        self.assertEqual(city_errors(with_location(kitchenCloses="21:30")), [])
        for bad in ("99:99", "25:00", "21:60", "9:30", "half nine"):
            self.one(with_location(kitchenCloses=bad), "kitchenCloses")

    def test_a_quote_needs_its_words(self):
        for bad in ({"lang": "en", "text": ""}, {"lang": "en", "text": "  "}, {"lang": "en"}, "all gf"):
            self.one(with_place(says=bad), "says has no text")

    def test_a_city_with_no_places_needs_a_sentence_to_show_instead(self):
        self.assertEqual(city_errors(city(places=[], none="No places found here yet.")), [])
        self.one(city(places=[]), "missing places")
        for bad in ("", "   ", None, ["No places"], True):
            self.one(city(places=[], none=bad), "missing places")
        c = city(none="No places found here yet.")
        del c["places"]  # the list itself must still be there, empty
        self.one(c, "missing places")

    def test_every_other_rule_still_applies_to_a_city_with_no_places(self):
        empty = lambda **changes: city(places=[], none="No places found here yet.", **changes)
        self.one(empty(checked=(TODAY + 3 * DAY).isoformat()), "must be a real date")
        self.one(empty(bounds={"lat": [-90, 90], "lon": [13.0, 13.8]}), "span more than")
        self.one(empty(language="xx"), "no coeliac card")
        self.one(empty(list={"url": "http://example.de", "by": "someone"}), "isn't an https address")
        c = empty()
        del c["timeZone"]
        self.one(c, "missing timeZone")
        for key in ("name", "tips", "sections", "country"):
            c = empty()
            del c[key]
            self.one(c, f"missing {key}")


if __name__ == "__main__":
    unittest.main()
