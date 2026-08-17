"""keyword_stats.py 单元测试：单日计数。"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import keyword_stats as ks  # noqa: E402


def write_corpus(tmp):
    path = os.path.join(tmp, "xwlb_20240101_full.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "items": [
                {"title": "止跌回稳", "text": "促进房地产市场止跌回稳"},
                {"title": "房住不炒", "text": "坚持房住不炒"},
            ]
        }, f)
    return path


class TestDayCounts(unittest.TestCase):
    def test_counts_keywords(self):
        tmp = tempfile.mkdtemp(prefix="t_kw_")
        path = write_corpus(tmp)
        cases = {
            "real_estate": {
                "old": ["房住不炒"],
                "new": ["止跌回稳"],
            }
        }
        counts = ks.day_counts(path, cases)
        self.assertEqual(counts[("real_estate", "old", "房住不炒")], (1, 2))
        self.assertEqual(counts[("real_estate", "new", "止跌回稳")], (1, 2))


if __name__ == "__main__":
    unittest.main()
