"""report_enhance.py 单元测试：昨日回访 / 周报月报 / 静默检测。"""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import report_enhance as reh  # noqa: E402


def make_theme(theme_id, name="主题", status="跟踪中", lifecycle=None, timeline=None):
    return {
        "id": theme_id,
        "name": name,
        "investment_hypothesis": "假设",
        "dimensions": {"level": "B", "novelty": "PROGRESS", "specificity": "S2",
                       "policy_window": "开放", "verification_window": "MID",
                       "narrative_framework": "发展框架"},
        "framework_evidence": "依据",
        "lifecycle": lifecycle or [{"date": "2026-08-01", "type": "create",
                                    "action": "主题建档", "evidence": "e", "reason": "r"}],
        "timeline": timeline or [],
        "outline_mapping": "第一篇 第1章",
        "verification": {"condition": "条件", "source": "联播", "date": "2026-09-01",
                         "grace_period": "+30天", "status": status},
        "category": "大类A",
    }


def make_doc(themes):
    return {"meta": {}, "categories": [], "themes": themes}


class TestActivity(unittest.TestCase):
    def test_last_activity_takes_latest_of_lifecycle_and_timeline(self):
        t = make_theme(1, lifecycle=[
            {"date": "2026-08-01", "type": "create", "action": "建档"},
            {"date": "2026-08-20", "type": "update", "action": "进展更新"},
        ], timeline=[{"date": "2026-08-10", "event": "联播事件"}])
        self.assertEqual(reh.last_activity(t), date(2026, 8, 20))

    def test_themes_touched_on_filters_by_day(self):
        t1 = make_theme(1, lifecycle=[{"date": "2026-08-22", "type": "update", "action": "u"}])
        t2 = make_theme(2, lifecycle=[{"date": "2026-08-23", "type": "update", "action": "u"}])
        doc = make_doc([t1, t2])
        touched = reh.themes_touched_on(doc, "2026-08-22")
        self.assertEqual([t["id"] for t in touched], [1])


class TestFollowup(unittest.TestCase):
    def test_yesterday_only_theme_flagged_not_mentioned(self):
        t = make_theme(1, lifecycle=[{"date": "2026-08-22", "type": "update", "action": "进展更新"}])
        doc = make_doc([t])
        section = reh.build_followup_section(doc, "2026-08-23")
        self.assertIn("## 昨日回访", section)
        self.assertIn("今日未提及", section)
        self.assertNotIn("今日有进展", section)

    def test_theme_touched_both_days_flagged_continued(self):
        t = make_theme(1, lifecycle=[
            {"date": "2026-08-22", "type": "update", "action": "昨日进展"},
            {"date": "2026-08-23", "type": "update", "action": "今日进展"},
        ])
        doc = make_doc([t])
        section = reh.build_followup_section(doc, "2026-08-23")
        self.assertIn("✅ 今日有进展", section)

    def test_action_with_type_prefix_not_duplicated(self):
        t = make_theme(1, lifecycle=[
            {"date": "2026-08-22", "type": "update", "action": "进展更新：外资数据发布"},
            {"date": "2026-08-22", "type": "status_change",
             "action": "状态流转：跟踪中 → 延迟验证"},
        ])
        doc = make_doc([t])
        section = reh.build_followup_section(doc, "2026-08-23")
        self.assertNotIn("进展更新：进展更新", section)
        self.assertNotIn("状态流转：状态流转", section)
        self.assertIn("进展更新：外资数据发布", section)

    def test_no_yesterday_changes(self):
        t = make_theme(1, lifecycle=[{"date": "2026-08-23", "type": "update", "action": "u"}])
        doc = make_doc([t])
        section = reh.build_followup_section(doc, "2026-08-23")
        self.assertIn("无主题变动", section)


class TestSilence(unittest.TestCase):
    def test_silent_and_long_silent_tiers(self):
        active = make_theme(1, status="跟踪中", lifecycle=[
            {"date": "2026-08-03", "type": "update", "action": "u"}])
        long_silent = make_theme(2, status="延迟验证", lifecycle=[
            {"date": "2026-07-10", "type": "update", "action": "u"}])
        doc = make_doc([active, long_silent])
        section = reh.build_silence_section(doc, "2026-08-23")
        self.assertIn("主题1", section)
        self.assertIn("20 天", section)
        self.assertIn("主题2", section)
        self.assertIn("长期静默", section)

    def test_terminal_or_recent_statuses_excluded(self):
        verified = make_theme(1, status="已验证", lifecycle=[
            {"date": "2026-07-01", "type": "verify", "action": "v"}])
        decayed = make_theme(2, status="信号衰减", lifecycle=[
            {"date": "2026-07-01", "type": "decay", "action": "d"}])
        recent = make_theme(3, status="跟踪中", lifecycle=[
            {"date": "2026-08-22", "type": "update", "action": "u"}])
        doc = make_doc([verified, decayed, recent])
        section = reh.build_silence_section(doc, "2026-08-23")
        self.assertIn("无进展更新", section)
        self.assertNotIn("主题1", section)
        self.assertNotIn("主题2", section)
        self.assertNotIn("主题3", section)


