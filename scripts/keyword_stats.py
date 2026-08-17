#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""回测词频统计（零 LLM、纯本地计数、零依赖）。

扫描本地语料目录中的 xwlb_YYYYMMDD_full.json，按关键词表做子串计数，输出：
    1) 月度计数 CSV  : case, group, keyword, month, days_mentioned, occurrences
    2) 首现日期表 CSV: case, group, keyword, first_date, last_date, days_mentioned, occurrences
    3) 缺口清单 JSON : 范围内缺失或损坏的日期

只读语料、只写统计数字——转录原文仍只留在 data/raw（gitignore），
统计输出默认到 data/backtest_stats/（纯统计，可入库公开）。

用法：
    python keyword_stats.py --start 2021-01-01 --end 2025-12-31
    python keyword_stats.py --start 2021-01-01 --end 2025-12-31 --dir data/raw
    python keyword_stats.py --keywords docs/backtest/keywords.json   # 不限定范围：扫描目录全部语料

注意：
- 计数为纯子串匹配（中文多字词假阳性低），不含上下文消歧；第一轮数据出来后人工抽查，
  噪音过大的词从 docs/backtest/keywords.json 里调换即可，重跑零成本。
- --start/--end 之外的语料文件不会参与统计，但也不会报错。
"""

import argparse
import csv
import json
import os
import re
from datetime import date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "raw"))
DEFAULT_KEYWORDS = os.path.normpath(os.path.join(BASE_DIR, "..", "docs", "backtest", "keywords.json"))
DEFAULT_OUT = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "backtest_stats"))

FILE_PATTERN = re.compile(r"^xwlb_(\d{8})_full\.json$")


def load_keywords(path):
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    cases = doc.get("cases")
    if not cases:
        raise SystemExit(f"关键词表为空：{path}")
    return cases


def list_corpus(data_dir, start=None, end=None):
    """返回 [(date_str, path)]，按日期升序；缺参数时包含目录内全部语料。"""
    lo = date.fromisoformat(start) if start else None
    hi = date.fromisoformat(end) if end else None
    if not os.path.isdir(data_dir):
        raise SystemExit(f"语料目录不存在：{data_dir}（请先运行 backfill_xwlb.py）")
    found = []
    for name in sorted(os.listdir(data_dir)):
        m = FILE_PATTERN.match(name)
        if not m:
            continue
        d = date(int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:8]))
        if lo and d < lo:
            continue
        if hi and d > hi:
            continue
        found.append((d.isoformat(), os.path.join(data_dir, name)))
    return found


def day_counts(path, cases):
    """返回 {date_str: {(case, group, kw): (days_mentioned, occurrences)}}，坏文件抛异常。"""
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    items = doc.get("items") or []
    haystacks = []
    for it in items:
        haystacks.append(" ".join(str(x) for x in [it.get("title", ""), it.get("text", "")]))
    result = {}
    for case, cfg in cases.items():
        for group in ("old", "new"):
            for kw in cfg.get(group, []):
                occ = sum(h.count(kw) for h in haystacks)
                result[(case, group, kw)] = (1 if occ else 0, occ)
    return result


def main():
    ap = argparse.ArgumentParser(description="回测词频统计")
    ap.add_argument("--dir", default=DEFAULT_DIR, help="语料目录，默认 data/raw")
    ap.add_argument("--keywords", default=DEFAULT_KEYWORDS, help="关键词表 JSON 路径")
    ap.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD（可选）")
    ap.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD（可选）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="统计输出目录，默认 data/backtest_stats")
    args = ap.parse_args()

    cases = load_keywords(args.keywords)
    corpus = list_corpus(args.dir, args.start, args.end)
    if not corpus:
        raise SystemExit(f"语料目录无匹配文件：{args.dir}（请先运行 backfill_xwlb.py）")

    # 汇总：monthly[(case, group, kw, month)] = [days, occ]；first[(case, group, kw)] = {...}
    monthly = {}
    first = {}
    valid_dates = set()
    corrupt = []

    for d_str, path in corpus:
        try:
            counts = day_counts(path, cases)
        except Exception as e:
            corrupt.append({"date": d_str, "error": str(e)[:120]})
            print(f"[WARN] {d_str} 损坏，跳过：{e}")
            continue
        valid_dates.add(d_str)
        month = d_str[:7]
        for key, (days, occ) in counts.items():
            case, group, kw = key
            mkey = (case, group, kw, month)
            m = monthly.setdefault(mkey, [0, 0])
            m[0] += days
            m[1] += occ
            if occ:
                f = first.setdefault((case, group, kw), {"first": d_str, "last": d_str, "days": 0, "occ": 0})
                f["last"] = d_str
                f["days"] += days
                f["occ"] += occ

    # 缺口：仅当用户给了范围才计算
    gaps = None
    if args.start and args.end:
        lo = date.fromisoformat(args.start)
        hi = date.fromisoformat(args.end)
        all_dates = set()
        cur = lo
        while cur <= hi:
            all_dates.add(cur.isoformat())
            cur = cur.fromordinal(cur.toordinal() + 1)
        gaps = {"missing": sorted(all_dates - valid_dates),
                "corrupt": corrupt}

    os.makedirs(args.out, exist_ok=True)

    # 月度 CSV
    monthly_path = os.path.join(args.out, "monthly_counts.csv")
    with open(monthly_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case", "group", "keyword", "month", "days_mentioned", "occurrences"])
        for key in sorted(monthly, key=lambda k: (k[0], 0 if k[1] == "old" else 1, k[2], k[3])):
            case, group, kw, month = key
            w.writerow([case, group, kw, month, monthly[key][0], monthly[key][1]])

    # 首现日期 CSV
    first_path = os.path.join(args.out, "first_occurrence.csv")
    with open(first_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case", "group", "keyword", "first_date", "last_date", "days_mentioned", "occurrences"])
        for key in sorted(first, key=lambda k: (k[0], 0 if k[1] == "old" else 1, k[2])):
            case, group, kw = key
            r = first[key]
            w.writerow([case, group, kw, r["first"], r["last"], r["days"], r["occ"]])

    if gaps is not None:
        gaps_path = os.path.join(args.out, "gaps.json")
        with open(gaps_path, "w", encoding="utf-8") as f:
            json.dump(gaps, f, ensure_ascii=False, indent=2)

    print(f"\n语料：{len(valid_dates)} 天有效，损坏 {len(corrupt)} 天" + (f"，缺失 {len(gaps['missing'])} 天" if gaps else ""))
    print(f"月度计数  : {monthly_path}")
    print(f"首现日期表: {first_path}")
    if gaps is not None:
        print(f"缺口清单  : {gaps_path}")
    print("\n==== 首现/末现速览 ====")
    for key in sorted(first, key=lambda k: (k[0], 0 if k[1] == "old" else 1, k[2])):
        case, group, kw = key
        r = first[key]
        label = cases[case].get("label", case)
        print(f"[{label}] {group}/{kw}: 首现 {r['first']}  末现 {r['last']}  （提及 {r['days']} 天 / {r['occ']} 次）")


if __name__ == "__main__":
    main()
