#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""批量回填《新闻联播》文字稿（回测语料建设）。

按日期范围逐日调用 fetch_xwlb.py 的 CLI（--date / --outdir / --force / --source），
复用其缓存：已存在且可解析的 JSON 直接跳过，可断点续传；失败日期记入缺口清单。
不 import fetch_xwlb 的内部函数，只依赖其文档化命令行接口。

用法：
    python backfill_xwlb.py --start 2021-01-01 --end 2025-12-31
    python backfill_xwlb.py --start 2021-01-01 --end 2025-12-31 --limit 5   # 冒烟测试
    python backfill_xwlb.py --start 2024-01-01 --end 2025-12-31             # 先跑近两年

设计：
- 默认从新到旧抓取（新页面结构与本仓库解析器最匹配；即使中断，也已先拿到近端数据）；
- 相邻两天之间礼貌停顿 --sleep 秒（默认 1.0，fetch_xwlb 内部另有每条目限速）；
- 缺口清单写 JSON（默认 <outdir>/backfill_gaps.json），失败日期重跑成功后自动清除；
- Ctrl+C 中断时先落盘缺口清单再退出，重跑本命令即可续传。
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FETCH_SCRIPT = os.path.join(BASE_DIR, "fetch_xwlb.py")
DEFAULT_OUTDIR = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "raw"))


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cache_ok(json_path):
    """缓存可用：文件存在、JSON 可解析、items 非空。"""
    if not os.path.exists(json_path):
        return False
    try:
        doc = read_json(json_path)
    except Exception:
        return False  # 损坏 → 交给 fetch_xwlb 重抓（它遇到损坏缓存会自动重抓）
    return bool(doc.get("items"))


def load_gap_log(path):
    if os.path.exists(path):
        try:
            doc = read_json(path)
            if isinstance(doc, dict):
                return doc
        except Exception:
            pass
    return {"failed": [], "updated_at": None}


def save_gap_log(path, doc):
    doc["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def remove_failed_entry(gaps, d_str):
    """某天重抓成功后，从缺口清单里清掉它的历史失败记录。"""
    gaps["failed"] = [e for e in gaps.get("failed", []) if e.get("date") != d_str]


def iter_dates(start, end, oldest_first=False):
    cur = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    step = 1 if oldest_first else -1
    cur = cur if oldest_first else stop
    final = stop if oldest_first else date.fromisoformat(start)
    while True:
        yield cur.isoformat()
        if cur == final:
            break
        cur += timedelta(days=step)


def main():
    ap = argparse.ArgumentParser(description="批量回填新闻联播文字稿（回测语料）")
    ap.add_argument("--start", required=True, help="起始日期 YYYY-MM-DD（含）")
    ap.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD（含）")
    ap.add_argument("--outdir", default=DEFAULT_OUTDIR, help="输出目录，默认 data/raw（已 gitignore）")
    ap.add_argument("--source", choices=["cctv", "mrxwlb", "auto"], default="auto",
                    help="数据源，默认 auto（主源失败自动降级）")
    ap.add_argument("--sleep", type=float, default=1.0, help="相邻两天之间停顿秒数，默认 1.0")
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少天（冒烟测试用），0=不限")
    ap.add_argument("--oldest-first", action="store_true", help="从旧到新；默认从新到旧")
    ap.add_argument("--gap-log", default=None, help="缺口清单路径，默认 <outdir>/backfill_gaps.json")
    args = ap.parse_args()

    try:
        d_start = date.fromisoformat(args.start)
        d_end = date.fromisoformat(args.end)
    except ValueError:
        sys.exit("日期格式错误，请使用 YYYY-MM-DD")
    if d_start > d_end:
        sys.exit("--start 不能晚于 --end")

    if not os.path.exists(FETCH_SCRIPT):
        sys.exit(f"未找到 fetch_xwlb.py：{FETCH_SCRIPT}")

    gap_path = args.gap_log or os.path.join(args.outdir, "backfill_gaps.json")
    os.makedirs(args.outdir, exist_ok=True)
    gaps = load_gap_log(gap_path)

    total = (d_end - d_start).days + 1
    fetched = skipped = failed = 0

    print(f"回填范围：{args.start} → {args.end}（共 {total} 天，方向：{'旧→新' if args.oldest_first else '新→旧'}）")
    print(f"输出目录：{args.outdir}")
    print(f"缺口清单：{gap_path}\n")

    try:
        for i, d_str in enumerate(iter_dates(args.start, args.end, args.oldest_first)):
            if args.limit and i >= args.limit:
                print(f"\n[达到 --limit {args.limit}] 停止")
                break
            compact = d_str.replace("-", "")
            json_path = os.path.join(args.outdir, f"xwlb_{compact}_full.json")

            if cache_ok(json_path):
                skipped += 1
                print(f"[{d_str}] 缓存已有，跳过（累计跳过 {skipped}）")
                continue

            force = []
            if os.path.exists(json_path):
                print(f"[{d_str}] 缓存损坏或条目为空，强制重抓")
                force = ["--force"]

            cmd = [sys.executable, FETCH_SCRIPT, "--date", d_str,
                   "--outdir", args.outdir, "--source", args.source] + force
            rc = subprocess.run(cmd).returncode
            if rc == 0 and cache_ok(json_path):
                fetched += 1
                remove_failed_entry(gaps, d_str)
                print(f"[{d_str}] 完成（累计抓取 {fetched}）")
            else:
                failed += 1
                gaps.setdefault("failed", []).append({"date": d_str, "exit": rc})
                print(f"[{d_str}] 失败（rc={rc}），已记入缺口清单")
            save_gap_log(gap_path, gaps)
            time.sleep(args.sleep)
    except KeyboardInterrupt:
        save_gap_log(gap_path, gaps)
        print("\n[中断] 缺口清单已保存，重跑本命令即可续传")
        sys.exit(130)

    save_gap_log(gap_path, gaps)
    print("\n==== 回填汇总 ====")
    print(f"范围内天数 : {total}")
    print(f"本次抓取   : {fetched}")
    print(f"复用缓存   : {skipped}")
    print(f"失败       : {failed}")
    print(f"缺口清单   : {gap_path}")


if __name__ == "__main__":
    main()
