"""verify_external.py 单元测试：候选筛选、检索解析、判定与状态流转。"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import verify_external as vx  # noqa: E402


def make_theme(tid, status="跟踪中", date="2026-08-01", name="主题", url=""):
    return {
        "id": tid,
        "name": name,
        "verification": {
            "condition": "商务部发布数据",
            "source": "商务部公开发布(外部检验)",
            "date": date,
            "grace_period": "+14天",
            "status": status,
            "external_url": url,
        },
        "lifecycle": [],
    }


def make_doc(themes):
    return {"meta": {}, "categories": [], "themes": themes}


class TestCandidates(unittest.TestCase):
    def test_review_status_selected(self):
        doc = make_doc([make_theme(1, status="待复核")])
        self.assertEqual([t["id"] for t in vx.candidates(doc, "2026-08-16")], [1])

    def test_due_tracking_selected(self):
        doc = make_doc([
            make_theme(1, status="跟踪中", date="2026-08-10"),
            make_theme(2, status="跟踪中", date="2026-09-01"),
            make_theme(3, status="已验证", date="2026-08-01"),
        ])
        self.assertEqual([t["id"] for t in vx.candidates(doc, "2026-08-16")], [1])

    def test_only_review(self):
        doc = make_doc([
            make_theme(1, status="待复核"),
            make_theme(2, status="跟踪中", date="2026-08-10"),
        ])
        out = vx.candidates(doc, "2026-08-16", only_review=True)
        self.assertEqual([t["id"] for t in out], [1])

    def test_retry_suppression_and_force(self):
        doc = make_doc([make_theme(1, status="待复核")])
        doc["themes"][0]["verification"]["last_verify_attempt"] = "2026-08-15"
        self.assertEqual(vx.candidates(doc, "2026-08-16"), [])
        self.assertEqual(len(vx.candidates(doc, "2026-08-16", force=True)), 1)
        doc["themes"][0]["verification"]["last_verify_attempt"] = "2026-08-10"
        self.assertEqual(len(vx.candidates(doc, "2026-08-16")), 1)

    def test_free_text_date_ignored(self):
        doc = make_doc([make_theme(1, status="跟踪中", date="2026-08-01（已过检验点）")])
        self.assertEqual(vx.candidates(doc, "2026-08-16"), [])

    def test_lianbo_type_skipped(self):
        # 联播型验证点（source=联播 且无 external_url）不参与外部查证
        doc = make_doc([make_theme(1, status="待复核")])
        doc["themes"][0]["verification"]["source"] = "联播"
        self.assertEqual(vx.candidates(doc, "2026-08-16"), [])

    def test_external_type_selected(self):
        # 外部型验证点（有 external_url 或 source 标注外部）参与查证
        doc = make_doc([make_theme(1, status="待复核", url="https://mofcom.gov.cn/x.html")])
        doc["themes"][0]["verification"]["source"] = "商务部公开发布(外部检验)"
        self.assertEqual([t["id"] for t in vx.candidates(doc, "2026-08-16")], [1])


class TestBingSearch(unittest.TestCase):
    FIXTURE = """
<html><body>
<ol id="b_results">
<li class="b_algo">
  <h2><a href="https://example.com/data" h="ID=SERP,1">商务部发布数据标题</a></h2>
  <div class="b_caption"><p>这是摘要内容一。</p></div>
</li>
<li class="b_algo">
  <h2><a href="https://example.org/news" h="ID=SERP,2">第二条标题</a></h2>
  <div class="b_caption"><p>这是摘要内容二。</p></div>
</li>
</ol>
</body></html>
"""

    def test_extract_results(self):
        with mock.patch.object(vx, "fetch_url", return_value=self.FIXTURE):
            text = vx.bing_search("测试")
        self.assertIn("商务部发布数据标题", text)
        self.assertIn("摘要内容一", text)
        self.assertIn("https://example.com/data", text)

    def test_empty_on_failure(self):
        with mock.patch.object(vx, "fetch_url", return_value=None):
            self.assertEqual(vx.bing_search("x"), "")


class TestSearchChannels(unittest.TestCase):
    def test_bing_first_then_ddg(self):
        with mock.patch.object(vx, "bing_search", return_value="bing结果") as m_b, \
             mock.patch.object(vx, "ddg_search", return_value="ddg结果") as m_d:
            text, channel = vx.search("查询")
        self.assertEqual((text, channel), ("bing结果", "bing"))
        m_d.assert_not_called()

    def test_fallback_when_bing_empty(self):
        with mock.patch.object(vx, "bing_search", return_value=""), \
             mock.patch.object(vx, "ddg_search", return_value="ddg结果"):
            text, channel = vx.search("查询")
        self.assertEqual((text, channel), ("ddg结果", "ddg"))

    def test_all_fail(self):
        with mock.patch.object(vx, "bing_search", return_value=""), \
             mock.patch.object(vx, "ddg_search", return_value=""):
            self.assertEqual(vx.search("查询"), ("", ""))

    def test_env_channel_order(self):
        with mock.patch.object(vx, "env_or", return_value="ddg,bing"), \
             mock.patch.object(vx, "bing_search", return_value="bing结果"), \
             mock.patch.object(vx, "ddg_search", return_value="ddg结果"):
            text, channel = vx.search("查询")
        self.assertEqual((text, channel), ("ddg结果", "ddg"))


class TestDdgSearch(unittest.TestCase):
    FIXTURE = """
<html><body>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdata">标题一</a>
  <a class="result__snippet">摘要一</a>
</div>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fnews">标题二</a>
  <a class="result__snippet">摘要二</a>
