"""
tools/snapshot.py compare(): a reader's output for the same guide can't change unnoticed, including for a guide that
went live without its snapshot being refreshed (the live menu then stands in for the snapshot).

Run: python -m unittest discover -s tests
"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import snapshot  # noqa: E402


def menu(source="autumn.pdf", avoid=("Carrot Cake", "Flapjack"), items=("Latte",)):
    return {"source": source, "items": [{"name": n, "section": "Drinks", "order": "asis"} for n in items],
            "avoid": [{"name": n, "section": "Food", "gluten": ["WHEAT"]} for n in avoid]}


BLIND = menu("winter.pdf", avoid=(), items=("Latte", "Carrot Cake", "Flapjack"))  # a reader that missed the marks


class Compare(unittest.TestCase):
    def compare(self, saved, now, live=None, update=False):
        """(failed, what was printed, the snapshot file's lines afterwards)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.txt"
            if saved is not None:
                path.write_text("\n".join(snapshot.lines(saved)) + "\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                failed = snapshot.compare("x", snapshot.lines(now), path, update, "items", snapshot.lines(live) if live else None)
            after = path.read_text(encoding="utf-8").splitlines() if path.exists() else None
        return failed, out.getvalue(), after

    def test_the_same_guide_is_compared_with_its_snapshot(self):
        failed, said, _ = self.compare(menu(), menu())
        self.assertFalse(failed)
        self.assertIn("matches its snapshot", said)
        failed, said, _ = self.compare(menu(), menu(avoid=("Flapjack",), items=("Latte", "Carrot Cake")))
        self.assertTrue(failed)
        self.assertIn("+OK    | Drinks | Carrot Cake | asis", said)
        # the live menu doesn't excuse a difference from a snapshot of the same guide
        changed = menu(avoid=("Flapjack",), items=("Latte", "Carrot Cake"))
        self.assertTrue(self.compare(menu(), changed, live=changed)[0])

    def test_a_guide_that_is_new_here_passes_with_a_warning_on_the_run(self):
        for live in (None, menu()):  # nothing live yet, or the old guide still live
            failed, said, _ = self.compare(menu(), menu("winter.pdf"), live=live)
            self.assertFalse(failed)
            self.assertIn("::warning::x: new guide (winter.pdf), so not compared", said)
        failed, said, _ = self.compare(None, menu("winter.pdf"))
        self.assertFalse(failed)
        self.assertIn("::warning::x: no snapshot yet", said)

    def test_a_live_guide_with_a_stale_snapshot_is_compared_with_the_live_menu(self):
        live = menu("winter.pdf")
        for saved in (menu(), None):  # the snapshot is for the old guide, or was never made
            failed, said, _ = self.compare(saved, menu("winter.pdf"), live=live)
            self.assertFalse(failed)
            self.assertIn("matches the live menu", said)
            self.assertNotIn("::warning::", said)
            failed, said, _ = self.compare(saved, BLIND, live=live)
            self.assertTrue(failed, "a reader change on a guide whose snapshot was never refreshed must fail")
            self.assertIn("-AVOID | Food | Carrot Cake | WHEAT", said)
            self.assertIn("--- live menu", said)

    def test_update_saves_what_is_built_and_passes(self):
        failed, said, after = self.compare(menu(), BLIND, live=menu("winter.pdf"), update=True)
        self.assertFalse(failed)
        self.assertEqual(after, snapshot.lines(BLIND))
        # and from then on the snapshot is the one compared with
        self.assertTrue(self.compare(BLIND, menu("winter.pdf"), live=menu("winter.pdf"))[0])


if __name__ == "__main__":
    unittest.main()
