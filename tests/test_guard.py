"""
tools/guard.py: a routine's pull request (scan/, city/, recheck/ branches) may change only its own files.

Run: python -m unittest discover -s tests
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import guard  # noqa: E402


class OtherRepository(unittest.TestCase):
    """A pull request from someone else's copy (a fork) isn't the owner's, whatever its commits say."""

    def pull(self, head_repo):
        return {"head": {"repo": {"full_name": head_repo} if head_repo else None}}

    def test_only_this_repository_passes(self):
        self.assertEqual(guard.from_other_repo(self.pull("o/r"), "o/r"), [])
        self.assertTrue(guard.from_other_repo(self.pull("stranger/r"), "o/r"))
        self.assertTrue(guard.from_other_repo(self.pull(None), "o/r"))  # a deleted fork

    def test_main_refuses_a_fork_before_anything_else(self):
        with mock.patch.object(guard.gh, "request", return_value=self.pull("stranger/r")), \
                mock.patch.dict(guard.os.environ, {"HEAD_REF": "patch-1", "PR": "9", "GITHUB_REPOSITORY": "o/r"}), \
                mock.patch.object(guard, "changed", side_effect=AssertionError("judged a fork's files")):
            with self.assertRaises(SystemExit) as stop:
                guard.main()
        self.assertEqual(stop.exception.code, 1)


