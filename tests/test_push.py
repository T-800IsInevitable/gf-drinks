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


class Release(unittest.TestCase):
    """'Update N is live!': only when the release number went up past the live one and whatsnew.json announces it."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.prev, self.site = self.tmp / "previous", self.tmp / "site"
        self.prev.mkdir()
        self.site.mkdir()

    def given(self, live, new, notes):
        if live is not None:
            (self.prev / "app-version").write_text(str(live), encoding="utf-8")
        (self.site / "app.js").write_text(f"(() => {{\n  const APP_VERSION = {new};\n}})();\n", encoding="utf-8")
        (self.site / "whatsnew.json").write_text(json.dumps(notes), encoding="utf-8")
        return push.release_plan(self.prev, self.site)

    NOTES = [{"version": 31, "date": "2026-10-27", "title": "Maps that work offline", "items": ["a"]}]

    def test_a_new_announced_release_is_announced(self):
        m = self.given(30, 31, self.NOTES)
        self.assertEqual(m["title"], "Update 31 is live!")
        self.assertEqual(m["body"], "Tap to see the new features: Maps that work offline")
        self.assertEqual(m["url"], "?whatsnew")  # a query, which the release before reads as nothing
        self.assertEqual(m["tag"], "gf-update-31")  # its own tag, so it can't silently replace Update 30's
        self.assertNotIn("badge", m)  # the badge counts new guides

    def test_no_notes_no_announcement(self):
        self.assertIsNone(self.given(30, 31, [{**self.NOTES[0], "version": 30}]))

    def test_the_same_release_again_isnt_announced(self):
        self.assertIsNone(self.given(31, 31, self.NOTES))

    def test_an_unknown_live_release_isnt_announced(self):
        self.assertIsNone(self.given(None, 31, self.NOTES))

    def test_guides_come_first_then_cities_then_the_release(self):
        with mock.patch.object(push, "plan", return_value={"title": "New menus in Treat Temple", "body": "x"}), \
                mock.patch.object(push, "city_plan", return_value={"title": "Leeds is in the app", "body": "z"}), \
                mock.patch.object(push, "release_plan", return_value={"title": "Update 31 is live!", "body": "y"}):
            self.assertEqual([m["title"] for m in push.messages()], ["New menus in Treat Temple", "Leeds is in the app", "Update 31 is live!"])

    def cities(self, live, now):
        if live is not None:
            (self.prev / "cities.json").write_text(json.dumps(live), encoding="utf-8")
        (self.site / "cities.json").write_text(json.dumps(now), encoding="utf-8")
        return push.city_plan(self.prev, self.site)

    def test_a_new_city_is_announced(self):
        york = {"name": "York", "places": [{}]}
        m = self.cities({"york": york}, {"york": york, "leeds": {"name": "Leeds", "places": [{}, {}, {}]}})
        self.assertEqual(m["title"], "Leeds is in the app")
        self.assertEqual(m["body"], "3 places to eat, from coeliac guides, each checked against its own website where it has one. Tap to see it.")
        self.assertEqual(m["url"], "#leeds")
        self.assertEqual(m["tag"], "gf-cities-leeds")
        self.assertNotIn("gluten free", m["body"])
        m = self.cities({"york": york}, {"york": york, "leeds": {"name": "Leeds", "places": [{}]}, "lyon": {"name": "Lyon", "places": [{}]}})
        self.assertEqual((m["title"], m["url"]), ("Leeds and Lyon are in the app", ""))

    def test_no_new_city_or_no_live_list_announces_nothing(self):
        york = {"name": "York", "places": [{}]}
        self.assertIsNone(self.cities({"york": york}, {"york": york}))
        self.assertIsNone(self.cities({"york": york, "poole": york}, {"york": york}))  # a city taken out isn't news
        self.assertIsNone(self.cities([], {"york": york}))  # a live list that isn't one doesn't announce every city
        (self.prev / "cities.json").write_text("<html>Not found", encoding="utf-8")
        self.assertIsNone(push.city_plan(self.prev, self.site))  # nor does a damaged one stop the publish
        shutil.rmtree(self.prev)
        self.prev.mkdir()
        self.assertIsNone(self.cities(None, {"york": york}))

    def test_each_message_is_sent(self):
        plan = self.tmp / "push-message.json"
        plan.write_text(json.dumps({"messages": [{"title": "A", "body": "a"}, {"title": "B", "body": "b"}]}), encoding="utf-8")
        env = {"PUSH_SUBSCRIPTIONS": '{"endpoint": "https://web.push.apple.com/x", "keys": {}}', "VAPID_PRIVATE_KEY": "k"}
        with mock.patch.dict(push.os.environ, env, clear=False), mock.patch.object(push, "send", return_value=["phone 1: sent"]) as sent, \
                mock.patch.object(sys, "argv", ["push.py", "--send", str(plan)]), mock.patch("builtins.print"):
            push.main()
        self.assertEqual([c.args[0]["title"] for c in sent.call_args_list], ["A", "B"])


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
        self.assertEqual(m["tag"], "gf-menus-x")  # from the build time, so each publish's message is its own
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
        # braces turned into web-address codes on the way from the phone (%7B, %7D), alone or among other lines
        encoded = json.dumps(one).replace('"keys": {', '"keys": %7B').replace("}}", "%7D%7D")
        self.assertEqual(push.subscriptions(encoded), [one])
        self.assertEqual(push.subscriptions(json.dumps(one) + "\n" + encoded), [one, one])
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
            if "/far/" in subscription_info["endpoint"]:
                raise ConnectionError("Max retries exceeded with url: /far/Zz9madeUpTokenForTheTest-0123456789abcdef")

        subs = [{"endpoint": f"https://push.example/{x}/secret-token", "keys": {}} for x in ("a", "old", "bad", "odd", "far")]
        msg = {"title": push.TITLE, "body": "b", "tag": "gf-menus", "url": "", "nowAvoid": [], "badge": 1}
        with mock.patch.object(push, "webpush", fake), mock.patch.object(push, "WebPushException", Gone):
            lines = push.send(msg, subs, "PEM", "https://github.com/o/r")
        self.assertEqual([l.split(": ", 1)[1].split(".")[0] for l in lines][:4], ["sent", "gone", "failed (500)", "failed (ValueError: not a key)"])
        self.assertNotIn("madeUpToken", lines[4])  # an error quoting the address doesn't put its token in the log
        self.assertIn("ConnectionError", lines[4])
        self.assertIn("Tell me about new menus", lines[1])
        self.assertTrue(all("secret-token" not in l and "push.example" in l for l in lines), lines)  # the host, never the token
        self.assertEqual(calls[0][1], msg)
        self.assertEqual(calls[0][2], {"sub": "https://github.com/o/r"})

    def test_each_phone_is_listed_with_its_check_code(self):
        sub = {"endpoint": "https://push.example/abc", "keys": {}}
        self.assertEqual(push.code(sub), "f7a263f8")
        with mock.patch.object(push, "webpush", lambda **k: None):
            line = push.send({"title": "t", "body": "b"}, [sub], "PEM", "https://x.github.io")[0]
        self.assertIn(f"code {push.code(sub)}", line)
        self.assertNotIn("abc", line)

    def test_a_test_message_shows_anew_each_time(self):
        from datetime import datetime, timezone
        one = push.test_message(datetime(2026, 7, 1, 13, 5, tzinfo=timezone.utc))
        two = push.test_message(datetime(2026, 7, 1, 13, 6, tzinfo=timezone.utc))
        self.assertNotEqual(one["tag"], two["tag"])
        self.assertTrue(one["tag"].startswith("gf-test-"))
        self.assertIn("14:05 UK time", one["body"])  # summer time
        self.assertNotIn("gluten free", one["body"])

    def test_the_contact_is_one_push_services_accept(self):
        self.assertEqual(push.contact("T-800IsInevitable/gf-drinks"), "https://t-800isinevitable.github.io")
        try:
            from py_vapid import _check_sub
        except ImportError:
            self.skipTest("py_vapid not installed")
        self.assertTrue(_check_sub(push.contact("T-800IsInevitable/gf-drinks")))
        self.assertTrue(_check_sub(push.contact("")))

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
