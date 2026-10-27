"""
The hash-locked requirement files the jobs install from (tools/*-lock.txt, made by uv pip compile with hashes for
every platform; assessment V12) still carry every pin from the plain files people install from, and every package in
them has a hash, so the two can't drift apart unnoticed and nothing unverified slips in.

Run: python -m unittest discover -s tests
"""
import re
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\;#]+)", re.M)
# one package in a lock: its pin line, then its indented continuation lines (markers, --hash lines)
BLOCK = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\;#]+)[^\n]*((?:\n[ \t]+[^\n]*)*)", re.M)
name_of = lambda n: n.lower().replace("_", "-")  # noqa: E731


def pins(path):
    return {name_of(n): v for n, v in PIN.findall(path.read_text(encoding="utf-8"))}


def blocks(path):
    text = path.read_text(encoding="utf-8")
    found = BLOCK.findall(text)
    # a sanity check on the parsing itself: every line that starts a package was matched as a block
    starts = [l for l in text.splitlines() if re.match(r"[A-Za-z0-9_.-]+==", l)]
    assert len(found) == len(starts), f"{path.name}: {len(starts)} pin lines but {len(found)} parsed blocks"
    return {name_of(n): (v, rest) for n, v, rest in found}


class Locks(unittest.TestCase):
    def check(self, lock, *sources):
        locked = blocks(TOOLS / lock)
        self.assertTrue(locked, f"{lock} holds no packages")
        for source in sources:
            for name, version in pins(TOOLS / source).items():
                with self.subTest(lock=lock, package=name):
                    self.assertEqual(locked.get(name, (None,))[0], version,
                                     f"{lock} doesn't pin {name}=={version} as {source} does: run uv pip compile again")
        for name, (version, rest) in locked.items():
            with self.subTest(lock=lock, hashed=name):
                self.assertIn("--hash=sha256:", rest, f"{lock}: {name}=={version} has no hash")

    def test_build_lock(self):
        self.check("requirements-lock.txt", "requirements.txt", "requirements-dev.txt")

    def test_notify_lock(self):
        self.check("requirements-notify-lock.txt", "requirements-notify.txt")

    def test_build_tools_lock(self):
        """setuptools and wheel, installed first by hash, so a package that ships as source (http-ece) is built with a
        checked backend rather than one pip fetches on its own."""
        self.check("requirements-buildtools-lock.txt", "requirements-buildtools.txt")

    def test_the_parser_notices_a_missing_hash(self):
        text = "a==1.0 \\\n    --hash=sha256:aa\nb==2.0\nc==3.0 ; python_full_version < '3.13' \\\n    --hash=sha256:cc\n"
        found = {n: rest for n, _, rest in BLOCK.findall(text)}
        self.assertEqual(sorted(found), ["a", "b", "c"])
        self.assertIn("--hash", found["a"])
        self.assertNotIn("--hash", found["b"])
        self.assertIn("--hash", found["c"])


if __name__ == "__main__":
    unittest.main()
