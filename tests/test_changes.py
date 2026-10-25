"""Tests for tools/changes.py. Run: python -m unittest discover -s tests"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import changes  # noqa: E402


def menu(source, items=(), avoid=(), **extra):
    return {"source": source, "guide": {"title": f"{source} guide"}, "items": list(items), "avoid": list(avoid), **extra}


def ok(name, section="Drinks", **how):
    return {"name": name, "section": section, "order": "asis", **how}


def bad(name, section="Drinks"):
    return {"name": name, "section": section, "gluten": ["WHEAT"]}


class Compare(unittest.TestCase):
    def test_nothing_to_compare_with(self):
        self.assertIsNone(changes.compare(None, menu("b.pdf", [ok("Tea")])))

    def test_same_guide_keeps_the_live_changes(self):
        live = menu("a.pdf", [ok("Tea")], changes={"since": "old", "added": [{"name": "Tea"}]})
        self.assertEqual(changes.compare(live, menu("a.pdf", [ok("Tea")])), live["changes"])

    def test_item_that_now_contains_gluten(self):
        c = changes.compare(menu("a.pdf", [ok("Latte")]), menu("b.pdf", avoid=[bad("Latte")]), date(2026, 10, 1))
        self.assertEqual([x["name"] for x in c["nowAvoid"]], ["Latte"])
        self.assertEqual(c["nowAvoid"][0]["gluten"], ["WHEAT"])
        self.assertEqual(c["date"], "2026-10-01")
        self.assertEqual(c["since"], "a.pdf guide")

    def test_item_no_longer_to_avoid(self):
        c = changes.compare(menu("a.pdf", avoid=[bad("Mocha")]), menu("b.pdf", [ok("Mocha")]))
        self.assertEqual([x["name"] for x in c["nowOk"]], ["Mocha"])

    def test_ordered_differently(self):
        was = ok("Latte", order="any", ok=["oat", "soya"])
        now = ok("Latte", order="except", ok=["soya"], **{"not": ["oat"]})
        c = changes.compare(menu("a.pdf", [was]), menu("b.pdf", [now]))
        self.assertEqual(len(c["changed"]), 1)
        self.assertEqual(c["changed"][0]["was"]["order"], "any")
        self.assertEqual(c["changed"][0]["now"]["not"], ["oat"])

    def test_new_and_gone(self):
        c = changes.compare(menu("a.pdf", [ok("Old")]), menu("b.pdf", [ok("New")], [bad("Cake")]))
        self.assertEqual([x["name"] for x in c["added"]], ["New"])
        self.assertEqual([x["name"] for x in c["removed"]], ["Old"])
        self.assertEqual(c["newAvoid"], 1)

    def test_renamed_section_is_not_a_change(self):
        c = changes.compare(menu("a.pdf", [ok("Tea", "Hot drinks")]), menu("b.pdf", [ok("Tea", "Teas")]))
        self.assertFalse(c["added"] or c["removed"] or c["changed"])
        self.assertIn("no changes", changes.summary(c))


if __name__ == "__main__":
    unittest.main()
