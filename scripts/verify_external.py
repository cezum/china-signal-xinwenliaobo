#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""外部查证：对到期未验证的主题，联网核实验证条件是否已满足（第二档）。

背景（2026-08-16 修订）：验证点分两类——联播型（看联播原文）与外部型
（如"商务部发布数据"）。外部型验证点的事实往往在联播之外发生，
"联播未报道"不等于"未发生"。本脚本在验证日期到期后自动联网查证，
避免单一信源造成的假阴性。

查证对象（按验证日期早者优先，每轮上限 --limit 个）：
- status == "待复核"（宽限期已过、联播无信号）
- verification.date 已到期且 status ∈ {跟踪中, 延迟验证}
- 3 天内已查证过（verification.last_verify_attempt）的跳过，--force 可忽略

查证方式（强证据优先）：
1. verification.external_url 且域名属于官方来源后缀 → 直接抓取该页正文；
2. 否则搜索引擎只作为“待复核”的辅助线索，不直接触发已验证/信号衰减。
   默认渠道顺序 bing,ddg（Bing 国内直连），可用环境变量
   VERIFY_SEARCH 覆盖，如 VERIFY_SEARCH="sogou" 或 "bing,ddg"。

结论判定（LLM）：verified → 已验证；not_verified → 信号衰减；
uncertain → 保持原状态。每次判定都追加 lifecycle 事件（含证据与出处）。

用法：
    python scripts/verify_external.py                 # 查证候选主题（上限5）
    python scripts/verify_external.py --limit 10      # 自定义上限
    python scripts/verify_external.py --only-review   # 只查"待复核"主题
    python scripts/verify_external.py --force         # 忽略3天重试抑制
    python scripts/verify_external.py --dry-run       # 只输出结论，不写数据

环境变量（与 run_daily 相同）：
    LLM_API_KEY 必填；LLM_BASE_URL / LLM_MODEL 可选
