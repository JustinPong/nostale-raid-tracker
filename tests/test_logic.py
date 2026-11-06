import tempfile
import unittest
from pathlib import Path

import logic
from ocr import Row, Sheet
from store import Store

KNOWN = {"劍鬥士夢古", "耶穌基督", "乙骨憂太", "Arashi嵐", "元素小棠", "萌萌小蝶"}


class OwedTest(unittest.TestCase):
    def test_full_run(self):
        self.assertEqual(logic.owed(100, 1, 70), 70)

    def test_rounding_modes(self):
        self.assertEqual(logic.owed(55, 1, 70, "half_up"), 39)  # 38.5
        self.assertEqual(logic.owed(55, 1, 70, "ceil"), 39)
        self.assertEqual(logic.owed(55, 1, 70, "floor"), 38)
        self.assertEqual(logic.owed(84, 1, 70, "half_up"), 59)  # 58.8
        self.assertEqual(logic.owed(11, 1, 70, "floor"), 7)  # 7.7
        self.assertEqual(logic.owed(10, 1, 70, "ceil"), 7)  # exact stays exact

    def test_per_game_multiplier(self):
        self.assertEqual(logic.owed(100, 3, 70), 210)


class ResolveTest(unittest.TestCase):
    def test_alias_wins(self):
        self.assertEqual(logic.resolve_name(["乙太"], KNOWN, {"乙太": "乙骨憂太"}), ("乙骨憂太", ""))

    def test_exact_known(self):
        self.assertEqual(logic.resolve_name(["耶基", "耶穌基督"], KNOWN, {}), ("耶穌基督", ""))

    def test_fuzzy_dropped_chars(self):
        self.assertEqual(logic.resolve_name(["乙骨太"], KNOWN, {}), ("乙骨憂太", "fuzzy"))
        self.assertEqual(logic.resolve_name(["Arashi/ä"], KNOWN, {}), ("Arashi嵐", "fuzzy"))

    def test_unknown_is_new_best_reading(self):
        self.assertEqual(logic.resolve_name(["帕路奇亞", "路奇亞"], KNOWN, {}), ("帕路奇亞", "new"))

    def test_ambiguous_is_new(self):
        known = {"萌萌小蝶", "萌萌小貓"}
        self.assertEqual(logic.resolve_name(["萌萌小"], known, {})[1], "new")


def session(**kw):
    s = {"raid": "不死龍", "created": "2026-11-05 20:00", "games": 100, "team_size": 15, "percent": 70,
         "boxes": 1, "coins": 1, "rounding": "half_up", "me": "我", "members": []}
    s.update(kw)
    return s


def member(name, runs, returned=False):
    return {"name": name, "runs": runs, "left": False, "returned": returned, "ocr": [], "flag": ""}


class SummaryTest(unittest.TestCase):
    def test_me_excluded_and_returned_split(self):
        s = session(members=[member("我", 100), member("a", 100), member("b", 55, returned=True), member("c", 45)])
        sm = logic.session_summary(s)
        self.assertEqual((sm["due_n"], sm["paid_n"]), (2, 1))
        self.assertEqual(sm["due_boxes"], 70 + 32)
        self.assertEqual(sm["empty_runs"], 1500 - 300)

    def test_zero_runs_owes_nothing(self):
        s = session(members=[member("a", 0), member("b", 100)])
        sm = logic.session_summary(s)
        self.assertEqual((sm["due_n"], sm["paid_n"], sm["due_boxes"]), (1, 0, 70))
        self.assertFalse(logic.owes_something(s, s["members"][0]))
        self.assertEqual([r["name"] for r in logic.outstanding([s])], ["b"])

    def test_outstanding_one_row_per_session(self):
        s1 = session(raid="不死龍", created="2026-11-01 20:00",
                     members=[member("a", 100), member("b", 100, returned=True)])
        s2 = session(raid="冰龍", created="2026-11-02 20:00", members=[member("a", 50), member("我", 50)])
        rows = logic.outstanding([s2, s1])
        self.assertEqual([(r["name"], r["raid"], r["boxes"]) for r in rows], [("a", "不死龍", 70), ("a", "冰龍", 35)])

    def test_needs_mail(self):
        s = session(members=[member("a", 100), member("b", 100, returned=True), member("c", 0), member("d", 100)])
        s["members"][3]["mailed"] = True
        self.assertEqual([m["name"] for m in s["members"] if logic.needs_mail(s, m)], ["a"])
        self.assertEqual([m["name"] for m in s["members"] if logic.can_mail(s, m)], ["a", "d"])  # not b: returned


class MailTest(unittest.TestCase):
    def test_default_template(self):
        s = session(raid="不死龍", created="2026-11-05 21:00")
        m = member("BoomBoom", 110)
        self.assertEqual(logic.render_mail(logic.MAIL_DEFAULT["title"], s, m), "不死龍110回77")
        self.assertEqual(logic.render_mail(logic.MAIL_DEFAULT["body"], s, m), "不死龍110回77 可以寄給我嗎 謝謝")

    def test_all_fields_and_unknown_braces(self):
        s = session(raid="冰龍", created="2026-11-05 21:00", boxes=2)
        text = logic.render_mail("{名字} {日期} {應還箱子}/{應還硬幣} {不明}", s, member("小氣", 10))
        self.assertEqual(text, "小氣 2026-11-05 14/7 {不明}")


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "d.json")
        self.store.data["players"] = ["乙骨憂太", "耶穌基督"]

    def test_two_pages_merge_and_games(self):
        s = self.store.new_session()
        self.store.merge_sheet(s, Sheet(100, [Row(["乙骨太"], 45, True), Row(["耶穌基督"], 100, False)]))
        rows, flagged = self.store.merge_sheet(s, Sheet(100, [Row(["紅豆泥"], 84, True)]))
        self.assertEqual([m["name"] for m in s["members"]], ["乙骨憂太", "耶穌基督", "紅豆泥"])
        self.assertEqual(s["games"], 100)
        self.assertEqual((rows, flagged), (1, 1))

    def test_repaste_updates_not_duplicates(self):
        s = self.store.new_session()
        self.store.merge_sheet(s, Sheet(50, [Row(["耶穌基督"], 50, False)]))
        self.store.merge_sheet(s, Sheet(100, [Row(["耶穌基督"], 100, False)]))
        self.assertEqual(len(s["members"]), 1)
        self.assertEqual((s["members"][0]["runs"], s["games"]), (100, 100))

    def test_confirm_learns_alias(self):
        s = self.store.new_session()
        self.store.merge_sheet(s, Sheet(100, [Row(["元小榮", "元素小"], 100, False)]))
        m = s["members"][0]
        m["name"] = "元素小棠"
        self.store.confirm(m)
        s2 = self.store.new_session()
        self.store.merge_sheet(s2, Sheet(100, [Row(["元小榮"], 100, False)]))
        self.assertEqual((s2["members"][0]["name"], s2["members"][0]["flag"]), ("元素小棠", ""))

    def test_save_roundtrip(self):
        s = self.store.new_session()
        s["members"].append(member("乙骨憂太", 45, returned=True))
        self.store.save()
        again = Store(self.store.path)
        self.assertEqual(again.sessions[0]["members"][0]["name"], "乙骨憂太")
        self.assertTrue(again.sessions[0]["members"][0]["returned"])


if __name__ == "__main__":
    unittest.main()
