"""run_daily.validate_llm_result 单元测试（P1-5 schema 校验）。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import run_daily as rd  # noqa: E402


def valid_new_signal():
    return {
        "existing_theme_id": None,
        "new_theme": {
            "name": "新主题",
            "investment_hypothesis": "假设",
            "public_conduction": "政策信号可能传导至测试产业链实物工作量",
            "dimensions": {"level": "A", "novelty": "NEW", "specificity": "S1",
                           "policy_window": "开放", "verification_window": "SHORT",
                           "narrative_framework": "发展框架"},
            "framework_evidence": "依据",
            "lifecycle": [],
            "timeline": [],
            "outline_mapping": "",
            "verification": {"condition": "c", "source": "联播", "date": "2026-09-01",
                             "grace_period": "+30天", "status": "跟踪中"},
            "category": "产业政策与科技创新",
        },
    }


def valid_update_signal():
    return {
        "existing_theme_id": 30,
        "update": {
            "lifecycle_events": [],
            "dimensions": {"narrative_framework": "安全框架"},
        },
    }


def base_result(signals=None):
    return {
        "signals": signals if signals is not None else [valid_new_signal()],
        "expiry_check": "无到期检验点",
        "report_markdown": (
            "# 新闻联播风向标 | 2026-08-17\n\n"
            "## 今日要点\n\n测试要点。\n\n"
            "## 读报指南（怎么读这份报告）\n\n口径表。\n\n"
            "## 信号详析\n\n"
            "### 信号一：测试主题\n\n"
            "- **联播原文：** 第1条——测试。\n"
            "- **趋势判断：** 测试。\n"
            "- **投资假设：** 测试。\n"
            "- **层级/首次性/具体性/验证窗口：** A / NEW / S1 / SHORT\n"
            "- **政策窗口：** 开放。测试。\n"
            "- **叙事框架：** 发展框架。判定依据：测试。\n"
            "- **待验证：** 测试。\n\n"
            "## 信号跟踪表\n\n跟踪表。\n\n"
            "## 验证打卡\n\n- 无到期检验点。\n- 异常缺席：无\n"
        ),
    }


class TestValidate(unittest.TestCase):
    def test_valid_passes(self):
        errors, warnings = rd.validate_llm_result(base_result())
        self.assertEqual(errors, [])

    def test_top_level_not_dict(self):
        errors, _ = rd.validate_llm_result("hello")
        self.assertIn("顶层不是 JSON 对象", errors)

    def test_signals_not_list(self):
        r = base_result(); r["signals"] = "x"
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("signals" in e for e in errors))

    def test_more_than_4_signals_rejected(self):
        r = base_result(signals=[valid_new_signal()] * 5)
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("超过上限 4" in e for e in errors))

    def test_weak_condition_rejected(self):
        sig = valid_new_signal()
        sig["new_theme"]["verification"]["condition"] = (
            "政策信号可能传导至基础设施建设、新兴领域投资、消费升级等实物工作量")
        r = base_result(signals=[sig])
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("疑似不可证伪" in e for e in errors))

    def test_cycle_condition_rejected(self):
        sig = valid_new_signal()
        sig["new_theme"]["verification"]["condition"] = "联播报道高技术制造业增速延续或提升"
        r = base_result(signals=[sig])
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("循环条件/趋势延续" in e for e in errors))

    def test_non_iso_verification_date_rejected(self):
        sig = valid_new_signal()
        sig["new_theme"]["verification"]["date"] = "预计2026年10月前后"
        r = base_result(signals=[sig])
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("YYYY-MM-DD" in e for e in errors))

    def test_missing_public_conduction_rejected(self):
        sig = valid_new_signal()
        sig["new_theme"].pop("public_conduction")
        r = base_result(signals=[sig])
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("public_conduction" in e for e in errors))

    def test_verified_status_requires_verdict_event(self):
        sig = valid_update_signal()
        sig["update"]["verification"] = {"status": "已验证"}
        r = base_result(signals=[sig])
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("缺少 verify/decay 生命周期事件" in e for e in errors))

    def test_verified_status_with_verdict_event_passes(self):
        sig = valid_update_signal()
        sig["update"]["lifecycle_events"] = [
            {"date": "2026-08-17", "type": "verify", "action": "验证通过"}]
        sig["update"]["verification"] = {"status": "已验证"}
        r = base_result(signals=[sig])
        errors, _ = rd.validate_llm_result(r)
        self.assertEqual(errors, [])

    def test_update_written_as_first_entry_warns(self):
        sig = valid_update_signal()
        r = base_result(signals=[sig])
        r["report_markdown"] = r["report_markdown"].replace(
            "- **待验证：** 测试。",
            "- **待验证：** 已纳入跟踪表主题30（首次纳入）。")
        _, warnings = rd.validate_llm_result(r)
        self.assertTrue(any("口径矛盾" in w for w in warnings))

    def test_both_new_and_existing_rejected(self):
        r = base_result(); r["signals"] = [{**valid_new_signal(), "existing_theme_id": 5}]
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("二选一" in e for e in errors))

    def test_missing_name_is_error(self):
        r = base_result(); r["signals"][0]["new_theme"].pop("name")
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("name" in e for e in errors))

    def test_dimensions_not_dict_is_error(self):
        r = base_result(); r["signals"][0]["new_theme"]["dimensions"] = "A"
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("dimensions" in e for e in errors))

    def test_invalid_enum_is_warning_only(self):
        r = base_result(); r["signals"][0]["new_theme"]["dimensions"]["level"] = "X"
        errors, warnings = rd.validate_llm_result(r)
        self.assertEqual(errors, [])
        self.assertTrue(any("level" in w for w in warnings))

    def test_timeline_not_list_is_error(self):
        r = base_result(); r["signals"][0]["new_theme"]["timeline"] = "x"
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("timeline" in e for e in errors))

    def test_update_bad_enum_is_error(self):
        r = base_result([valid_update_signal()])
        r["signals"][0]["update"]["dimensions"] = {"level": "Z"}
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("level" in e for e in errors))

    def test_existing_id_string_digit_ok(self):
        r = base_result([valid_update_signal()])
        r["signals"][0]["existing_theme_id"] = "30"
        errors, _ = rd.validate_llm_result(r)
        self.assertEqual(errors, [])

    def test_existing_id_garbage_rejected(self):
        r = base_result([valid_update_signal()])
        r["signals"][0]["existing_theme_id"] = "abc"
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("existing_theme_id" in e for e in errors))

    def test_missing_report_markdown(self):
        r = base_result(); r.pop("report_markdown")
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("report_markdown" in e for e in errors))

    def test_missing_expiry_check_is_warning(self):
        r = base_result(); r.pop("expiry_check")
        errors, warnings = rd.validate_llm_result(r)
        self.assertEqual(errors, [])
        self.assertTrue(any("expiry_check" in w for w in warnings))

    def test_missing_section_is_error(self):
        r = base_result()
        r["report_markdown"] = r["report_markdown"].replace("## 验证打卡\n\n- 无到期检验点。\n- 异常缺席：无\n", "")
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("验证打卡" in e for e in errors))

    def test_section_order_error(self):
        r = base_result()
        r["report_markdown"] = r["report_markdown"].replace(
            "## 今日要点\n\n测试要点。\n\n## 读报指南",
            "## 读报指南\n\n口径表。\n\n## 今日要点\n\n测试要点。")
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("顺序" in e for e in errors))

    def test_signal_block_missing_field_is_error(self):
        r = base_result()
        r["report_markdown"] = r["report_markdown"].replace(
            "- **待验证：** 测试。\n", "")
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("待验证" in e for e in errors))

    def test_no_signal_block_when_signals_present_is_error(self):
        r = base_result()
        r["report_markdown"] = r["report_markdown"].replace(
            "### 信号一：测试主题\n\n", "")
        errors, _ = rd.validate_llm_result(r)
        self.assertTrue(any("至少一个" in e for e in errors))

    def test_empty_signals_allows_no_signal_block(self):
        r = base_result(signals=[])
        r["report_markdown"] = r["report_markdown"].replace(
            "### 信号一：测试主题\n\n", "")
        errors, _ = rd.validate_llm_result(r)
        self.assertEqual(errors, [])


class TestNotifyHelpers(unittest.TestCase):
    def test_build_notify_text_uses_today_key_points(self):
        md = (
            "# 新闻联播风向标 | 2026-08-17\n\n"
            "## 今日要点\n\n今日最重要的变化。\n\n"
            "## 读报指南（怎么读这份报告）\n\n口径表。\n\n"
            "## 信号详析\n\n"
            "### 信号一：示例主题\n\n"
            "- **联播原文：** 第1条——联播报道。\n"
            "- **趋势判断：** 测试。\n"
            "- **投资假设：** 测试。\n"
            "- **层级/首次性/具体性/验证窗口：** A / NEW / S1 / SHORT\n"
            "- **政策窗口：** 开放。\n"
            "- **叙事框架：** 发展框架。\n"
            "- **待验证：** 测试。\n\n"
            "## 信号跟踪表\n\n跟踪表。\n\n"
            "## 验证打卡\n\n- 无到期检验点。\n- 异常缺席：无\n"
        )
        text = rd.build_notify_text(md)
        self.assertIn("新闻联播风向标", text)
        self.assertIn("今日最重要的变化", text)
        self.assertNotIn("示例主题", text)
        self.assertNotIn("验证打卡", text)

    def test_build_notify_text_falls_back_to_raw(self):
        md = "纯文本兜底内容"
        self.assertEqual(rd.build_notify_text(md), md)


if __name__ == "__main__":
    unittest.main()
