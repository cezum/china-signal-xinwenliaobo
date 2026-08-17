"""fetch_xwlb.py 解析器 fixture 测试（不访问网络）。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import fetch_xwlb as fx  # noqa: E402

CCTV_FIXTURE = """<html><body>
<ul>
<li>
  <a href="https://tv.cctv.com/v/first/img.jpg"><img src="x.jpg"></a>
  <a href="https://tv.cctv.com/2026/08/12/VIDExxx.shtml" title="[视频]【新思想引领新征程】积极安全有序发展核电"><span>00:02:31</span></a>
</li>
<li>
  <a href="https://tv.cctv.com/2026/08/12/VIDEfull.shtml" title="[视频]《新闻联播》20260812 完整版"><span>00:30:00</span></a>
</li>
<li>
  <a href="https://tv.cctv.com/2027/01/01/VIDEyyy.shtml" title="[视频]2027年新条目"><span>00:01:00</span></a>
</li>
<li>普通文本，无链接</li>
</ul>
</body></html>"""

MRXWLB_FIXTURE = """<html><body>
<div class="entry-content">
<p><strong>新闻联播主要内容</strong></p>
<ul>
  <li>新闻联播主要内容</li>
  <li>第一条标题</li>
  <li>第二条标题</li>
</ul>
<p><strong>第一条标题</strong></p>
<p>第一条正文内容。</p>
<p><strong>第二条标题</strong></p>
<p>第二条正文内容。</p>
<p><strong>快讯子条目</strong></p>
<p>快讯正文内容。</p>
<!-- .entry-content -->
</div>
</body></html>"""


class TestCctvDayPage(unittest.TestCase):
    def test_parses_items_and_strips_prefix(self):
        items = fx.parse_cctv_day_page(CCTV_FIXTURE)
        titles = [it["title"] for it in items]
        self.assertIn("【新思想引领新征程】积极安全有序发展核电", titles)

    def test_full_episode_skipped(self):
        items = fx.parse_cctv_day_page(CCTV_FIXTURE)
        self.assertFalse(any("完整版" in it["title"] for it in items))

    def test_year_not_hardcoded(self):
        # 2027 年链接也能解析（修复写死 2026 的问题）
        items = fx.parse_cctv_day_page(CCTV_FIXTURE)
        self.assertTrue(any(it["url"].startswith("https://tv.cctv.com/2027/")
                            for it in items))

    def test_duration_captured(self):
        items = fx.parse_cctv_day_page(CCTV_FIXTURE)
        by_title = {it["title"]: it for it in items}
        self.assertEqual(
            by_title["【新思想引领新征程】积极安全有序发展核电"]["duration"],
            "00:02:31")


class TestMrxwlbParser(unittest.TestCase):
    def test_items_and_text(self):
        items = fx.parse_mrxwlb(MRXWLB_FIXTURE)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "第一条标题")
        self.assertIn("第一条正文内容", items[0]["text"])
        self.assertIn("第二条正文内容", items[1]["text"])
        # 未命中主要内容标题的 <strong> 作为子标题并入当前条目
        self.assertIn("快讯子条目", items[1]["text"])
        self.assertIn("快讯正文内容", items[1]["text"])

    def test_missing_entry_content(self):
        self.assertEqual(fx.parse_mrxwlb("<html>no content</html>"), [])


class TestMrxwlbUrl(unittest.TestCase):
    def test_title_uses_unpadded_month_day(self):
        # mrxwlb 文章 slug 的标题部分不加前导零；路径部分保留前导零。
        url = fx.mrxwlb_url("2021-01-25")
        self.assertIn("/2021/01/25/", url)
        self.assertIn("%E5%B9%B41%E6%9C%8825%E6%97%A5", url)
        self.assertNotIn("%E5%B9%B401", url)


class TestRenderMarkdown(unittest.TestCase):
    def test_item_numbers(self):
        result = {
            "source_name": "CCTV央视网（tv.cctv.com）",
            "items": [{"title": "甲", "text": "正文甲"}, {"title": "乙", "text": ""}],
        }
        md = fx.render_markdown(result, "2026-08-12")
        self.assertIn("第1条：甲", md)
        self.assertIn("第2条：乙", md)
        self.assertIn("正文甲", md)


if __name__ == "__main__":
    unittest.main()
