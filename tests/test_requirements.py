"""
The hash-locked requirement files the jobs install from (tools/requirements*.lock, made by uv pip compile with hashes
for every platform; assessment V12) still carry every pin from the plain files people install from, so the two can't
drift apart unnoticed.

Run: python -m unittest discover -s tests
"""
import re
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\;#]+)", re.M)


def pins(path):
    return {name.lower().replace("_", "-"): version for name, version in PIN.findall(path.read_text(encoding="utf-8"))}


class Locks(unittest.TestCase):
    def check(self, lock, *sources):
        locked = pins(TOOLS / lock)
        for source in sources:
            for name, version in pins(TOOLS / source).items():
                with self.subTest(lock=lock, package=name):
                    self.assertEqual(locked.get(name), version, f"{lock} doesn't pin {name}=={version} as {source} does: run uv pip compile again")
        text = (TOOLS / lock).read_text(encoding="utf-8")
        self.assertEqual(len(locked), text.count("==") - text.count("--python-version") * 0, "every line in the lock is a pin")
        self.assertTrue(all("--hash=sha256:" in block for block in text.split("\n\n")[1:] if "==" in block), f"{lock}: a package without a hash")

    def test_build_lock(self):
        self.check("requirements.lock", "requirements.txt", "requirements-dev.txt")

    def test_notify_lock(self):
        self.check("requirements-notify.lock", "requirements-notify.txt")


if __name__ == "__main__":
    unittest.main()
