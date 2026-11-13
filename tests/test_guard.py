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

    def test_a_routine_or_workflow_commit_must_be_on_its_own_kind_of_branch(self):
        # the name is chosen by whoever opens the pull request, so a free-looking name doesn't free a routine's work
        for ref in ("fix/anything", "safeguards", "scan-setup-note"):
            self.assertTrue(guard.scope(ref, ["tools/check.py", ".github/workflows/guard.yml"], machine=True), ref)
            self.assertTrue(guard.scope(ref, ["restaurants/x/menu.csv"], machine=True), ref)
        # on its own branch it keeps that branch's limits, as before
        self.assertEqual(guard.scope("scan/x-2026-10-26", ["restaurants/x/menu.csv"], machine=True), [])
        self.assertTrue(guard.scope("scan/x-2026-10-26", ["tools/check.py"], machine=True))
        self.assertEqual(guard.scope("guide-watch/x-abcdef0123", ["restaurants/x/guides/new.pdf"], machine=True), [])

    def test_who_made_a_commit(self):
        owner = {"commit": {"author": {"email": "someone@example.com"}, "committer": {"email": "someone@example.com"}}, "author": None, "committer": None}
        routine = {"commit": {"author": {"email": "noreply@anthropic.com"}, "committer": {"email": "noreply@anthropic.com"}}, "author": {"login": "claude"}}
        workflow = {"commit": {"author": {"email": "41898282+github-actions[bot]@users.noreply.github.com"}}, "author": {"login": "github-actions[bot]"}}
        dependabot = {"commit": {"author": {"email": "49699333+dependabot[bot]@users.noreply.github.com"}, "committer": {"email": "noreply@github.com"}},
                      "author": {"login": "dependabot[bot]"}, "committer": {"login": "web-flow"}}
        self.assertFalse(guard.machine_made([owner, dependabot]))
        self.assertTrue(guard.machine_made([owner, routine]))
        self.assertTrue(guard.machine_made([workflow]))
        self.assertTrue(guard.machine_made([{"commit": {"author": {"email": "NoReply@Anthropic.com"}}}]))

    def test_the_guide_watch_refusal_says_where_the_fix_goes(self):
        said = guard.scope("guide-watch/pret-uk-abcdef0123", ["restaurants/pret-uk/restaurant.json"])
        self.assertIn("pull request of your own", said[0])

    def test_too_many_commits_to_read_is_refused(self):
        pages = iter([[{}] * 100, [{}] * 100, [{}] * 50])
        with mock.patch.object(guard.gh, "request", side_effect=lambda *a: next(pages)):
            with self.assertRaises(SystemExit):
                guard.commits(7)
        with mock.patch.object(guard.gh, "request", return_value=[{}] * 3):
            self.assertEqual(len(guard.commits(7)), 3)

    def test_a_rename_counts_both_names(self):
        answer = [{"filename": "restaurants/x/menu.csv", "previous_filename": "tools/check.py"}]
        with mock.patch.object(guard.gh, "request", return_value=answer):
            paths = guard.changed(7)
        self.assertEqual(paths, ["restaurants/x/menu.csv", "tools/check.py"])
        self.assertTrue(guard.scope("scan/x-2026-10-28", paths))


if __name__ == "__main__":
    unittest.main()