class TestPeriodSections(unittest.TestCase):
    def test_weekly_includes_only_this_week(self):
        inside = make_theme(1, lifecycle=[
            {"date": "2026-08-18", "type": "update", "action": "u1"},
            {"date": "2026-08-22", "type": "update", "action": "u2"},
        ])
        outside = make_theme(2, lifecycle=[
            {"date": "2026-08-10", "type": "update", "action": "old"}])
        doc = make_doc([inside, outside])
        section = reh.build_weekly_section(doc, "2026-08-23")
        self.assertIn("## 本周回顾（周报）", section)
        self.assertIn("共 1 个主题有变动", section)
        self.assertIn("更新 2 次", section)
        self.assertIn("主题1", section)
        self.assertNotIn("主题2", section)

    def test_monthly_includes_only_this_month(self):
        inside = make_theme(1, lifecycle=[
            {"date": "2026-08-05", "type": "create", "action": "建档"}])
        outside = make_theme(2, lifecycle=[
            {"date": "2026-07-31", "type": "update", "action": "old"}])
        doc = make_doc([inside, outside])
        section = reh.build_monthly_section(doc, "2026-08-31")
        self.assertIn("## 本月回顾（月报）", section)
        self.assertIn("新增 1 个", section)
        self.assertNotIn("主题2", section)


class TestEnrichReport(unittest.TestCase):
    BASE_MD = (
        "# 新闻联播风向标 | 2026-08-23\n\n"
        "## 今日要点\n\n要点正文。\n\n"
        "## 读报指南（怎么读这份报告）\n\n口径表。\n\n"
        "## 验证打卡\n\n- 无到期检验点。\n\n"
        "---\n*数据源：CCTV*"
    )

    def test_sunday_gets_followup_weekly_and_silence(self):
        t = make_theme(1, lifecycle=[
            {"date": "2026-08-22", "type": "update", "action": "昨日进展"}])
        doc = make_doc([t])
        out = reh.enrich_report(self.BASE_MD, doc, "2026-08-23")
        self.assertLess(out.index("## 昨日回访"), out.index("## 读报指南"))
        self.assertIn("## 本周回顾（周报）", out)
        self.assertIn("## 静默主题检测", out)
        self.assertNotIn("## 本月回顾（月报）", out)

    def test_month_end_gets_monthly(self):
        doc = make_doc([make_theme(1)])
        out = reh.enrich_report(self.BASE_MD, doc, "2026-08-31")
        self.assertIn("## 本月回顾（月报）", out)
        self.assertNotIn("## 本周回顾（周报）", out)

    def test_followup_absent_when_no_yesterday_activity(self):
        doc = make_doc([make_theme(1)])
        out = reh.enrich_report(self.BASE_MD, doc, "2026-08-23")
        self.assertIn("## 昨日回访", out)
        self.assertIn("无主题变动", out)


class TestYesterdayFocusBlock(unittest.TestCase):
    def test_block_lists_yesterday_themes(self):
        t = make_theme(1, lifecycle=[
            {"date": "2026-08-22", "type": "update", "action": "进展更新"}])
        doc = make_doc([t])
        block = reh.yesterday_focus_block(doc, "2026-08-23")
        self.assertIn("## 昨日涉及主题", block)
        self.assertIn("主题1", block)

    def test_block_empty_without_yesterday_activity(self):
        doc = make_doc([make_theme(1)])
        self.assertEqual(reh.yesterday_focus_block(doc, "2026-08-23"), "")


class TestFactualCorrection(unittest.TestCase):
    """方案 A：落库后用真实跟踪表校正日报的可机器校验标注。"""

    def test_new_theme_claim_id_corrected(self):
        t = make_theme(53, name="示例测试主题", lifecycle=[
            {"date": "2026-08-23", "type": "create", "action": "建档"}])
        doc = make_doc([t])
        md = ("### 信号一：示例测试主题\n\n"
              "- **待验证：** 检验条件。已纳入跟踪表主题1（首次纳入）。")
        out = reh.correct_factual_claims(
            md, doc, [{"new_theme": {"name": "示例测试主题"}}], "2026-08-23")
        self.assertIn("已纳入跟踪表主题53（首次纳入）", out)
        self.assertNotIn("主题1", out)

    def test_existing_theme_claim_without_event_drops_kind(self):
        t = make_theme(42, name="下沉市场主题", lifecycle=[
            {"date": "2026-08-18", "type": "create", "action": "建档"}])
        doc = make_doc([t])
        md = "### 信号一：赛事经济\n\n- **待验证：** 需观察。已纳入跟踪表主题42（进展更新）。"
        out = reh.correct_factual_claims(
            md, doc, [{"existing_theme_id": 42}], "2026-08-23")
        self.assertIn("已纳入跟踪表主题42", out)
        self.assertNotIn("（进展更新）", out)

    def test_existing_theme_claim_verify_becomes_state_change(self):
        t = make_theme(19, lifecycle=[
            {"date": "2026-08-23", "type": "verify", "action": "验证通过"}])
        doc = make_doc([t])
        md = "### 信号一：就业\n\n- **待验证：** 已纳入跟踪表主题19（进展更新）。"
        out = reh.correct_factual_claims(
            md, doc, [{"existing_theme_id": 19}], "2026-08-23")
        self.assertIn("已纳入跟踪表主题19（状态变更）", out)

    def test_checkin_status_marker_corrected(self):
        t = make_theme(19, status="已验证", lifecycle=[
            {"date": "2026-08-23", "type": "verify", "action": "验证通过"}])
        doc = make_doc([t])
        md = ("## 验证打卡\n\n"
              "| 主题 | 验证日期 | 验证条件 | 核验结果 |\n"
              "|------|---------|---------|---------|\n"
              "| 19 | 2026-08-17 | 条件 | ⏳ 延迟验证——今日无报道 |\n")
        out = reh.correct_factual_claims(md, doc, [], "2026-08-23")
        self.assertIn("| 19 | 2026-08-17 | 条件 | ✅ 已验证——今日无报道 |", out)

    def test_no_match_preserved(self):
        doc = make_doc([make_theme(1)])
        md = "## 验证打卡\n\n- 无到期检验点。\n"
        out = reh.correct_factual_claims(md, doc, [], "2026-08-23")
        self.assertEqual(out, md)


if __name__ == "__main__":
    unittest.main()
