"""
tools/guard.py: a routine's pull request (scan/, city/, recheck/ branches) may change only its own files.

Run: python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import guard  # noqa: E402


class Scope(unittest.TestCase):
    def test_a_scan_changes_one_restaurant(self):
        self.assertEqual(guard.scope("scan/test-cafe-2026-10-26", ["restaurants/test-cafe/menu.csv", "restaurants/test-cafe/source/x/menu.pdf"]), [])
        self.assertTrue(guard.scope("scan/test-cafe-2026-10-26", ["restaurants/test-cafe/menu.csv", "site/phrases.json"]))
        self.assertTrue(guard.scope("scan/test-cafe-2026-10-26", ["restaurants/test-cafe/menu.csv", "restaurants/pret-uk/menu.csv"]))
        self.assertTrue(guard.scope("scan/x-2026-10-26", ["tools/check.py"]))
        self.assertTrue(guard.scope("scan/x-2026-10-26", [".github/workflows/checks.yml"]))
        self.assertTrue(guard.scope("scan/x-2026-10-26", ["restaurants/README.md"]))

    def test_a_city_changes_only_the_cities(self):
        for ref in ("city/bath-2026-10-28", "recheck/york-2026-11-27"):
            self.assertEqual(guard.scope(ref, ["site/cities.json"]), [])
            self.assertTrue(guard.scope(ref, ["site/cities.json", "site/app.js"]))
            self.assertTrue(guard.scope(ref, ["tools/check.py"]))

    def test_a_scan_changes_only_the_restaurant_its_branch_names(self):
        self.assertTrue(guard.scope("scan/new-cafe-york-2026-11-01", ["restaurants/pret-uk/restaurant.json"]))
        self.assertTrue(guard.scope("scan/new-cafe", ["restaurants/new-cafe/menu.csv"]))
        self.assertEqual(guard.scope("scan/new-cafe-york-2026-11-01", ["restaurants/new-cafe-york/menu.csv"]), [])

    def test_a_look_alike_prefix_is_refused(self):
        for ref in ("Scan/x-2026-10-26", "SCAN/x", "City/bath-2026-10-28", "Guide-Watch/x"):
            self.assertTrue(guard.scope(ref, ["tools/check.py"]), ref)
        # the owner's own branch names, which start with the same words but have no slash, stay free
        for ref in ("city-requests", "scan-setup-note"):
            self.assertEqual(guard.scope(ref, ["tools/check.py"]), [], ref)

    def test_a_retry_suffix_is_allowed(self):
        self.assertEqual(guard.scope("scan/test-cafe-london-2026-10-26-b", ["restaurants/test-cafe-london/menu.csv"]), [])

    def test_a_guide_watch_changes_only_that_restaurants_guides(self):
        ref = "guide-watch/pret-uk-abcdef0123"
        self.assertEqual(guard.scope(ref, ["restaurants/pret-uk/guides/new.pdf", "restaurants/pret-uk/guides/archive/old.pdf"]), [])
        self.assertTrue(guard.scope(ref, ["tools/adapters/pret_uk_pdf.py"]))
        self.assertTrue(guard.scope(ref, ["restaurants/pret-uk/restaurant.json"]))
        self.assertTrue(guard.scope(ref, ["restaurants/greggs-uk/guides/new.pdf"]))

    def test_the_owners_branches_have_no_limit(self):
        self.assertEqual(guard.scope("safeguards", ["tools/check.py", ".github/workflows/guard.yml"]), [])

    def test_a_rename_counts_both_names(self):
        answer = [{"filename": "restaurants/x/menu.csv", "previous_filename": "tools/check.py"}]
        with mock.patch.object(guard.gh, "request", return_value=answer):
            paths = guard.changed(7)
        self.assertEqual(paths, ["restaurants/x/menu.csv", "tools/check.py"])
        self.assertTrue(guard.scope("scan/x-2026-10-28", paths))


if __name__ == "__main__":
    unittest.main()
