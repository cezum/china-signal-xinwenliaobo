"""render_tracking_table.py 渲染健壮性单元测试（P1-1/次要8）。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import render_tracking_table as rt  # noqa: E402


def make_theme(theme_id, name="主题", level="A", category="大类A", evidence="依据"):
    return {
        "id": theme_id,
        "name": name,
        "investment_hypothesis": "假设",
        "dimensions": {"level": level, "novelty": "NEW", "specificity": "S1",
                       "policy_window": "开放", "verification_window": "SHORT",
                       "narrative_framework": "发展框架"},
        "framework_evidence": evidence,
        "lifecycle": [{"date": "2026-08-16", "type": "create", "action": "建档",
                       "evidence": "证据", "reason": "原因"}],
        "timeline": [{"date": "2026-08-16", "event": "事件"}],
        "outline_mapping": "第一篇 第1章",
        "verification": {"condition": "条件", "source": "联播", "date": "2026-09-01",
                         "grace_period": "+30天", "status": "跟踪中"},
        "category": category,
    }


def make_doc(themes=None, meta=None):
    doc = {
        "meta": meta or {"version": "1.1", "generated_at": "2026-08-16",
                         "data_range": "2026-03-01 至 2026-08-12",
                         "headline_total": 1795, "prescreened_signals": 708},
        "categories": [{"name": "大类A", "theme_ids": [1]}],
        "themes": themes if themes is not None else [make_theme(1)],
    }
    from common import recompute_stats
    recompute_stats(doc)
    return doc


class TestHelpers(unittest.TestCase):
    def test_pct_zero_total(self):
        self.assertEqual(rt.pct(0, 0), 0)
        self.assertEqual(rt.pct(1, 2), 50)

    def test_cn_num(self):
        self.assertEqual(rt.cn_num(1), "一")
        self.assertEqual(rt.cn_num(10), "十")
        self.assertEqual(rt.cn_num(11), "十一")
        self.assertEqual(rt.cn_num(20), "二十")
        self.assertEqual(rt.cn_num(35), "三十五")
        self.assertEqual(rt.cn_num(99), "九十九")
        self.assertEqual(rt.cn_num(100), "100")

    def test_esc(self):
        self.assertEqual(rt.esc("a|b"), "a\\|b")
        self.assertEqual(rt.esc("a\nb"), "a<br>b")


class TestRenderFull(unittest.TestCase):
    def test_empty_doc_no_crash(self):
        doc = make_doc(themes=[])
        text = rt.render_full(doc)
        self.assertIn("| **合计** | **0** | **100%** |", text)
        self.assertIn("（跟踪表为空，暂无统计）", text)

    def test_more_than_10_categories(self):
        themes = [make_theme(i, category=f"大类{i}") for i in range(1, 13)]
        doc = make_doc(themes=themes)
        doc["categories"] = [{"name": f"大类{i}", "theme_ids": [i]} for i in range(1, 13)]
        from common import recompute_stats
        recompute_stats(doc)
        text = rt.render_full(doc)
        self.assertIn("十一、大类11", text)
        self.assertIn("十二、大类12", text)

    def test_stale_stats_recomputed(self):
        # 模拟旧 stats 缺少主题当前维度值（P1-1 崩溃场景）：
        # 渲染必须基于 themes 重算而不是信任旧 stats
        doc = make_doc(themes=[make_theme(1, level="D")])
        doc["stats"]["by_level"] = {"A": 1}  # 故意写坏
        text = rt.render_full(doc)
        self.assertNotIn("KeyError", text)
        self.assertIn("D", text)

    def test_meta_driven_headline_numbers(self):
        doc = make_doc(meta={"version": "1.1", "generated_at": "x",
                             "data_range": "r", "headline_total": 2000,
                             "prescreened_signals": 800})
        text = rt.render_full(doc)
        self.assertIn("| 联播标题总数 | 2000 条 |", text)
        self.assertIn("| 算法预筛选信号数 | 800 条 |", text)

    def test_quality_conclusions_dynamic(self):
        doc = make_doc()
        text = rt.render_full(doc)
        # 100% NEW → 应出现“占比高”口径而非固定“超七成”
        self.assertIn("NEW信号占比100%", text)
        self.assertIn("占比高", text)


class TestRenderDigest(unittest.TestCase):
    def test_escapes_pipe_and_newline(self):
        theme = make_theme(1, name="带|竖线\n和换行")
        doc = make_doc(themes=[theme])
        text = rt.render_digest(doc)
        self.assertIn("带\\|竖线<br>和换行", text)

    def test_missing_dimension_keys_safe(self):
        theme = make_theme(1)
        theme["dimensions"].pop("level")
        doc = make_doc(themes=[theme])
        text = rt.render_digest(doc)
        self.assertIn("未标注", text)


class TestRenderTracking(unittest.TestCase):
    def test_short_logic_prefers_arrow_right_side(self):
        theme = make_theme(1)
        theme["investment_hypothesis"] = "政策背景描述 → 城市防洪排涝工程、监测预警装备、应急产业订单加速"
        self.assertTrue(rt.short_logic(theme).startswith("城市防洪排涝工程"))

    def test_short_logic_falls_back_to_verification_condition(self):
        theme = make_theme(1)
        theme["investment_hypothesis"] = ""
        theme["verification"]["condition"] = "应急管理部发布防洪排涝专项方案"
        self.assertEqual(rt.short_logic(theme), "应急管理部发布防洪排涝专项方案")

    def test_wind_maps_tracking_open_to_go(self):
        theme = make_theme(1)
        theme["verification"]["status"] = "跟踪中"
        theme["dimensions"]["policy_window"] = "开放"
        self.assertEqual(rt.wind(theme), ("🟢", "抓紧落"))

    def test_render_tracking_has_five_columns_and_legend(self):
        doc = make_doc(themes=[make_theme(1)])
        text = rt.render_tracking(doc)
        self.assertIn("| # | 主题 | 风向 | 验证日期 | 盯什么 |", text)
        self.assertIn("## 风向图例", text)
        self.assertIn("🟢 抓紧落", text)


if __name__ == "__main__":
    unittest.main()
