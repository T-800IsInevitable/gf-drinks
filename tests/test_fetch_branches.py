"""
tools/fetch_branches.py: the chains' UK branches from OpenStreetMap for the map and Near me, matched as the app
matches them, and a busy week never empties the list or fails the publish. Also check.py's check of the list.

Run: python -m unittest discover -s tests
"""
import io
import json
import sys
import tempfile
import time
import unittest
import urllib.error
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check  # noqa: E402
import fetch_branches as fb  # noqa: E402

CHAINS = [("pret-uk", ["Pret A Manger", "Pret"]), ("nandos-uk", ["Nando's", "Nandos"])]


def node(n, lat, lon, **tags):
    return {"type": "node", "id": n, "lat": lat, "lon": lon, "tags": tags}


class Matching(unittest.TestCase):
    def test_brand_or_name_whole_and_ignoring_case(self):
        els = [node(1, 51.53, -0.12, name="PRET A MANGER", **{"addr:street": "Euston Road", "opening_hours": "24/7"}),
               node(2, 51.50, -0.10, brand="Nando's", name="Nando's Waterloo"),
               node(3, 51.51, -0.11, name="Pret A Manger Express"),  # not the whole name
               node(4, 51.52, -0.13, name="Not a chain"),
               {"type": "way", "id": 5, "center": {"lat": 53.48, "lon": -2.24}, "tags": {"name": "Nandos"}}]
        self.assertEqual(fb.branches(els, CHAINS), [[0, 51.53, -0.12, "Euston Road", "24/7"], [1, 51.5, -0.1, "", ""], [1, 53.48, -2.24, "", ""]])

    def test_outside_the_uk_and_repeats_are_left_out(self):
        els = [node(1, 48.85, 2.35, name="Pret"), node(2, 51.5, -0.1, name="Pret"), node(2, 51.5, -0.1, name="Pret")]
        self.assertEqual(fb.branches(els, CHAINS), [[0, 51.5, -0.1, "", ""]])

    def test_the_query_names_every_chain_with_quotes_escaped(self):
        q = fb.query(["Nando's", 'A "B"'])
        self.assertIn('Nando\'s|A \\"B\\"', q)
        self.assertIn('area["ISO3166-1"="GB"]', q)


def live_list(fetched="2026-10-20", pret=20, nandos=20):
    return {"fetched": fetched, "chains": ["pret-uk", "nandos-uk"],
            "b": [[0, 51.5, -0.1, "", ""]] * pret + [[1, 53.4, -2.2, "", ""]] * nandos}


class Fallback(unittest.TestCase):
    def run_main(self, osm, live, argv=(), osm_error=None):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "restaurants.json").write_text(json.dumps({"restaurants": [{"id": r, "osm": n} for r, n in CHAINS]}), encoding="utf-8")
            asked = mock.Mock(return_value=osm, side_effect=osm_error)
            with mock.patch.object(fb, "DATA", data), mock.patch.object(fb, "OUT", data / "branches.json"), \
                    mock.patch.object(fb, "from_openstreetmap", asked), mock.patch.object(fb, "from_live", return_value=live), \
                    mock.patch.object(sys, "argv", ["fetch_branches.py", *argv]), redirect_stdout(io.StringIO()) as out, \
                    mock.patch("sys.stderr", io.StringIO()):
                fb.main()
            written = (data / "branches.json").exists() and json.loads((data / "branches.json").read_text(encoding="utf-8"))
            self.asked = asked.called
            return written, out.getvalue()

    def test_a_push_publishes_a_recent_live_list_without_asking(self):
        live = live_list(fetched=date.today().isoformat())
        written, _ = self.run_main([node(1, 51.53, -0.12, name="Pret")], live, ["--reuse-days", "7"])
        self.assertEqual(written, live)
        self.assertFalse(self.asked)

    def test_a_push_asks_when_the_live_list_is_a_week_old(self):
        live = live_list(fetched=(date.today() - timedelta(days=8)).isoformat(), pret=1, nandos=0)
        written, _ = self.run_main([node(1, 51.53, -0.12, name="Pret")], live, ["--reuse-days", "7"])
        self.assertTrue(self.asked)
        self.assertEqual(written["fetched"], date.today().isoformat())

    def test_a_list_that_lost_a_fifth_keeps_the_live_one(self):
        live = live_list()
        written, out = self.run_main([node(n, 51.5 + n / 1000, -0.1, name="Pret") for n in range(20)]
                                     + [node(100 + n, 53.4 + n / 1000, -2.2, name="Nandos") for n in range(10)], live)
        self.assertEqual(written, live)
        self.assertIn("looks broken", out)

    def test_a_chain_that_vanished_keeps_the_live_one(self):
        live = live_list(pret=20, nandos=10)
        written, out = self.run_main([node(n, 51.5 + n / 1000, -0.1, name="Pret") for n in range(40)], live)
        self.assertEqual(written, live)
        self.assertIn("nandos-uk", out)

    def test_any_error_falls_back_to_the_live_list(self):
        live = live_list()
        written, out = self.run_main(None, live, osm_error=KeyError("surprise"))
        self.assertEqual(written, live)
        self.assertIn("went wrong", out)

    def test_an_answer_is_written(self):
        written, _ = self.run_main([node(1, 51.53, -0.12, name="Pret")], None)
        self.assertEqual(written["chains"], ["pret-uk", "nandos-uk"])
        self.assertEqual(written["b"], [[0, 51.53, -0.12, "", ""]])

    def test_no_answer_keeps_the_live_list(self):
        live = {"fetched": "2026-10-20", "chains": ["pret-uk"], "b": [[0, 51.5, -0.1, "", ""]]}
        written, out = self.run_main(None, live)
        self.assertEqual(written, live)
        self.assertIn("2026-10-20", out)

    def test_an_empty_answer_keeps_the_live_list_too(self):
        live = {"fetched": "2026-10-20", "chains": ["pret-uk"], "b": [[0, 51.5, -0.1, "", ""]]}
        written, _ = self.run_main([], live)
        self.assertEqual(written, live)

    def test_nothing_at_all_writes_nothing_and_doesnt_fail(self):
        written, out = self.run_main(None, None)
        self.assertFalse(written)
        self.assertIn("no branch list this time", out)


