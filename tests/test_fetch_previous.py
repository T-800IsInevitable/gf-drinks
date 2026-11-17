"""Tests for tools/fetch_previous.py. Run: python -m unittest discover -s tests"""
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import fetch_previous  # noqa: E402


class FetchPrevious(unittest.TestCase):
    def test_404_is_the_first_deploy_only_when_it_says_so(self):
        """Nothing published yet is fine for the very first publish (GF_FIRST_DEPLOY=1). Otherwise a 404 is a moved or
        switched-off site, which must not skip the build's check on the live menus."""
        e404 = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        with mock.patch.object(fetch_previous, "get", side_effect=e404), mock.patch.object(sys, "argv", ["fetch_previous.py"]):
            with mock.patch.dict(fetch_previous.os.environ, {"GF_FIRST_DEPLOY": "1"}):
                fetch_previous.main()  # must not raise
            with mock.patch.dict(fetch_previous.os.environ, {}, clear=True), self.assertRaises(SystemExit) as stop:
                fetch_previous.main()
            self.assertIn("GF_FIRST_DEPLOY=1", str(stop.exception))

    def test_one_menu_failing_stops_the_build_too(self):
        """The index arrives but one restaurant's menu doesn't: that restaurant would otherwise publish with no
        'what changed' at all, so the build stops rather than carry on without it."""
        index = b'{"restaurants": [{"id": "a", "file": "data/r/a.json"}, {"id": "b", "file": "data/r/b.json"}]}'
        answers = {"data/restaurants.json": index, "data/r/a.json": b"{}"}

        def get(url):
            path = url.split("/gf-drinks/")[-1]
            if path not in answers:
                raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)
            return answers[path]
        with mock.patch.object(fetch_previous, "get", side_effect=get), mock.patch.object(fetch_previous, "OUT", Path(tempfile.mkdtemp())), \
                mock.patch.object(sys, "argv", ["fetch_previous.py"]):  # not unittest's own arguments
            with self.assertRaises(SystemExit) as stop:
                fetch_previous.main()
            self.assertIn("live b menu", str(stop.exception))

    def test_other_failures_stop_the_build(self):
        """A download that fails for any other reason (offline, timeout, a 500) must not let the build
        carry on and publish with every restaurant's change marks silently dropped (assessment X4)."""
        for err in (urllib.error.URLError("no connection"), TimeoutError("timed out"),
                    urllib.error.HTTPError("u", 500, "Server Error", {}, None)):
            with self.subTest(err=err), mock.patch.object(fetch_previous, "get", side_effect=err):
                with self.assertRaises(SystemExit):
                    fetch_previous.main()

    def test_a_passing_fault_is_tried_once_more(self):
        """A brief 503 from Pages stopped a publish: each download is tried once more after a pause, and a fault
        that lasts still stops the build. A 404 isn't retried (for the index it means the first deploy)."""
        res = mock.MagicMock()
        res.__enter__.return_value.read.return_value = b"ok"
        e503 = urllib.error.HTTPError("u", 503, "Service Unavailable", {}, None)
        e404 = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        for answers, want in (([e503, res], b"ok"), ([TimeoutError("slow"), res], b"ok"), ([e503, e503], e503),
                              ([e404, res], e404), ([urllib.error.URLError("no connection")] * 2, urllib.error.URLError)):
            with self.subTest(answers=answers), mock.patch.object(fetch_previous, "RETRY_AFTER", 0), \
                    mock.patch.object(fetch_previous.urllib.request, "urlopen", side_effect=answers) as opened:
                if isinstance(want, bytes):
                    self.assertEqual(fetch_previous.get("https://x.test/a.json"), want)
                else:
                    with self.assertRaises(want if isinstance(want, type) else type(want)):
                        fetch_previous.get("https://x.test/a.json")
                self.assertEqual(opened.call_count, 1 if want is e404 else 2)


if __name__ == "__main__":
    unittest.main()