class HandKeptAvoidSetting(unittest.TestCase):
    """A scan/ branch for a menu kept by hand may change its restaurant.json (the guide's dates live there), but not
    avoidDropOk, which would let it switch off the build's Avoid guard for its own new menu."""

    def test_avoid_drop_ok_may_not_change(self):
        same = guard.avoid_ok_changed("knoops-uk", {"avoidDropOk": "a.pdf", "guide": {"version": "1"}},
                                      {"avoidDropOk": "a.pdf", "guide": {"version": "2"}})
        self.assertEqual(same, [])
        self.assertTrue(guard.avoid_ok_changed("knoops-uk", {}, {"avoidDropOk": "new.pdf"}))
        self.assertTrue(guard.avoid_ok_changed("knoops-uk", {"avoidDropOk": "a.pdf"}, {"avoidDropOk": "b.pdf"}))
        self.assertTrue(guard.avoid_ok_changed("knoops-uk", {"avoidDropOk": "a.pdf"}, {}))
        # avoidDropOk left alone, but the source renamed to match it: the build would accept the drop for this menu
        main_cfg = {"avoidDropOk": "b.pdf", "guide": {"source": "a.pdf"}}
        self.assertTrue(guard.avoid_ok_changed("knoops-uk", main_cfg, {**main_cfg, "guide": {"source": "b.pdf"}}))
        self.assertTrue(guard.avoid_ok_changed("knoops-uk", {"avoidDropOk": "menu.csv", "guide": {"source": "a.pdf"}},
                                               {"avoidDropOk": "menu.csv", "guide": {}}))  # the menu's own name
        # a new source that the existing avoidDropOk doesn't name is fine
        self.assertEqual(guard.avoid_ok_changed("knoops-uk", main_cfg, {**main_cfg, "guide": {"source": "c.pdf"}}), [])

    def test_main_reads_both_copies_for_a_hand_kept_scan(self):
        rj = "restaurants/knoops-uk/restaurant.json"
        answers = {"/pulls/9": {"head": {"sha": "abc", "repo": {"full_name": "o/r"}}},
                   f"/contents/{rj}?ref=abc": {"reader": "manual_csv", "avoidDropOk": "new.pdf"}}
        env = {"HEAD_REF": "scan/knoops-uk-2026-11-20", "PR": "9", "GITHUB_REPOSITORY": "o/r"}
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "restaurants" / "knoops-uk").mkdir(parents=True)
            (Path(tmp) / rj).write_text('{"reader": "manual_csv"}', encoding="utf-8")
            with mock.patch.object(guard, "ROOT", Path(tmp)), mock.patch.dict(guard.os.environ, env), \
                    mock.patch.object(guard.gh, "request", side_effect=lambda m, path, **k: answers[path]), \
                    mock.patch.object(guard, "changed", return_value=["restaurants/knoops-uk/menu.csv", rj]), \
                    mock.patch.object(guard, "commits", return_value=[]), mock.patch("builtins.print") as out:
                with self.assertRaises(SystemExit):
                    guard.main()
        self.assertIn("avoidDropOk", " ".join(str(c) for c in out.call_args_list))


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

    def test_a_scan_for_a_restaurant_a_reader_builds_adds_only_guides_and_sources(self):
        ref, folder = "scan/starbucks-uk-2026-11-15", "restaurants/starbucks-uk/"
        upload = [folder + "guides/WIN_26_UK_AllergenBook_CORE_BEVERAGE_v01.pdf", folder + "guides/archive/old.pdf",
                  folder + "source/2026-11-15-starbucks/upload.json"]
        self.assertEqual(guard.scope(ref, upload, True, reader_built=True), [])
        for path in ("restaurant.json", "menu.csv", "logo.png", "guides.txt", "sourced/x.pdf"):
            said = guard.scope(ref, upload + [folder + path], True, reader_built=True)
            self.assertTrue(said, path)
            self.assertIn(folder + path, said[0])
            self.assertIn("pull request of your own", said[0])
        # another restaurant's guides, and anything outside restaurants/, stay refused
        self.assertTrue(guard.scope(ref, ["restaurants/pret-uk/guides/x.pdf"], True, reader_built=True))
        self.assertTrue(guard.scope(ref, upload + ["tools/build.py"], True, reader_built=True))
        # a new restaurant, or one whose menu is kept by hand, may still have its whole folder written
        self.assertEqual(guard.scope(ref, upload + [folder + "restaurant.json", folder + "menu.csv"], True), [])

    def test_which_restaurants_a_reader_builds_is_read_from_this_checkout(self):
        root =Path(tempfile.mkdtemp())
        for rid, config in (("by-reader", '{"reader": "pret_uk_pdf"}'), ("by-two", '{"readers": ["a_pdf", "b_pdf"]}'),
                            ("by-hand", '{"reader": "manual_csv"}'), ("mixed", '{"reader": "manual_csv", "readers": ["a_pdf"]}'),
                            ("no-reader", "{}"), ("broken", "{not json"), ("a-list", "[]")):
            (root / "restaurants" / rid).mkdir(parents=True)
            (root / "restaurants" / rid / "restaurant.json").write_text(config, encoding="utf-8")
        for rid, expected in (("by-reader", True), ("by-two", True), ("mixed", True), ("no-reader", True), ("broken", True),
                              ("a-list", True), ("by-hand", False), ("not-there", False)):
            self.assertEqual(guard.reader_built(f"scan/{rid}-2026-11-15", root), expected, rid)
            self.assertEqual(guard.reader_built(f"scan/{rid}-2026-11-15-b", root), expected, rid)
        # only a scan/ branch is asked, and a name that isn't a scan's reads nothing
        for ref in ("guide-watch/by-reader-abcdef0123", "safeguards", "scan/by-reader", "scan/../by-reader-2026-11-15"):
            self.assertFalse(guard.reader_built(ref, root), ref)
        # the real folders: every restaurant here but the ones kept by hand
        for f in sorted((Path(guard.ROOT) / "restaurants").glob("*/restaurant.json")):
            if f.parent.name.startswith(("_", ".")):
                continue
            c = json.loads(f.read_text(encoding="utf-8"))
            by_hand = c.get("reader") == "manual_csv" and not c.get("readers")
            self.assertEqual(guard.reader_built(f"scan/{f.parent.name}-2026-11-15"), not by_hand, f.parent.name)
        self.assertTrue(guard.reader_built("scan/starbucks-uk-2026-11-15"))

    def test_a_city_branch_is_named_for_its_city(self):
        for ref in ("city/bath", "recheck/york", "city/2026-10-28", "recheck/York-2026-11-27", "city/bath-2026-10-28/x",
                    "recheck/york-2026-11-27-toolongsuffix"):
            self.assertTrue(guard.scope(ref, ["site/cities.json"]), ref)
        self.assertEqual(guard.scope("recheck/milton-keynes-2026-11-27-b", ["site/cities.json"]), [])
        self.assertEqual(guard.CITY_REF.fullmatch("recheck/milton-keynes-2026-11-27-b").groups(), ("recheck", "milton-keynes"))

    def test_the_owners_own_branches_stay_unrestricted(self):
        everything = ["tools/guard.py", ".github/workflows/guard.yml", "site/cities.json", "site/app.js", "restaurants/starbucks-uk/restaurant.json",
                      "restaurants/pret-uk/menu.csv", "tests/snapshots/pret-uk.txt", "CLAUDE.md"]
        for ref in ("audit-pipeline", "audit-enhance", "safeguards", "fix/reader", "city-requests", "scan-setup-note", "recheck-notes",
                    "guide-watch-fix", "dependabot/pip/tools/pdfplumber-0.11.11", "starbucks-uk-2026-11-15"):
            for flag in (False, True):  # whatever main's copy of a restaurant says
                self.assertEqual(guard.scope(ref, everything, reader_built=flag), [], ref)
            self.assertFalse(guard.reader_built(ref), ref)
            self.assertIsNone(guard.CITY_REF.fullmatch(ref), ref)  # so main() asks nothing about cities for it


