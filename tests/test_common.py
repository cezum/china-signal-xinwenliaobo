"""common.py 单元测试：原子写入、备份恢复、统计重算。"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import common  # noqa: E402


class TestAtomicWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t_common_")
        self.path = os.path.join(self.tmp, "sub", "out.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def test_write_atomic_creates_dirs(self):
        common.write_atomic(self.path, "hello")
        self.assertEqual(common.read_text(self.path), "hello")

    def test_write_backup(self):
        common.write_atomic(self.path, "v1")
        common.write_atomic(self.path, "v2", backup=True)
        self.assertEqual(common.read_text(self.path), "v2")
        self.assertEqual(common.read_text(self.path + ".bak"), "v1")

    def test_no_half_written_tmp_left(self):
        common.write_atomic(self.path, "content")
        leftovers = [f for f in os.listdir(os.path.dirname(self.path))
                     if f.startswith(".tmp-")]
        self.assertEqual(leftovers, [])

    def test_read_json_recovers_from_bak(self):
        common.write_json(self.path, {"a": 1})
        common.write_json(self.path, {"a": 2}, backup=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{corrupt")
        self.assertEqual(common.read_json(self.path), {"a": 1})

    def test_read_json_raises_without_bak(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{corrupt")
        with self.assertRaises(ValueError):
            common.read_json(self.path)

    def test_write_json_valid_and_newline_terminated(self):
        common.write_json(self.path, {"a": "中文"})
        raw = common.read_text(self.path)
        self.assertTrue(raw.endswith("\n"))
        self.assertEqual(json.loads(raw), {"a": "中文"})


class TestRecomputeStats(unittest.TestCase):
    def make_doc(self):
        return {
            "meta": {},
            "categories": [
                {"name": "大类A", "theme_ids": [1]},
                {"name": "大类B", "theme_ids": []},
            ],
            "themes": [
                {"id": 1, "name": "t1", "dimensions": {
                    "level": "A", "novelty": "NEW", "specificity": "S1",
                    "policy_window": "开放", "verification_window": "SHORT",
                    "narrative_framework": "发展框架"}},
                {"id": 2, "name": "t2", "dimensions": {
                    "level": "B", "novelty": "PROGRESS", "specificity": "S2",
                    "policy_window": "接近", "verification_window": "MID",
                    "narrative_framework": "安全框架"}},
            ],
        }

    def test_counts(self):
        doc = self.make_doc()
        stats = common.recompute_stats(doc)
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["by_level"], {"A": 1, "B": 1})
        self.assertEqual(stats["by_category"], {"大类A": 1, "大类B": 0})
        self.assertIs(doc["stats"], stats)

    def test_missing_dimensions_fallback(self):
        doc = self.make_doc()
        doc["themes"][1]["dimensions"] = None
        stats = common.recompute_stats(doc)
        self.assertEqual(stats["by_level"]["未标注"], 1)

    def test_new_value_appears_in_stats(self):
        # 更新维度后旧统计里不存在的值也能被统计（P1-1 修复验证）
        doc = self.make_doc()
        doc["themes"][0]["dimensions"]["level"] = "D"
        stats = common.recompute_stats(doc)
        self.assertEqual(stats["by_level"], {"D": 1, "B": 1})

    def test_empty_doc(self):
        doc = {"meta": {}, "categories": [], "themes": []}
        stats = common.recompute_stats(doc)
        self.assertEqual(stats["total"], 0)


if __name__ == "__main__":
    unittest.main()
