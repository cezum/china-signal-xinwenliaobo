"""run_daily.apply_result / apply_expiry_checks 单元测试（P1-1/P1-5/次要1）。"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import run_daily as rd  # noqa: E402


def make_doc():
    return {
        "meta": {"version": "1.1", "generated_at": "2026-08-13", "data_range": "x"},
        "categories": [{"name": "产业政策与科技创新", "theme_ids": [1]}],
        "themes": [
            {
                "id": 1,
                "name": "主题一",
                "investment_hypothesis": "h1",
                "dimensions": {"level": "A", "novelty": "NEW", "specificity": "S1",
                               "policy_window": "开放", "verification_window": "SHORT",
                               "narrative_framework": "发展框架"},
                "framework_evidence": "",
                "lifecycle": [],
                "timeline": [],
                "outline_mapping": "",
                "verification": {"condition": "c", "source": "联播", "date": "2026-09-01",
                                 "grace_period": "+30天", "status": "跟踪中"},
                "category": "产业政策与科技创新",
            }
        ],
    }


def new_theme_signal(name="新主题", **dim_overrides):
    dims = {"level": "B", "novelty": "PROGRESS", "specificity": "S2",
            "policy_window": "接近", "verification_window": "MID",
            "narrative_framework": "竞争框架"}
    dims.update(dim_overrides)
    return {
        "existing_theme_id": None,
        "new_theme": {
            "name": name,
            "investment_hypothesis": "h",
            "dimensions": dims,
            "framework_evidence": "e",
            "lifecycle": [{"date": "2026-08-16", "type": "create", "action": "建档"}],
            "timeline": [{"date": "2026-08-16", "event": "联播事件"}],
            "outline_mapping": "x",
            "verification": {"condition": "c", "source": "联播", "date": "2026-10-01",
                             "grace_period": "+30天", "status": "跟踪中"},
            "category": "绿色转型",
        },
    }


class TestApplyResult(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t_apply_")
        rd.PATHS["tracking"] = os.path.join(self.tmp, "tracking.json")

    def load(self):
        with open(os.path.join(self.tmp, "tracking.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_new_theme_added_and_stats_recomputed(self):
        doc = make_doc()
        stats = rd.apply_result(doc, {"signals": [new_theme_signal()]}, "2026-08-16")
        saved = self.load()
        self.assertEqual(stats["new"], 1)
        self.assertEqual(saved["stats"]["total"], 2)
        self.assertEqual(saved["stats"]["by_level"], {"A": 1, "B": 1})
        # P1-1：meta.generated_at 刷新
        self.assertEqual(saved["meta"]["generated_at"], "2026-08-16")
        # 新分类自动建立并挂上主题 id
        cats = {c["name"]: c["theme_ids"] for c in saved["categories"]}
        self.assertIn("绿色转型", cats)

    def test_verified_status_not_clobbered_by_plain_update(self):
        """P0-1 回归：已验证主题被无事件进展更新覆盖回跟踪中 → 忽略。"""
        doc = make_doc()
        theme = doc["themes"][0]
        theme["verification"]["status"] = "已验证"
        sig = {
            "existing_theme_id": 1,
            "update": {
                "lifecycle_events": [
                    {"date": "2026-08-17", "type": "update", "action": "进展更新"}],
                "verification": {"status": "跟踪中"},
            },
        }
        rd.apply_result(doc, {"signals": [sig]}, "2026-08-17")
        self.assertEqual(theme["verification"]["status"], "已验证")

    def test_status_change_allowed_with_verdict_event(self):
        """显式 status_change 事件 + 状态变更 → 允许。"""
        doc = make_doc()
        theme = doc["themes"][0]
        sig = {
            "existing_theme_id": 1,
            "update": {
                "lifecycle_events": [
                    {"date": "2026-08-17", "type": "status_change",
                     "action": "状态变更：跟踪中→已验证"}],
                "verification": {"status": "已验证"},
            },
        }
        rd.apply_result(doc, {"signals": [sig]}, "2026-08-17")
        self.assertEqual(theme["verification"]["status"], "已验证")

    def test_final_status_without_verdict_event_ignored(self):
        """无 verify/decay 事件时，跟踪中→已验证 被忽略（防 LLM 无出处写终态）。"""
        doc = make_doc()
        theme = doc["themes"][0]
        sig = {
            "existing_theme_id": 1,
            "update": {
                "lifecycle_events": [],
                "verification": {"status": "已验证"},
            },
        }
        rd.apply_result(doc, {"signals": [sig]}, "2026-08-17")
        self.assertEqual(theme["verification"]["status"], "跟踪中")

    def test_expiry_check_skips_theme_with_verdict(self):
        """P0-1 回归：lifecycle 有 verify 终判的主题，到期检查不得打回。"""
        doc = make_doc()
        theme = doc["themes"][0]
        theme["verification"] = {
            "condition": "c", "source": "联播", "date": "2026-08-01",
            "grace_period": "+7天", "status": "已验证",
        }
        theme["lifecycle"].append(
            {"date": "2026-08-16", "type": "verify", "action": "验证通过"})
        changed = rd.apply_expiry_checks(doc, "2026-08-16")
        self.assertEqual(changed, 0)
        self.assertEqual(theme["verification"]["status"], "已验证")

    def test_duplicate_name_skipped(self):
        doc = make_doc()
        stats = rd.apply_result(doc, {"signals": [new_theme_signal(name="主题一")]},
                                "2026-08-16")
        saved = self.load()
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(saved["stats"]["total"], 1)

    def test_string_id_coerced(self):
        doc = make_doc()
        sig = {"existing_theme_id": "1",
               "update": {"dimensions": {"level": "D"}, "lifecycle_events": []}}
        stats = rd.apply_result(doc, {"signals": [sig]}, "2026-08-16")
        saved = self.load()
        self.assertEqual(stats["updated"], 1)
        self.assertEqual(saved["themes"][0]["dimensions"]["level"], "D")

    def test_missing_id_counted(self):
        doc = make_doc()
        sig = {"existing_theme_id": 999, "update": {"dimensions": {"level": "D"}}}
        stats = rd.apply_result(doc, {"signals": [sig]}, "2026-08-16")
        self.assertEqual(stats["missing"], 1)

    def test_invalid_enum_coerced_to_default(self):
        doc = make_doc()
        stats = rd.apply_result(doc, {"signals": [new_theme_signal(level="X")]},
                                "2026-08-16")
        saved = self.load()
        self.assertEqual(stats["new"], 1)
        self.assertEqual(saved["themes"][1]["dimensions"]["level"], "未标注")

    def test_update_invalid_enum_ignored(self):
        doc = make_doc()
        sig = {"existing_theme_id": 1, "update": {"dimensions": {"level": "Z"}}}
        rd.apply_result(doc, {"signals": [sig]}, "2026-08-16")
        saved = self.load()
        self.assertEqual(saved["themes"][0]["dimensions"]["level"], "A")

    def test_empty_themes_ok(self):
        doc = make_doc()
        doc["themes"] = []
        doc["categories"] = []
        stats = rd.apply_result(doc, {"signals": [new_theme_signal()]}, "2026-08-16")
        saved = self.load()
        self.assertEqual(stats["new"], 1)
        self.assertEqual(saved["themes"][0]["id"], 1)


class TestExpiryChecks(unittest.TestCase):
    def test_review_after_grace_not_decay(self):
        # 宽限期过后联播无验证信号 → 不再自动判"信号衰减"，改"待复核"
        # （外部事件型验证点可能早已发生而未上联播，自动判死会误杀）
        doc = make_doc()
        doc["themes"][0]["verification"].update(
            {"date": "2026-08-01", "grace_period": "+5天", "status": "跟踪中"})
        changed = rd.apply_expiry_checks(doc, "2026-08-16")
        self.assertEqual(changed, 1)
        self.assertEqual(doc["themes"][0]["verification"]["status"], "待复核")
        self.assertEqual(doc["themes"][0]["lifecycle"][-1]["type"], "status_change")
        self.assertIn("人工外部核验", doc["themes"][0]["lifecycle"][-1]["reason"])

    def test_delayed_within_grace(self):
        doc = make_doc()
        doc["themes"][0]["verification"].update(
            {"date": "2026-08-10", "grace_period": "+30天", "status": "跟踪中"})
        changed = rd.apply_expiry_checks(doc, "2026-08-16")
        self.assertEqual(changed, 1)
        self.assertEqual(doc["themes"][0]["verification"]["status"], "延迟验证")

    def test_future_date_untouched(self):
        doc = make_doc()
        changed = rd.apply_expiry_checks(doc, "2026-08-01")
        self.assertEqual(changed, 0)
        self.assertEqual(doc["themes"][0]["verification"]["status"], "跟踪中")

    def test_verified_untouched(self):
        doc = make_doc()
        doc["themes"][0]["verification"].update(
            {"date": "2026-08-01", "grace_period": "0天", "status": "已验证"})
        changed = rd.apply_expiry_checks(doc, "2026-08-16")
        self.assertEqual(changed, 0)
        self.assertEqual(doc["themes"][0]["verification"]["status"], "已验证")

    def test_free_text_date_untouched(self):
        doc = make_doc()
        doc["themes"][0]["verification"].update(
            {"date": "待确认（视细则发布）", "grace_period": "+30天"})
        changed = rd.apply_expiry_checks(doc, "2026-08-16")
        self.assertEqual(changed, 0)


class TestIdleChecks(unittest.TestCase):
    """自动退出检查：已验证 14 天→线索；静默 30 天+过宽限期→待复核。"""

    def _theme(self, status="跟踪中", last_date="2026-08-01",
               ver_date="2026-09-01", grace="+30天"):
        doc = make_doc()
        t = doc["themes"][0]
        t["lifecycle"] = [{"date": last_date, "type": "create", "action": "建档"}]
        t["verification"].update(
            {"date": ver_date, "grace_period": grace, "status": status})
        return doc, t

    def test_verified_idle_14d_becomes_idea(self):
        doc, t = self._theme(status="已验证", last_date="2026-08-01")
        changed = rd.apply_idle_checks(doc, "2026-08-23")  # 静默 22 天
        self.assertEqual(changed, 1)
        self.assertEqual(t["verification"]["status"], "投资线索就绪")
        self.assertEqual(t["lifecycle"][-1]["type"], "status_change")
        self.assertIn("投资线索就绪", t["lifecycle"][-1]["action"])

    def test_verified_recent_untouched(self):
        doc, t = self._theme(status="已验证", last_date="2026-08-10")
        changed = rd.apply_idle_checks(doc, "2026-08-23")  # 静默 13 天
        self.assertEqual(changed, 0)
        self.assertEqual(t["verification"]["status"], "已验证")

    def test_silent_overdue_tracking_becomes_review(self):
        doc, t = self._theme(status="跟踪中", last_date="2026-07-01",
                             ver_date="2026-07-10", grace="+10天")
        changed = rd.apply_idle_checks(doc, "2026-08-23")
        self.assertEqual(changed, 1)
        self.assertEqual(t["verification"]["status"], "待复核")

    def test_silent_but_future_verification_untouched(self):
        doc, t = self._theme(status="跟踪中", last_date="2026-07-01",
                             ver_date="2026-09-10", grace="+30天")
        changed = rd.apply_idle_checks(doc, "2026-08-23")
        self.assertEqual(changed, 0)
        self.assertEqual(t["verification"]["status"], "跟踪中")

    def test_terminal_statuses_not_auto_reactivated(self):
        doc, t = self._theme(status="归档", last_date="2026-07-01")
        changed = rd.apply_idle_checks(doc, "2026-08-23")
        self.assertEqual(changed, 0)
        self.assertEqual(t["verification"]["status"], "归档")

        doc2, t2 = self._theme(status="待复核", last_date="2026-07-01")
        changed2 = rd.apply_idle_checks(doc2, "2026-08-23")
        self.assertEqual(changed2, 0)
        self.assertEqual(t2["verification"]["status"], "待复核")


if __name__ == "__main__":
    unittest.main()
