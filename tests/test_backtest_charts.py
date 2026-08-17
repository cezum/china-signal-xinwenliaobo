"""backtest_charts.py 单元测试：CSV 聚合、SVG 生成、索引输出。"""

import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import backtest_charts as bc  # noqa: E402


def write_monthly(tmp):
    path = os.path.join(tmp, "monthly_counts.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case", "group", "keyword", "month", "days_mentioned", "occurrences"])
        w.writerow(["real_estate", "old", "调控", "2024-01", "2", "3"])
        w.writerow(["real_estate", "new", "止跌回稳", "2024-01", "1", "1"])
        w.writerow(["real_estate", "old", "调控", "2024-02", "0", "0"])
        w.writerow(["real_estate", "new", "止跌回稳", "2024-02", "3", "4"])
    return path


class TestBacktestCharts(unittest.TestCase):
    def test_load_monthly_aggregates_days(self):
        tmp = tempfile.mkdtemp(prefix="t_chart_")
        write_monthly(tmp)
        series, months = bc.load_monthly(tmp)
        self.assertEqual(months, ["2024-01", "2024-02"])
        self.assertEqual(series[("real_estate", "old")]["2024-01"], 2.0)
        self.assertEqual(series[("real_estate", "new")]["2024-02"], 3.0)

    def test_svg_contains_two_series_and_legend(self):
        tmp = tempfile.mkdtemp(prefix="t_chart_")
        write_monthly(tmp)
        series, months = bc.load_monthly(tmp)
        svg = bc.svg_for_case("real_estate", "房地产案例", series, months)
        self.assertIn("<polyline", svg)
        self.assertIn("旧政策组", svg)
        self.assertIn("新政策组", svg)

    def test_build_index(self):
        tmp = tempfile.mkdtemp(prefix="t_chart_")
        write_monthly(tmp)
        series, months = bc.load_monthly(tmp)
        bc.build_index(["real_estate"], {"real_estate": "房地产案例"}, tmp)
        self.assertTrue(os.path.exists(os.path.join(tmp, "index.html")))


if __name__ == "__main__":
    unittest.main()
