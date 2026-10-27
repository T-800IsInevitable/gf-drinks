"""
The copy of Leaflet in site/vendor/ is the official 1.9.4 build and nothing else (assessment V9): its fingerprint,
with line endings normalised to LF, must be the one published at https://unpkg.com/leaflet@1.9.4/dist/ and
https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/ (the same bytes; upstream ships the CSS with CRLF endings and
the script with LF, and a Windows checkout turns both into CRLF, hence the normalising).

Run: python -m unittest discover -s tests
"""
import hashlib
import unittest
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / "site" / "vendor" / "leaflet"
OFFICIAL = {  # sha256 of the official file with every CRLF made LF
    "leaflet.js": "db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a",
    "leaflet.css": "337bfca5cabd03b39815b2700febe2b3b7edf55921c59cd49f88ecb328212303",
}


def fingerprint(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class Vendor(unittest.TestCase):
    def test_leaflet_is_the_official_build(self):
        for name, want in OFFICIAL.items():
            with self.subTest(file=name):
                self.assertEqual(fingerprint(VENDOR / name), want, f"site/vendor/leaflet/{name} isn't the official Leaflet 1.9.4 file")

    def test_nothing_else_is_loaded_from_vendor(self):
        """Only the two files (and the licence) live there: anything else would be code the fingerprint test doesn't cover."""
        self.assertEqual(sorted(p.name for p in VENDOR.iterdir()), ["LICENSE", "leaflet.css", "leaflet.js"])


if __name__ == "__main__":
    unittest.main()