class Clock:
    """time.time and time.sleep for the fetcher, moved on by hand: each ask() takes `took` seconds."""
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, s):
        self.now += s


class Asking(unittest.TestCase):
    def test_busy_servers_are_retried_within_the_budget(self):
        calls, clock = [], Clock()

        def ask(server, q, seconds):
            calls.append((server, seconds))
            clock.now += 5
            if len(calls) < 3:
                raise urllib.error.HTTPError(server, 502, "busy", {}, None)
            return [node(1, 51.5, -0.1, name="Pret")]
        with mock.patch.object(fb, "ask", side_effect=ask), mock.patch.object(fb.time, "time", clock.time), \
                mock.patch.object(fb.time, "sleep", clock.sleep), redirect_stdout(io.StringIO()):
            got = fb.from_openstreetmap(CHAINS)
        self.assertEqual(len(got), 1)
        self.assertEqual([s for s, _ in calls], [fb.SERVERS[0], fb.SERVERS[1], fb.SERVERS[0]])

    def test_slow_servers_never_run_past_the_budget(self):
        calls, clock = [], Clock()
        start = clock.now

        def ask(server, q, seconds):
            calls.append(seconds)
            clock.now += seconds  # every answer takes all the time it's given, then fails
            raise TimeoutError("slow")
        with mock.patch.object(fb, "ask", side_effect=ask), mock.patch.object(fb.time, "time", clock.time), \
                mock.patch.object(fb.time, "sleep", clock.sleep), redirect_stdout(io.StringIO()):
            self.assertIsNone(fb.from_openstreetmap(CHAINS))
        self.assertLessEqual(clock.now - start, fb.BUDGET)
        self.assertEqual(calls[0], 360)
        self.assertLess(calls[1], 360)  # the second server gets only what's left

    def test_an_answer_needs_its_elements_and_no_error_remark(self):
        def answer(body):
            res = mock.MagicMock()
            res.__enter__.return_value = io.BytesIO(json.dumps(body).encode())
            return res
        with mock.patch.object(fb.urllib.request, "urlopen", return_value=answer({"elements": [node(1, 51.5, -0.1, name="Pret")]})):
            self.assertEqual(len(fb.ask("https://overpass.invalid/", "q", 5)), 1)
        with mock.patch.object(fb.urllib.request, "urlopen", return_value=answer({"elements": [], "remark": "runtime error: Query timed out"})):
            self.assertRaises(RuntimeError, fb.ask, "https://overpass.invalid/", "q", 5)
        with mock.patch.object(fb.urllib.request, "urlopen", return_value=answer(["not", "an", "answer"])):
            self.assertRaises(ValueError, fb.ask, "https://overpass.invalid/", "q", 5)

    def test_a_trickling_answer_is_cut_off_at_the_deadline(self):
        def slow(*a, **k):
            time.sleep(3)
        with mock.patch.object(fb.urllib.request, "urlopen", side_effect=slow):
            t = time.time()
            self.assertRaises(TimeoutError, fb.ask, "https://overpass.invalid/", "q", 0.3)
            self.assertLess(time.time() - t, 2)


class Check(unittest.TestCase):
    def test_good_list_passes_and_a_bad_row_fails(self):
        errors = []
        good = {"fetched": "2026-10-27", "chains": ["pret-uk"], "b": [[0, 51.5, -0.1, "Euston Road", ""]]}
        with redirect_stdout(io.StringIO()):
            check.check_branches(good, {"pret-uk"}, errors.append)
            self.assertEqual(errors, [])
            check.check_branches({**good, "b": [[0, 48.85, 2.35, "", ""]]}, {"pret-uk"}, errors.append)  # Paris
            check.check_branches({**good, "b": [[3, 51.5, -0.1, "", ""]]}, {"pret-uk"}, errors.append)  # no such chain
            check.check_branches({**good, "b": []}, {"pret-uk"}, errors.append)
        self.assertEqual(len(errors), 3)


if __name__ == "__main__":
    unittest.main()