</div>
</body></html>
"""

    def test_extract_results_and_decode_uddg(self):
        with mock.patch.object(vx, "fetch_url", return_value=self.FIXTURE):
            text = vx.ddg_search("测试查询")
        self.assertIn("标题一", text)
        self.assertIn("摘要一", text)
        self.assertIn("https://example.com/data", text)  # uddg 已解码
        self.assertNotIn("duckduckgo.com/l/", text)

    def test_empty_on_fetch_failure(self):
        with mock.patch.object(vx, "fetch_url", return_value=None):
            self.assertEqual(vx.ddg_search("x"), "")


class TestGather(unittest.TestCase):
    def test_external_url_priority(self):
        theme = make_theme(1, url="https://mofcom.gov.cn/data.html")
        with mock.patch.object(vx, "fetch_url", return_value="<p>官方正文</p>") as m:
            snippet, label, strong = vx.gather(theme, "条件")
        self.assertIn("官方正文", snippet)
        self.assertIn("官方页面", label)
        self.assertTrue(strong)
        m.assert_called_once()

    def test_bad_scheme_does_not_auto_verify(self):
        theme = make_theme(1, url="javascript:alert(1)")
        with mock.patch.object(vx, "fetch_url", return_value=None):
            snippet, label, strong = vx.gather(theme, "条件")
        self.assertEqual(snippet, "")
        self.assertEqual(label, "")
        self.assertFalse(strong)

    def test_official_url_failure_does_not_fall_back_to_search(self):
        theme = make_theme(1, url="https://mofcom.gov.cn/data.html")
        with mock.patch.object(vx, "fetch_url", side_effect=Exception("boom")):
            snippet, label, strong = vx.gather(theme, "条件")
        self.assertEqual(snippet, "")
        self.assertFalse(strong)

    def test_non_official_url_is_weak_evidence(self):
        theme = make_theme(1, url="https://example.com/data.html")
        with mock.patch.object(vx, "fetch_url", return_value="<p>正文</p>"):
            snippet, label, strong = vx.gather(theme, "条件")
        self.assertEqual(snippet, "")
        self.assertIn("非官方", label)
        self.assertFalse(strong)


class TestJudge(unittest.TestCase):
    def test_judge_returns_verdict(self):
        with mock.patch.object(vx, "call_llm", return_value={
                "conclusion": "verified", "evidence": "已发布", "reason": "官方页"}) as m:
            verdict = vx.judge("条件", "资料")
        self.assertEqual(verdict["conclusion"], "verified")
        user = m.call_args[0][1]
        self.assertIn("条件", user)
        self.assertIn("资料", user)

    def test_invalid_conclusion_falls_back(self):
        with mock.patch.object(vx, "call_llm", return_value={"conclusion": "maybe"}):
            self.assertEqual(vx.judge("条件", "资料")["conclusion"], "uncertain")

    def test_non_dict_falls_back(self):
        with mock.patch.object(vx, "call_llm", return_value=["not", "a", "dict"]):
            self.assertEqual(vx.judge("条件", "资料")["conclusion"], "uncertain")


class TestApplyVerdict(unittest.TestCase):
    def test_verified(self):
        doc = make_doc([make_theme(1, status="待复核")])
        t = doc["themes"][0]
        changed = vx.apply_verdict(
            doc, t,
            {"conclusion": "verified", "evidence": "7/23发布", "reason": "官网"},
            "2026-08-16", "官方页面 https://x")
        self.assertEqual(changed, 1)
        self.assertEqual(t["verification"]["status"], "已验证")
        self.assertEqual(t["verification"]["last_verify_attempt"], "2026-08-16")
        self.assertEqual(t["lifecycle"][-1]["type"], "verify")
        self.assertIn("7/23发布", t["lifecycle"][-1]["evidence"])

    def test_not_verified(self):
        doc = make_doc([make_theme(1, status="待复核")])
        t = doc["themes"][0]
        changed = vx.apply_verdict(
            doc, t,
            {"conclusion": "not_verified", "evidence": "未见发布", "reason": "检索"},
            "2026-08-16", "")
        self.assertEqual(changed, 1)
        self.assertEqual(t["verification"]["status"], "信号衰减")
        self.assertEqual(t["lifecycle"][-1]["type"], "decay")

    def test_uncertain_keeps_status(self):
        doc = make_doc([make_theme(1, status="待复核")])
        t = doc["themes"][0]
        changed = vx.apply_verdict(
            doc, t,
            {"conclusion": "uncertain", "evidence": "", "reason": "资料不足"},
            "2026-08-16", "联网检索")
        self.assertEqual(changed, 0)
        self.assertEqual(t["verification"]["status"], "待复核")
        self.assertEqual(t["lifecycle"][-1]["type"], "update")


class TestApplyReviewPending(unittest.TestCase):
    def test_tracking_becomes_review(self):
        doc = make_doc([make_theme(1, status="跟踪中")])
        t = doc["themes"][0]
        changed = vx.apply_review_pending(
            doc, t, "2026-08-16", "仅有搜索摘要", "联网检索[bing]")
        self.assertEqual(changed, 1)
        self.assertEqual(t["verification"]["status"], "待复核")
        self.assertEqual(t["verification"]["last_verify_attempt"], "2026-08-16")
        self.assertEqual(t["lifecycle"][-1]["type"], "status_change")

    def test_already_review_keeps_status(self):
        doc = make_doc([make_theme(1, status="待复核")])
        t = doc["themes"][0]
        changed = vx.apply_review_pending(
            doc, t, "2026-08-16", "仍无法确认", "")
        self.assertEqual(changed, 0)
        self.assertEqual(t["verification"]["status"], "待复核")
        self.assertEqual(t["lifecycle"][-1]["type"], "update")


if __name__ == "__main__":
    unittest.main()
