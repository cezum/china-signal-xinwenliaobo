#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""从 keyword_stats.py 的输出生成零依赖 SVG 双线图。

输入：data/backtest_stats/monthly_counts.csv
输出：data/backtest_stats/charts/<case>.svg 与 index.html

每个案例画两条线：旧政策组 vs 新政策组。主图默认使用 days_mentioned
（某月至少有几天提到该组词），避免同一篇报道重复出现同一词导致峰值虚高。

用法：
    python scripts/backtest_charts.py
    python scripts/backtest_charts.py --stats data/backtest_stats --out data/backtest_stats/charts
"""

import argparse
import csv
import html
import json
import os
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STATS = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "backtest_stats"))
DEFAULT_KEYWORDS = os.path.normpath(os.path.join(BASE_DIR, "..", "docs", "backtest", "keywords.json"))
DEFAULT_OUT = os.path.normpath(os.path.join(DEFAULT_STATS, "charts"))

COLORS = {"old": "#d9534f", "new": "#2a9d8f"}
GROUP_LABELS = {"old": "旧政策组", "new": "新政策组"}


def load_labels(keywords_path):
    if not os.path.exists(keywords_path):
        return {}
    with open(keywords_path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    out = {}
    for key, cfg in doc.get("cases", {}).items():
        out[key] = cfg.get("label", key)
    return out


def load_monthly(stats_dir):
    path = os.path.join(stats_dir, "monthly_counts.csv")
    if not os.path.exists(path):
        raise SystemExit(f"未找到 {path}，请先运行 keyword_stats.py")
    series = defaultdict(lambda: defaultdict(float))
    months = set()
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            case, group, month = row["case"], row["group"], row["month"]
            value = float(row["days_mentioned"])
            series[(case, group)][month] += value
            months.add(month)
    return series, sorted(months)


def esc(text):
    return html.escape(str(text), quote=True)


def svg_for_case(case, label, series, months, width=960, height=420):
    left, right, top, bottom = 92, width - 36, 42, height - 74
    plot_w = right - left
    plot_h = bottom - top

    values = [series[(case, group)].get(m, 0.0) for m in months for group in ("old", "new")]
    max_value = max(values) if values else 1
    if max_value <= 0:
        max_value = 1

    def x_for(idx):
        if len(months) == 1:
            return left + plot_w / 2
        return left + plot_w * idx / (len(months) - 1)

    def y_for(v):
        return bottom - plot_h * (v / max_value)

    def polyline(group):
        points = []
        for idx, m in enumerate(months):
            points.append(f"{x_for(idx):.1f},{y_for(series[(case, group)].get(m, 0.0)):.1f}")
        return " ".join(points)

    parts = []
    parts.append(
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'xmlns="http://www.w3.org/2000/svg" role="img">'
    )
    parts.append(f"<title>{esc(label)}</title>")
    parts.append(
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>'
    )

    # 横向网格与 y 轴刻度
    for i in range(5):
        y = top + plot_h * i / 4
        val = max_value * (1 - i / 4)
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" '
            'stroke="#e5e5e5" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{left - 12}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-size="12" fill="#555">{val:.1f}</text>'
        )

    # x 轴标签：最多显示约 12 个，避免重叠
    step = max(1, len(months) // 12)
    for idx in range(0, len(months), step):
        x = x_for(idx)
        parts.append(
            f'<text x="{x:.1f}" y="{bottom + 22}" text-anchor="middle" '
            f'font-size="11" fill="#555">{esc(months[idx])}</text>'
        )

    parts.append(
        f'<text x="{left}" y="{top - 16}" font-size="16" font-weight="bold" fill="#222">{esc(label)}</text>'
    )
    parts.append(
        f'<text x="{right}" y="{top - 16}" text-anchor="end" font-size="12" fill="#777">'
        '纵轴：提及天数（关键词-天）</text>'
    )

    for group in ("old", "new"):
        color = COLORS[group]
        parts.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="2.5" '
            f'points="{polyline(group)}"/>'
        )
        # 数据点
        for idx, m in enumerate(months):
            y = y_for(series[(case, group)].get(m, 0.0))
            parts.append(
                f'<circle cx="{x_for(idx):.1f}" cy="{y:.1f}" r="2.4" fill="{color}"/>'
            )

    # 图例
    lx = left + 18
    for i, group in enumerate(("old", "new")):
        y = top + 20 + i * 20
        parts.append(f'<line x1="{lx}" y1="{y}" x2="{lx + 26}" y2="{y}" stroke="{COLORS[group]}" stroke-width="3"/>')
        parts.append(
            f'<text x="{lx + 34}" y="{y + 4}" font-size="12" fill="#333">'
            f'{esc(GROUP_LABELS[group])}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def build_index(cases, labels, outdir):
    items = []
    for case in cases:
        items.append(
            f'<section><h2>{esc(labels.get(case, case))}</h2>'
            f'<img src="{esc(case + ".svg")}" alt="{esc(labels.get(case, case))}"/></section>'
        )
    html = (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<title>回测词频图</title><style>body{font-family:sans-serif;margin:32px;max-width:1100px;}"
        "img{max-width:100%;height:auto;border:1px solid #eee;margin:12px 0;}</style></head>"
        f"<body><h1>回测词频图</h1>{''.join(items)}</body></html>"
    )
    with open(os.path.join(outdir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


def main():
    ap = argparse.ArgumentParser(description="生成回测词频 SVG 图")
    ap.add_argument("--stats", default=DEFAULT_STATS, help="统计目录（含 monthly_counts.csv）")
    ap.add_argument("--keywords", default=DEFAULT_KEYWORDS, help="关键词表 JSON 路径")
    ap.add_argument("--out", default=DEFAULT_OUT, help="SVG 输出目录")
    args = ap.parse_args()

    series, months = load_monthly(args.stats)
    labels = load_labels(args.keywords)
    cases = sorted({case for case, _ in series})
    if not cases:
        raise SystemExit("monthly_counts.csv 中没有数据")

    os.makedirs(args.out, exist_ok=True)
    for case in cases:
        svg = svg_for_case(case, labels.get(case, case), series, months)
        with open(os.path.join(args.out, f"{case}.svg"), "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"已生成: {os.path.join(args.out, case + '.svg')}")

    build_index(cases, labels, args.out)
    print(f"已生成: {os.path.join(args.out, 'index.html')}")


if __name__ == "__main__":
    main()
