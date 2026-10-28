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