class OneCity(unittest.TestCase):
    BASE = {"york": {"name": "York", "checked": "2026-10-01", "places": [{"name": "A", "claim": "place-all"}]},
            "london": {"name": "London", "checked": "2026-10-05", "places": [{"name": "B", "claim": "list-all", "caution": "Oats"}]}}

    def head(self, **changes):
        head =copy.deepcopy(self.BASE)
        for cid, city in changes.items():
            if city is None:
                head.pop(cid)
            else:
                head[cid] = city
        return head

    def test_a_recheck_changes_only_its_city(self):
        york = {"name": "York", "checked": "2026-11-15", "places": []}
        self.assertEqual(guard.one_city("recheck", "york", self.BASE, self.head(york=york)), [])
        self.assertEqual(guard.one_city("recheck", "york", self.BASE, self.head()), [])  # nothing changed at all
        london = self.head()["london"]
        london["places"][0].update(claim="place-all")
        del london["places"][0]["caution"]
        said = guard.one_city("recheck", "york", self.BASE, self.head(york=york, london=london))
        self.assertEqual(len(said), 1)
        self.assertIn("london", said[0])
        self.assertTrue(guard.one_city("recheck", "york", self.BASE, self.head(york=york, london=None)))  # another city removed
        self.assertTrue(guard.one_city("recheck", "york", self.BASE, self.head(york=york, bath={"name": "Bath"})))  # or added
        self.assertTrue(guard.one_city("recheck", "york", self.BASE, self.head(york=None)))  # its own city removed
        self.assertTrue(guard.one_city("recheck", "bath", self.BASE, self.head(bath={"name": "Bath"})))  # not there to re-check

    def test_a_city_adds_only_its_city(self):
        bath = {"name": "Bath", "checked": "2026-11-15", "places": []}
        self.assertEqual(guard.one_city("city", "bath", self.BASE, self.head(bath=bath)), [])
        self.assertTrue(guard.one_city("city", "bath", self.BASE, self.head()))  # nothing added
        self.assertTrue(guard.one_city("city", "york", self.BASE, self.head(york=bath)))  # an existing city rewritten
        said = guard.one_city("city", "bath", self.BASE, self.head(bath=bath, york={"name": "York"}))
        self.assertEqual(len(said), 1)
        self.assertIn("york", said[0])

    def test_key_order_is_not_a_change_but_any_value_is(self):
        reordered = {k: dict(reversed(list(v.items()))) for k, v in reversed(list(self.BASE.items()))}
        self.assertEqual(guard.one_city("recheck", "york", self.BASE, reordered), [])
        london = self.head()["london"]
        london["places"].append(london["places"][0])
        self.assertTrue(guard.one_city("recheck", "york", self.BASE, self.head(london=london)))

    def test_a_file_that_is_not_a_list_of_cities_is_refused(self):
        self.assertTrue(guard.one_city("recheck", "york", self.BASE, []))
        self.assertTrue(guard.one_city("city", "bath", None, {"bath": {}}))

    def test_the_cities_are_read_where_the_branch_left_main_and_at_its_head(self):
        asked = []

        def api(method, path, body=None, accept="application/vnd.github+json"):
            asked.append((method, path, accept))
            if path == "/pulls/7":
                return {"head": {"sha": "h" * 40}, "base": {"ref": "main"}}
            if path.startswith("/compare/"):
                return {"merge_base_commit": {"sha": "b" * 40}}
            return {"at": path.split("ref=")[1][0]}
        with mock.patch.object(guard.gh, "request", side_effect=api):
            self.assertEqual(guard.cities_of(7), ({"at": "b"}, {"at": "h"}))
        self.assertEqual([a[0] for a in asked], ["GET"] * 4)  # the guard only reads
        self.assertEqual(asked[1][1], f"/compare/main...{'h' * 40}?per_page=1")
        self.assertEqual([a[2] for a in asked[2:]], ["application/vnd.github.raw+json"] * 2)

    def test_main_holds_a_recheck_to_its_city_and_asks_nothing_for_other_branches(self):
        london = {"name": "London", "checked": "2026-10-05", "places": []}
        env = {"PR": "7", "HEAD_REF": "recheck/york-2026-11-15"}
        with mock.patch.object(guard, "changed", return_value=["site/cities.json"]), mock.patch.object(guard, "commits", return_value=[]), \
                mock.patch.object(guard, "cities_of", return_value=(self.BASE, self.head(london=london))) as cities, \
                mock.patch.object(guard.gh, "request", return_value={"head": {"repo": {"full_name": "o/r"}}}), \
                mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "o/r"}), mock.patch("builtins.print"):
            with mock.patch.dict("os.environ", env), self.assertRaises(SystemExit):
                guard.main()
            cities.return_value = (self.BASE, self.head(york={"name": "York", "checked": "2026-11-15"}))
            with mock.patch.dict("os.environ", env):
                guard.main()
            cities.reset_mock()
            with mock.patch.dict("os.environ", {"PR": "7", "HEAD_REF": "audit-pipeline"}):
                guard.main()  # the owner's own branch, changing cities.json: no limit, and the cities aren't fetched
            cities.assert_not_called()
            with mock.patch.dict("os.environ", {"PR": "7", "HEAD_REF": "recheck/york"}), self.assertRaises(SystemExit):
                guard.main()  # a badly named branch is refused before anything is fetched
            cities.assert_not_called()


if __name__ == "__main__":
    unittest.main()
