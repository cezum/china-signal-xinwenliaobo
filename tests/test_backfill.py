"""backfill_xwlb.py 单元测试：日期迭代与缓存判断。"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import backfill_xwlb as bf  # noqa: E402


class TestIterDates(unittest.TestCase):
    def test_newest_first_default(self):
        dates = list(bf.iter_dates("2024-01-01", "2024-01-05"))
        self.assertEqual(dates, [
            "2024-01-05", "2024-01-04", "2024-01-03",
            "2024-01-02", "2024-01-01",
        ])

    def test_oldest_first(self):
        dates = list(bf.iter_dates("2024-01-01", "2024-01-05", oldest_first=True))
        self.assertEqual(dates, [
            "2024-01-01", "2024-01-02", "2024-01-03",
            "2024-01-04", "2024-01-05",
        ])

    def test_single_day(self):
        self.assertEqual(list(bf.iter_dates("2024-01-01", "2024-01-01")), ["2024-01-01"])


class TestCacheOk(unittest.TestCase):
    def test_valid_cache(self):
        tmp = tempfile.mkdtemp(prefix="t_backfill_")
        path = os.path.join(tmp, "xwlb_20240101_full.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"items": [{"title": "x"}]}, f)
        self.assertTrue(bf.cache_ok(path))

    def test_missing_or_corrupt(self):
        tmp = tempfile.mkdtemp(prefix="t_backfill_")
        missing = os.path.join(tmp, "missing.json")
        self.assertFalse(bf.cache_ok(missing))
        corrupt = os.path.join(tmp, "corrupt.json")
        with open(corrupt, "w", encoding="utf-8") as f:
            f.write("{bad")
        self.assertFalse(bf.cache_ok(corrupt))


if __name__ == "__main__":
    unittest.main()
