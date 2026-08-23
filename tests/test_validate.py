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
    def test_build_notify_text_basic(self):
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
        self.assertNotIn("【最强信号】", text)  # 已去掉，避免与今日要点重复
        # 无变化、无到期检验点、无跟踪表时不推空模板
        self.assertNotIn("验证打卡", text)
        self.assertNotIn("【今日变化】", text)
        self.assertNotIn("【今日验证】", text)
        self.assertNotIn("【接下来盯】", text)  # 已删除

    def test_build_notify_text_parses_verification_table(self):
        md = (
            "# 新闻联播风向标 | 2026-08-22\n\n"
            "## 今日要点\n\n要点。\n\n"
            "## 验证打卡\n\n"
            "| 主题 | 验证日期 | 验证条件 | 核验结果 |\n"
            "|------|---------|---------|---------|\n"
            "| 11 | 2026-08-22 | 商务部发布数据 | ✅ 已验证——商务部发布1-7月数据，"
            "高技术产业外资增长32.7%。来源：商务部（2026-08-22） |\n"
            "| 22 | 2026-08-22 | 以旧换新数据 | ⏳ 延迟验证——今日联播未出现相关数据，"
            "进入宽限期（+30天） |\n\n"
            "**异常缺席：** 无\n"
        )
        tracking = {
            "themes": [
                {"id": 11, "name": "外资吸引与高水平开放"},
                {"id": 22, "name": "以旧换新与两重建设"},
            ]
        }
        text = rd.build_notify_text(md, tracking=tracking)
        self.assertIn("【今日验证】", text)
        self.assertIn("外资吸引与高水平开放 ✅ 已验证", text)
        self.assertIn("以旧换新与两重建设 ⏳ 延迟验证", text)
        self.assertNotIn("主题11", text)
        self.assertNotIn("宽限期", text)  # 延迟验证不交代宽限期
        self.assertNotIn("异常缺席", text)  # 值为「无」时不出现
        self.assertNotIn("主题 核验结果", text)  # 表头行不进入结果

    def test_build_notify_text_abnormal_only(self):
        md = (
            "# 新闻联播风向标 | 2026-08-18\n\n"
            "## 今日要点\n\n要点。\n\n"
            "## 验证打卡\n\n"
            "| 主题 | 验证日期 | 验证条件 | 核验结果 |\n"
            "|------|---------|---------|---------|\n"
            "| 22 | 2026-08-15 | 以旧换新数据 | ⏳ 延迟验证——今日联播未出现相关数据 |\n\n"
            "**异常缺席：** 商务部数据今日应发布但未出现\n"
        )
        tracking = {"themes": [{"id": 22, "name": "以旧换新与两重建设"}]}
        text = rd.build_notify_text(md, tracking=tracking)
        self.assertIn("⚠️ 异常缺席：商务部数据今日应发布但未出现", text)

    def test_build_notify_text_today_changes(self):
        md = (
            "# 新闻联播风向标 | 2026-08-23\n\n"
            "## 今日要点\n\n要点。\n\n"
            "## 信号跟踪表\n\n### 今日生命周期事件\n\n"
            "| 日期 | 主题 | 类型 | 动作 | 证据 | 原因 |\n"
            "|------|------|------|------|------|------|\n"
            "| 2026-08-23 | 52 | create | 主题建档（首次纳入跟踪） | 联播第3条 | 新增 |\n"
            "| 2026-08-23 | 22 | status_change | 验证日期到期自动流转：跟踪中 → 延迟验证 | 证据 | 原因 |\n"
            "| 2026-08-23 | 30 | framework_change | 框架变更：竞争框架 → 安全框架 | 证据 | 原因 |\n"
            "| 2026-08-23 | 11 | update | 进展更新：外资数据发布 | 证据 | 原因 |\n"
            "## 验证打卡\n\n- 无到期检验点。\n"
        )
        tracking = {
            "themes": [
                {"id": 2, "name": "国家发展规划法立法推进",
                 "verification": {"status": "跟踪中", "date": "2026-08-25",
                                  "condition": "全国人大常委会表决通过国家发展规划法"}},
                {"id": 52, "name": "商业航天产业高地建设（山东模式）"},
                {"id": 22, "name": "以旧换新与两重建设"},
                {"id": 30, "name": "核电工程建设规模世界第一"},
                {"id": 11, "name": "外资吸引与高水平开放"},
            ]
        }
        text = rd.build_notify_text(md, tracking=tracking)
        self.assertIn("【今日变化】", text)
        self.assertIn("🆕 新主题：商业航天产业高地建设（山东模式）", text)
        self.assertIn("📌 以旧换新与两重建设：跟踪中 → 延迟验证", text)
        self.assertIn("🔄 核电工程建设规模世界第一：竞争框架 → 安全框架", text)
        self.assertNotIn("外资吸引与高水平开放", text)  # update 不推送
        self.assertNotIn("【接下来盯】", text)
        self.assertNotIn("全国人大常委会表决通过", text)  # 不带验证条件细节

    def test_build_notify_text_falls_back_to_raw(self):
        md = "纯文本兜底内容"
        self.assertEqual(rd.build_notify_text(md), md)


class TestPromptContract(unittest.TestCase):
    """PROMPT 硬性规则防回退（2026-08-23：承接必须写实质变化，禁止纯相关性声明）。"""

    @classmethod
    def setUpClass(cls):
        prompt_path = os.path.join(os.path.dirname(__file__), "..", "PROMPT.md")
        with open(prompt_path, encoding="utf-8") as f:
            cls.prompt = f.read()

    def test_today_keypoints_require_substantive_followup(self):
        self.assertIn("承接昨日主题仅限实质变化", self.prompt)
        self.assertIn("纯相关性", self.prompt)
        self.assertIn("一律不写", self.prompt)

    def test_verified_wording_requires_system_confirmation(self):
        self.assertIn("仅限系统已确认的验证结果", self.prompt)


if __name__ == "__main__":
    unittest.main()
