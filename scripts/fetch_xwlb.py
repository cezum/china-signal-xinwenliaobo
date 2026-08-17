#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""获取某日《新闻联播》全文。

主源：CCTV 央视网官方（tv.cctv.com）
备份：mrxwlb.com（文字版镜像）

用法：
    python fetch_xwlb.py --date 2026-08-11
    python fetch_xwlb.py                  # 默认今天
    python fetch_xwlb.py --date 2026-08-11 --outdir E:/path/to/data

输出：
    xwlb_{YYYYMMDD}_full.json  结构化条目（标题/链接/时长/正文/来源）
    xwlb_{YYYYMMDD}_text.md    全文 Markdown（与旧版格式兼容，条目带“第N条”序号）

修复背景（代码审查 2026-08-16）：
- 次要 4 CCTV 正则不再写死 2026 年份（\\d{4}），跨年可用；
- 次要 2 备份源质量校验：正文全部为空（仅剩标题列表）判定不可用；
- 次要 5 输出文本标注“第N条”，与 Prompt/日报的对账口径一致；
- 次要 6 缓存一致性：JSON 在而 MD 缺失时补写 MD，消除中断死锁；
- P1-3 关键文件原子写入（common.write_atomic）；
- 安全 1 mrxwlb 改用 HTTPS，失败时回退 HTTP（仅告警）。
"""

import argparse
import gzip
import html as html_mod
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

from common import write_atomic, read_json

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 默认输出到 data/raw/（已加入 .gitignore，联播原文不入库）
DATA_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "raw"))


def fetch_url(url, retries=3, timeout=30, delay=2):
    """带重试与 gzip 处理的抓取；404 返回 None，其余异常抛给上层。"""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Accept-Encoding": "gzip",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"    [fetch] 404: {url}")
                return None
            if e.code in (403, 503) and attempt < retries:
                print(f"    [fetch] HTTP {e.code}, attempt {attempt}/{retries}, wait {delay*10}s...")
                time.sleep(delay * 10)
                last_err = e
                continue
            print(f"    [fetch] HTTP {e.code}: {url}")
            last_err = e
            break
        except Exception as e:
            print(f"    [fetch] {e}, attempt {attempt}/{retries}")
            last_err = e
            if attempt < retries:
                time.sleep(delay)
    if last_err:
        raise last_err
    return None


def strip_tags(html_text):
    # 块级标签先转成换行，保留段落结构
    html_text = re.sub(r"</p>|</div>|<br\s*/?>", "\n", html_text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", html_text)
    text = html_mod.unescape(text)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


# ---------------------------------------------------------------- CCTV 主源

def parse_cctv_day_page(raw):
    """从每日页 HTML 解析条目列表（{title, url, duration}）。独立成函数便于测试。"""
    items = []
    # 每个 <li> 内：第一个 <a> 是视频图，第二个 <a> 是标题链接；<span> 为时长。
    # 年份用 \d{4} 通配（不再写死 2026），跨年仍然可用。
    li_pattern = re.compile(r"<li>(.*?)</li>", re.DOTALL)
    for li in li_pattern.finditer(raw):
        block = li.group(1)
        link_m = re.search(
            r'<a href="(https://tv\.cctv\.com/\d{4}[^"]+?\.shtml)"[^>]*?title="([^"]+)"',
            block,
        )
        if not link_m:
            continue
        url_i, title = link_m.group(1), link_m.group(2)
        dur_m = re.search(r"<span>(\d{2}:\d{2}:\d{2})</span>", block)
        duration = dur_m.group(1) if dur_m else ""
        # 跳过整期完整版视频
        if "《新闻联播》" in title and re.search(r"\d{8}", title):
            continue
        # 去掉 [视频] 前缀
        title = re.sub(r"^\[视频\]", "", title).strip()
        if title:
            items.append({"title": title, "url": url_i, "duration": duration})
    return items


def cctv_day_page(date_str):
    """返回 (items, raw_html)。items 每项 {title, url, duration}。"""
    compact = date_str.replace("-", "")
    url = f"https://tv.cctv.com/lm/xwlb/day/{compact}.shtml"
    print(f"[CCTV] 每日页: {url}")
    raw = fetch_url(url)
    if not raw:
        return [], raw
    return parse_cctv_day_page(raw), raw


def cctv_item_text(url):
    """抓取单条新闻页，提取 #content_area 正文。"""
    raw = fetch_url(url)
    if not raw:
        return ""
    m = re.search(
        r'<div class="content_area" id="content_area">(.*?)</div>\s*<div class="zebian"',
        raw,
        re.DOTALL,
    )
    if not m:
        m = re.search(
            r'<div class="content_area" id="content_area">(.*?)</div>', raw, re.DOTALL
        )
    if not m:
        return ""
    text = strip_tags(m.group(1))
    # 去掉开头的“央视网消息（新闻联播）：”
    text = re.sub(r"^央视网消息\s*（新闻联播）\s*：", "", text)
    return text


