"""Tests for tools/fetch_previous.py. Run: python -m unittest discover -s tests"""
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import fetch_previous  # noqa: E402


class FetchPrevious(unittest.TestCase):
    def test_404_is_treated_as_the_first_deploy(self):
        """The site is up but nothing has been published yet: not an error."""
        with mock.patch.object(fetch_previous, "get", side_effect=urllib.error.HTTPError("u", 404, "Not Found", {}, None)):
            fetch_previous.main()  # must not raise

    def test_other_failures_stop_the_build(self):
        """A download that fails for any other reason (offline, timeout, a 500) must not let the build
        carry on and publish with every restaurant's change marks silently dropped (assessment X4)."""
        for err in (urllib.error.URLError("no connection"), TimeoutError("timed out"),
                    urllib.error.HTTPError("u", 500, "Server Error", {}, None)):
            with self.subTest(err=err), mock.patch.object(fetch_previous, "get", side_effect=err):
                with self.assertRaises(SystemExit):
                    fetch_previous.main()


if __name__ == "__main__":
    unittest.main()