"""

import argparse
import os
import re
import urllib.parse
from datetime import datetime, timedelta

from common import read_json, write_json, recompute_stats
from fetch_xwlb import fetch_url, strip_tags
from run_daily import call_llm, env_or

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKING_JSON = os.path.join(ROOT, "data", "tracking_table.json")

MAX_SNIPPET_CHARS = 6000
CONCLUSIONS = {"verified", "not_verified", "uncertain"}
RETRY_WINDOW_DAYS = 3
OFFICIAL_HOST_SUFFIXES = (
    "gov.cn",
    "people.com.cn",
    "news.cn",
    "xinhuanet.com",
    "cctv.com",
)

JUDGE_SYSTEM = (
    "你是事实核查助手。请判断下面这条\"验证条件\"是否已经被所附资料证实。\n"
    "判定标准：\n"
    "- verified：资料明确显示验证条件中的事件已发生；\n"
    "- not_verified：资料明确显示该事件未发生或已被证伪；\n"
    "- uncertain：资料不足、无关或无法判断。\n"
    "只输出 JSON：{\"conclusion\": \"verified|not_verified|uncertain\", "
    "\"evidence\": \"一句话证据（含日期与出处）\", \"reason\": \"判断依据\"}"
)


# ---------------------------------------------------------------- 候选筛选

def candidates(doc, today, only_review=False, force=False):
    """返回到期待查证主题列表（按验证日期早者优先）。"""
    try:
        today_d = datetime.strptime(today, "%Y-%m-%d").date()
    except ValueError:
        today_d = None
    out = []
    for t in doc["themes"]:
        v = t.get("verification") or {}
        status = v.get("status")
        # 联播型验证点（检验条件为"联播报道XX"）只由每日联播文本检查，
        # 不参与外部联网查证（外网检索"联播是否报道"语义错误）。
        if str(v.get("source") or "").strip() == "联播" and not str(v.get("external_url") or "").strip():
            continue
        if not force:
            last = str(v.get("last_verify_attempt") or "")
            m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})", last)
            if m and today_d:
                last_d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                if today_d - last_d < timedelta(days=RETRY_WINDOW_DAYS):
                    continue  # 3 天内已查证过，不重复烧调用
        if status == "待复核":
            out.append(t)
            continue
        if only_review or status not in ("跟踪中", "延迟验证"):
            continue
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})", str(v.get("date") or "").strip())
        if m and today_d:
            due = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            if due <= today_d:
                out.append(t)
    out.sort(key=lambda t: str((t.get("verification") or {}).get("date") or "9999-12-31"))
    return out


# ---------------------------------------------------------------- 资料获取

def bing_search(query):
    """Bing（cn.bing.com）检索，返回摘要文本（失败返回空串）。"""
    url = ("https://cn.bing.com/search?q=" + urllib.parse.quote(query)
           + "&setlang=zh-CN")
    raw = fetch_url(url)
    if not raw:
        return ""
    lines = []
    for m in re.finditer(
            r'<li class="b_algo".*?<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a></h2>'
            r'(.*?)</li>',
            raw, re.S):
        href, title = m.group(1), strip_tags(m.group(2))
        snippet = strip_tags(m.group(3))
        if title:
            lines.append(f"- {title}\n  摘要：{snippet[:300]}\n  来源：{href}")
        if len(lines) >= 5:
            break
    return "\n".join(lines)


def ddg_search(query):
    """DuckDuckGo HTML 端点检索，返回摘要文本（失败返回空串）。"""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    raw = fetch_url(url)
    if not raw:
        return ""
    lines = []
    for m in re.finditer(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
            r'.*?<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            raw, re.S):
        href, title, snippet = m.group(1), strip_tags(m.group(2)), strip_tags(m.group(3))
        # DDG 跳转链接中提取真实地址
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        if "uddg" in qs:
            href = qs["uddg"][0]
        if title:
            lines.append(f"- {title}\n  摘要：{snippet}\n  来源：{href}")
        if len(lines) >= 5:
            break
    return "\n".join(lines)


def search_channels():
    """搜索渠道顺序：环境变量 VERIFY_SEARCH 覆盖，默认 bing,ddg。"""
    raw = env_or("VERIFY_SEARCH") or "bing,ddg"
    out = []
    for ch in raw.split(","):
        ch = ch.strip().lower()
        if ch in ("bing", "ddg") and ch not in out:
            out.append(ch)
    return out or ["bing"]


def search(query):
    """按渠道顺序检索，返回 (文本, 渠道名)；全部失败返回 ("", "")。

    渠道函数通过 globals() 动态解析（而非静态字典），便于测试 mock。
    """
    for ch in search_channels():
        func = globals().get(f"{ch}_search")
        if not callable(func):
            continue
        try:
            results = func(query)
            if results:
                return results, ch
        except Exception as e:
            print(f"    [search] {ch} 失败：{e}")
    return "", ""


def _is_official_url(url):
    """判断 URL 是否为可自动采信的官方来源域名。"""
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == suffix or host.endswith("." + suffix)
               for suffix in OFFICIAL_HOST_SUFFIXES)


def gather(theme, condition):
    """返回 (snippet, source_label, strong)。

    strong=True 表示资料来自官方 URL 且正文抓取成功，才允许后续
    LLM 判定直接落为“已验证/信号衰减”；搜索摘要等弱证据只供
    “待复核”阶段留痕，不直接改变终态。
    """
    v = theme.get("verification") or {}
    url = str(v.get("external_url") or "").strip()
    if url:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme in ("http", "https"):
            if not _is_official_url(url):
                print(f"    [gather] external_url 非官方来源，不作为自动终态证据：{url}")
                return "", f"非官方页面 {url}", False
            try:
                raw = fetch_url(url)
                if raw:
                    text = strip_tags(raw)
                    if text:
                        return text[:MAX_SNIPPET_CHARS], f"官方页面 {url}", True
            except Exception as e:
                print(f"    [gather] 官方 URL 抓取失败：{e}")
            print(f"    [gather] 官方 URL 未取得有效正文，转待复核：{url}")
            return "", f"官方页面抓取失败 {url}", False
        else:
            print(f"    [gather] external_url 协议非法（{parsed.scheme or '空'}），转待复核")
            return "", "", False
    query = f"{theme.get('name', '')} {condition}".strip()[:200]
    results, channel = search(query)
    if results:
        return results, f"联网检索[{channel}]（{query[:80]}）", False
    return "", "", False


# ---------------------------------------------------------------- 判定与流转

def judge(condition, snippet):
    """调 LLM 判断，返回 {"conclusion", "evidence", "reason"}。"""
    user = f"验证条件：{condition}\n\n资料：\n{snippet[:MAX_SNIPPET_CHARS]}"
    data = call_llm(JUDGE_SYSTEM, user)
    verdict = {"conclusion": "uncertain", "evidence": "", "reason": ""}
    if isinstance(data, dict):
        if data.get("conclusion") in CONCLUSIONS:
            verdict["conclusion"] = data["conclusion"]
        verdict["evidence"] = str(data.get("evidence") or "")
        verdict["reason"] = str(data.get("reason") or "")
    return verdict


def apply_verdict(doc, theme, verdict, today, source_label):
    """按结论流转状态并追加生命周期事件；返回 1=有状态变化。"""
    v = theme.setdefault("verification", {})
    old = v.get("status", "跟踪中")
    conclusion = verdict.get("conclusion", "uncertain")
    evidence = str(verdict.get("evidence") or "").strip()
    label = f"（查证源：{source_label}）" if source_label else ""
    v["last_verify_attempt"] = today

    if conclusion == "verified":
        v["status"] = "已验证"
        ev_type, action = "verify", f"外部查证：验证通过（{old} → 已验证）"
        changed = 1
    elif conclusion == "not_verified":
        v["status"] = "信号衰减"
        ev_type, action = "decay", f"外部查证：证伪（{old} → 信号衰减）"
        changed = 1
    else:
        ev_type, action = "update", f"外部查证：无法确认（保持{old}）"
        changed = 0
    theme.setdefault("lifecycle", []).append({
        "date": today,
        "type": ev_type,
        "action": action,
        "evidence": (evidence + label) if evidence else label,
        "reason": f"验证日期到期后的外部查证：{str(verdict.get('reason') or '—')}",
    })
    return changed


def apply_review_pending(doc, theme, today, reason, source_label):
    """弱证据/无证据时，不自动终态，只转到“待复核”并留痕。"""
    v = theme.setdefault("verification", {})
    old = v.get("status", "跟踪中")
    v["last_verify_attempt"] = today
    label = f"（查证源：{source_label}）" if source_label else ""

    if old in ("已验证", "信号衰减", "归档"):
        return 0
    if old == "待复核":
        ev_type, action, changed = "update", f"外部查证：仍待复核（{reason}）", 0
    else:
        v["status"] = "待复核"
        ev_type, action, changed = (
            "status_change",
            f"外部查证证据不足：{old} → 待复核",
            1,
        )

    theme.setdefault("lifecycle", []).append({
        "date": today,
        "type": ev_type,
        "action": action,
        "evidence": label,
        "reason": reason,
    })
    return changed


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="到期主题外部查证")
    ap.add_argument("--json", default=TRACKING_JSON, help="跟踪表 JSON 路径")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                    help="今天 YYYY-MM-DD（默认系统日期）")
    ap.add_argument("--limit", type=int, default=5, help="每轮最多查证主题数（默认5）")
    ap.add_argument("--only-review", action="store_true", help="只查'待复核'主题")
    ap.add_argument("--force", action="store_true", help="忽略3天重试抑制")
    ap.add_argument("--dry-run", action="store_true", help="只输出结论，不写数据")
    args = ap.parse_args()

    doc = read_json(args.json)
    cands = candidates(doc, args.date, only_review=args.only_review, force=args.force)
    if not cands:
        print("无到期待查证主题")
        return
    print(f"候选主题 {len(cands)} 个，本轮查证前 {min(args.limit, len(cands))} 个")

    changed = 0
    for theme in cands[:args.limit]:
        v = theme.get("verification") or {}
        condition = str(v.get("condition") or "").strip()
        print(f"\n[verify] 主题{theme['id']} {theme.get('name', '')}")
        print(f"        条件：{condition[:80]}")
        snippet, source, strong = gather(theme, condition)
        if not snippet:
            changed += apply_review_pending(
                doc, theme, args.date, "未获取到可自动采信的外部资料", source)
            print("        未获取到强证据，已转待复核")
            continue
        if not strong:
            changed += apply_review_pending(
                doc, theme, args.date, "仅有搜索摘要/非官方来源，不足以自动终态", source)
            print("        证据不足，仅转待复核，不自动改终态")
            continue
        try:
            verdict = judge(condition, snippet)
        except SystemExit as e:
            print(f"        LLM 调用失败，跳过：{e}")
            continue
        except Exception as e:
            print(f"        判断失败，跳过：{type(e).__name__}: {e}")
            continue
        print(f"        结论：{verdict['conclusion']} | {verdict['evidence'][:90]}")
        changed += apply_verdict(doc, theme, verdict, args.date, source)

    if changed and not args.dry_run:
        recompute_stats(doc)
        write_json(args.json, doc, backup=True)
        print(f"\n已更新 {changed} 个主题的状态（原子写入 + .bak）")
    elif args.dry_run:
        print("\n（--dry-run：未写回数据）")


if __name__ == "__main__":
    main()