def fetch_cctv(date_str):
    items, _ = cctv_day_page(date_str)
    if not items:
        print("[CCTV] 每日页无有效条目，判定不可用")
        return None
    print(f"[CCTV] 解析到 {len(items)} 条新闻，开始抓取正文...")
    for i, it in enumerate(items, 1):
        print(f"    [{i}/{len(items)}] {it['title'][:30]}...")
        it["text"] = cctv_item_text(it["url"])
        if not it["text"]:
            print(f"    [WARN] 正文为空: {it['title']}")
        time.sleep(0.5)  # 礼貌限速
    return {
        "source": "cctv",
        "source_name": "CCTV央视网（tv.cctv.com）",
        "items": items,
    }


# ---------------------------------------------------------------- mrxwlb 备份

def mrxwlb_url(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    title = f"{d.year}年{d.month}月{d.day}日新闻联播文字版"
    # 优先 HTTPS；旧版 http:// 仅作回退
    return f"https://mrxwlb.com/{d.year}/{d.month:02d}/{d.day:02d}/{urllib.parse.quote(title)}/"


def parse_mrxwlb(raw):
    """从 mrxwlb 文章页 HTML 解析条目列表。独立成函数便于测试。"""
    # 定位 entry-content
    i = raw.find('class="entry-content"')
    if i < 0:
        print("[MRXWLB] 未找到 entry-content")
        return []
    content = raw[i:]
    end = content.find("<!-- .entry-content -->")
    if end < 0:
        end = content.find("</div>", content.find("</div>") + 1)
    content = content[:end] if end > 0 else content

    # 标题列表（主要内容 <ul><li>）
    titles = []
    for li in re.finditer(r"<li>(.*?)</li>", content, re.DOTALL):
        t = strip_tags(li.group(1))
        if t and "新闻联播主要内容" not in t:
            titles.append(t)

    # 正文：<p><strong>标题</strong></p> 只有当命中主要内容标题时才开新条目；
    # 其余 <strong>（快讯子条目等）作为子标题并入当前条目正文。
    items = []
    cur = None
    for p in re.finditer(r"<p>(.*?)</p>", content, re.DOTALL):
        block = p.group(1)
        strong = re.match(r"<strong>(.*?)</strong>", block, re.DOTALL)
        if strong:
            heading = strip_tags(strong.group(1))
            if not heading or "新闻联播主要内容" in heading or "文字版全文" in heading:
                continue
            if heading in titles:
                cur = {"title": heading, "text": ""}
                items.append(cur)
            elif cur is not None:
                cur["text"] += ("\n" if cur["text"] else "") + heading
            continue
        text = strip_tags(block)
        if text and cur is not None:
            cur["text"] += ("\n" if cur["text"] else "") + text
    if not items and titles:
        # 退化：至少保留标题列表（正文质量校验会拦截全空结果）
        items = [{"title": t, "text": ""} for t in titles]
    return items


def fetch_mrxwlb(date_str):
    url = mrxwlb_url(date_str)
    print(f"[MRXWLB] 备份源: {url}")
    raw = None
    try:
        raw = fetch_url(url)
    except Exception as e:
        print(f"[MRXWLB] HTTPS 抓取失败: {e}")
    if raw is None and url.startswith("https://"):
        http_url = url.replace("https://", "http://", 1)
        print(f"[MRXWLB] 回退 HTTP: {http_url}")
        try:
            raw = fetch_url(http_url)
        except Exception as e:
            print(f"[MRXWLB] HTTP 抓取失败: {e}")
    if not raw:
        return None
    items = parse_mrxwlb(raw)
    if not items:
        return None
    return {
        "source": "mrxwlb",
        "source_name": "mrxwlb.com 文字版镜像",
        "items": items,
    }


# ---------------------------------------------------------------- 输出

def render_markdown(result, date_str):
    lines = [f"{date_str.replace('-', '')}今日新闻联播主要内容："]
    for i, it in enumerate(result["items"], 1):
        lines.append(f"第{i}条：{it['title']}")
    lines.append("")
    lines.append("以下为详细的文字版全文：")
    for i, it in enumerate(result["items"], 1):
        lines.append("")
        lines.append(f"第{i}条：{it['title']}")
        if it.get("text"):
            lines.append(it["text"])
    lines.append("")
    lines.append("---")
    lines.append(f"*数据源：{result['source_name']}（主源：CCTV央视网；备份：mrxwlb.com）*")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="获取新闻联播全文")
    ap.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD，默认今天")
    ap.add_argument("--outdir", default=DATA_DIR, help="输出目录，默认 data/raw（已 gitignore）")
    ap.add_argument("--force", action="store_true", help="即使本地已有缓存也重新抓取")
    ap.add_argument("--source", choices=["cctv", "mrxwlb", "auto"], default="auto",
                    help="强制指定数据源（auto=主源失败自动降级）")
    args = ap.parse_args()

    date_str = args.date
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        try:
            date_str = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            sys.exit("日期格式错误，请使用 YYYY-MM-DD 或 YYYYMMDD")

    compact = date_str.replace("-", "")
    md_path = os.path.join(args.outdir, f"xwlb_{compact}_text.md")
    json_path = os.path.join(args.outdir, f"xwlb_{compact}_full.json")

    # 缓存一致性（次要 6）：JSON 在而 MD 缺失时补写 MD，避免与 run_daily 死锁
    if not args.force and os.path.exists(json_path):
        try:
            existing = read_json(json_path)
        except Exception as e:
            print(f"本地缓存损坏（{e}），忽略缓存重新抓取")
            existing = None
        if existing and existing.get("items"):
            if not os.path.exists(md_path):
                print("检测到 JSON 缓存但缺少 MD（上次运行中断），补写 MD")
                write_atomic(md_path, render_markdown(existing, date_str))
            print(f"本地已有 {date_str} 数据（来源：{existing.get('source_name')}），跳过抓取（--force 可强制）")
            return

    result = None
    if args.source in ("cctv", "auto"):
        # 主源：CCTV
        try:
            result = fetch_cctv(date_str)
        except Exception as e:
            print(f"[CCTV] 抓取失败: {e}")
        # 校验主源质量
        if result:
            ok = sum(1 for it in result["items"] if it.get("text"))
            if ok < max(3, len(result["items"]) // 2):
                print(f"[CCTV] 正文完整率过低（{ok}/{len(result['items'])}），改用备份源")
                result = None

    if not result and args.source in ("mrxwlb", "auto"):
        # 备份源：mrxwlb
        print("[MRXWLB] 尝试备份源...")
        try:
            result = fetch_mrxwlb(date_str)
        except Exception as e:
            print(f"[MRXWLB] 抓取失败: {e}")
        # 校验备份源质量（次要 2）：正文全部为空 = 解析退化，判定不可用
        if result:
            ok = sum(1 for it in result["items"] if it.get("text"))
            if ok == 0:
                print("[MRXWLB] 正文全部为空（仅剩标题列表），判定不可用")
                result = None

    if not result or not result["items"]:
        sys.exit("两个数据源均失败，未获取到任何数据")

    result["date"] = date_str
    result["fetched_at"] = datetime.now().isoformat(timespec="seconds")

    os.makedirs(args.outdir, exist_ok=True)
    write_atomic(json_path, json.dumps(result, ensure_ascii=False, indent=2))
    write_atomic(md_path, render_markdown(result, date_str))

    print(f"\n完成：来源={result['source_name']}，条目={len(result['items'])}")
    print(f"  JSON: {json_path}")
    print(f"  MD  : {md_path}")


if __name__ == "__main__":
    main()
