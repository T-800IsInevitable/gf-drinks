"""
Push notifications (tools/push.py): a message only when a publish brought a new guide, saying what changed, with the
"now contains gluten" keys for the phone's favourites check; sending reports an expired subscription as gone.

Run: python -m unittest discover -s tests
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import push  # noqa: E402


def restaurant(rid, name, source, items=3, changes=None, title="Autumn 2026"):
    return {"id": rid, "name": name, "file": f"data/r/{rid}.json", "source": source, "guide": {"title": title},
            "stats": {"items": items, "avoid": 1}, "changes": changes, "hash": source[:8]}


class Plan(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.prev, self.data = self.tmp / "previous", self.tmp / "data"
        (self.prev / "r").mkdir(parents=True)
        (self.data / "r").mkdir(parents=True)

    def write(self, folder, rs):
        (folder / "restaurants.json").write_text(json.dumps({"built": "x", "restaurants": rs}), encoding="utf-8")
        for r in rs:
            (folder / "r" / f"{r['id']}.json").write_text(json.dumps(r), encoding="utf-8")

    def test_nothing_when_no_guide_changed(self):
        rs = [restaurant("pret-uk", "Pret A Manger", "pret-sep.pdf"), restaurant("pho-uk", "Pho", "pho-2026.pdf")]
        self.write(self.prev, rs)
        self.write(self.data, rs)
        self.assertIsNone(push.plan(self.prev, self.data))

    def test_one_new_guide_names_what_changed_and_links_to_it(self):
        self.write(self.prev, [restaurant("pret-uk", "Pret A Manger", "pret-sep.pdf"), restaurant("pho-uk", "Pho", "pho-2026.pdf")])
        changes = {"added": [{"section": "Soup", "name": "Pea soup"}] * 5,
                   "nowAvoid": [{"section": "Hot drinks", "name": "Oat latte"}, {"section": "Food", "name": "Granola pot"}],
                   "nowOk": [], "changed": [], "removed": []}
        self.write(self.data, [restaurant("pret-uk", "Pret A Manger", "pret-nov.pdf", changes=changes, title="November 2026"),
                               restaurant("pho-uk", "Pho", "pho-2026.pdf")])
        m = push.plan(self.prev, self.data)
        self.assertEqual(m["title"], push.TITLE)
        self.assertEqual(m["body"], "Pret A Manger: November 2026 guide: 2 now contain gluten, 5 new.")
        self.assertEqual(m["url"], "#pret-uk")
        self.assertEqual(m["nowAvoid"], ["pret-uk|Hot drinks|Oat latte", "pret-uk|Food|Granola pot"])
        self.assertEqual(m["badge"], 1)
        self.assertNotIn("gluten free", m["body"])

    def test_several_new_guides_and_a_new_restaurant(self):
        self.write(self.prev, [restaurant(f"r{n}", f"Chain {n}", f"g{n}.pdf") for n in range(4)])
        new = [restaurant(f"r{n}", f"Chain {n}", f"g{n}-new.pdf", changes={"added": [{"section": "s", "name": "x"}]}, title="Allergen guide") for n in range(4)]
        new.append(restaurant("new-uk", "Newcomer", "new.pdf", items=12))
        self.write(self.data, new)
        m = push.plan(self.prev, self.data)
        self.assertEqual(m["body"], "Chain 0: new guide: 1 new; Chain 1: new guide: 1 new; Chain 2: new guide: 1 new; and 2 more.")
        self.assertEqual(m["url"], "")
        self.assertEqual(m["badge"], 5)

    def test_a_big_change_still_fits_a_push(self):
        self.write(self.prev, [restaurant("starbucks-uk", "Starbucks", "old.pdf")])
        now_avoid = [{"section": "Seasonal and Festive Beverages", "name": f"Iced Caramel Macchiato with Oat Drink and Cold Foam number {n}"} for n in range(80)]
        self.write(self.data, [restaurant("starbucks-uk", "Starbucks", "new.pdf", changes={"nowAvoid": now_avoid})])
        m = push.plan(self.prev, self.data)
        size = len(json.dumps(m, ensure_ascii=False).encode("utf-8"))
        self.assertLessEqual(size, push.MAX_BYTES)
        self.assertTrue(10 < len(m["nowAvoid"]) < 80, len(m["nowAvoid"]))
        self.assertIn("80 now contain gluten", m["body"])

    def test_first_publish_has_nothing_to_compare(self):
        self.write(self.data, [restaurant("pret-uk", "Pret A Manger", "pret-sep.pdf", items=40)])
        m = push.plan(self.prev, self.data)  # no previous index at all: every restaurant counts as new to the app
        self.assertEqual(m["body"], "Pret A Manger: Autumn 2026 guide: 40 items with no gluten ingredients.")


class Send(unittest.TestCase):
    def test_subscriptions_in_any_of_the_three_layouts(self):
        one = {"endpoint": "https://push.example/a", "keys": {"p256dh": "x", "auth": "y"}}
        self.assertEqual(push.subscriptions(json.dumps(one)), [one])
        self.assertEqual(push.subscriptions(json.dumps([one, one])), [one, one])
        self.assertEqual(push.subscriptions("# Owen's phone\n" + json.dumps(one) + "\n\n" + json.dumps(one) + "\n"), [one, one])
        self.assertEqual(push.subscriptions(""), [])
        with self.assertRaises(SystemExit):
            push.subscriptions(json.dumps(one) + "\nnot json")

    def test_sent_gone_and_failed(self):
        class Gone(Exception):
            def __init__(self, status):
                self.response = mock.Mock(status_code=status)

        calls = []

        def fake(subscription_info, data, vapid_private_key, vapid_claims, ttl):
            calls.append((subscription_info["endpoint"], json.loads(data), vapid_claims))
            if "/old/" in subscription_info["endpoint"]:
                raise Gone(410)
            if "/bad/" in subscription_info["endpoint"]:
                raise Gone(500)
            if "/odd/" in subscription_info["endpoint"]:
                raise ValueError("not a key")

        subs = [{"endpoint": f"https://push.example/{x}/secret-token", "keys": {}} for x in ("a", "old", "bad", "odd")]
        msg = {"title": push.TITLE, "body": "b", "tag": "gf-menus", "url": "", "nowAvoid": [], "badge": 1}
        with mock.patch.object(push, "webpush", fake), mock.patch.object(push, "WebPushException", Gone):
            lines = push.send(msg, subs, "PEM", "https://github.com/o/r")
        self.assertEqual([l.split(": ", 1)[1].split(".")[0] for l in lines], ["sent", "gone", "failed (500)", "failed (ValueError: not a key)"])
        self.assertIn("Tell me about new menus", lines[1])
        self.assertTrue(all("secret-token" not in l and "push.example" in l for l in lines), lines)  # the host, never the token
        self.assertEqual(calls[0][1], msg)
        self.assertEqual(calls[0][2], {"sub": "https://github.com/o/r"})

    def test_the_key_as_pem_or_raw(self):
        raw = "A" * 43
        self.assertEqual(push.vapid_key(raw + "\n"), raw)
        if push.Vapid is None:
            self.skipTest("py_vapid not installed")
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        self.assertIsInstance(push.vapid_key(pem), push.Vapid)


if __name__ == "__main__":
    unittest.main()
