"""
tools/check.py: every web address in the data must be https (assessment V3), because the app turns them into links.

Run: python -m unittest discover -s tests
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check  # noqa: E402


class Urls(unittest.TestCase):
    def test_only_https_addresses_pass(self):
        errors = []
        data = {"officialUrl": "https://www.pret.co.uk/allergens", "logoUrl": None, "guideFiles": {"a.pdf": "guides/a/a.pdf"},
                "list": {"url": "https://www.example.de/liste", "also": [{"url": "http://example.nl"}]},
                "places": [{"url": "javascript:alert(1)", "listPage": "https://www.example.de/p/1"}]}
        check.check_urls(data, "t", errors.append)
        self.assertEqual(sorted(errors), ["t: list.also.0.url 'http://example.nl' isn't an https address",
                                          "t: places.0.url 'javascript:alert(1)' isn't an https address"])

    def test_a_restaurant_with_a_bad_address_fails_the_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            (site / "data" / "r").mkdir(parents=True)
            menu = {"items": [{"name": "Latte", "section": "Hot drinks", "order": "asis"}], "avoid": [], "hash": "abc",
                    "guide": {"validUntil": "2027-01-01"}, "officialUrl": "javascript:alert(1)"}
            (site / "data" / "r" / "x.json").write_text(json.dumps(menu), encoding="utf-8")
            errors = []
            with mock.patch.object(check, "SITE", site):
                check.check_restaurant({"id": "x", "file": "data/r/x.json", "hash": "abc"}, errors.append)
        self.assertIn("x: officialUrl 'javascript:alert(1)' isn't an https address", errors)

    def test_a_city_with_a_bad_list_address_fails_the_check(self):
        c = {"name": "Testville", "language": "de", "checked": "2026-10-01", "country": "Testland", "sections": ["Cafés"],
             "bounds": {"lat": [0, 1], "lon": [0, 1]}, "tips": ["x"], "list": {"url": "http://example.de", "by": "someone"},
             "places": [{"name": "A", "section": "Cafés", "claim": "place-all", "says": {"lang": "en", "text": "all gf"}, "status": "confirmed",
                         "url": "https://a.example", "locations": [{"address": "1 Street", "area": "Mitte", "lat": 0.5, "lon": 0.5}]}]}
        errors = []
        check.check_city("testville", c, {"de": {}}, errors.append)
        self.assertEqual(errors, ["city testville: list.url 'http://example.de' isn't an https address"])


if __name__ == "__main__":
    unittest.main()
