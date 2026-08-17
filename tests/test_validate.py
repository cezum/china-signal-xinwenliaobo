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
        "report_markdown": "# 日报\n\n正文",
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


if __name__ == "__main__":
    unittest.main()
