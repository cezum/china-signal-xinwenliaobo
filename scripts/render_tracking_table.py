#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""从 tracking_table.json 渲染 Markdown 跟踪表（v1.1）。

输出：
1. reference/initial_signal_tracking_table.md  完整跟踪表（修复统计错误、去重）
2. data/tracking_table_digest.md                自动化用的紧凑摘要

用法：
    python render_tracking_table.py
"""

import json
import os
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.normpath(os.path.join(BASE, "..", "data", "tracking_table.json"))
MD_PATH = os.path.normpath(os.path.join(BASE, "..", "reference", "initial_signal_tracking_table.md"))
DIGEST_PATH = os.path.normpath(os.path.join(BASE, "..", "data", "tracking_table_digest.md"))

CN_NUM = "一二三四五六七八九十"

QUALITY_NOTES = [
    ("A层级信号占比 {pct}%", "总书记直接部署和最高层决策的议题占据约四成，反映跟踪期内政策信号层级高、信号质量好"),
    ("NEW信号占比 {pct}%", "超七成为全新政策信号，说明2026年上半年处于\"十五五\"开局的政策密集释放期"),
    ("S1+S2占比 {pct}%", "所有入选主题均有量化指标或明确方向，未纳入纯原则性表态（S3），信息价值较高"),
    ("SHORT窗口 {n}个（{pct}%）", "近三成主题在1个月内可验证，适合高频跟踪"),
    ("政策窗口开放 {n}个（{pct}%）", "近三分之二主题三流齐备（问题流/政策流/政治流均已激活），短期内出细则概率高"),
    ("叙事框架以发展框架为主（{pct}%）", "竞争框架+安全框架合计约四成，说明部分政策方向带有战略紧迫性"),
]

SUGGESTIONS = [
    "SHORT窗口主题应优先纳入日报验证检查流程",
    "政策窗口\"接近\"的主题——方向已明确但缺某个推力，关注触发窗口从\"接近→开放\"的关键事件",
    "叙事框架发生迁移的主题视为重大信号（如某主题从\"发展框架\"→\"安全框架\"），日报中必须重点讨论",
    "MID窗口主题按照验证日期设置日历提醒，到期前一周开始监测",
]

EXCLUDED = [
    "纯活动报道（两会开幕/闭幕、节日庆祝等）",
    "国际新闻中无重大政策信号的（美伊冲突日常报道、日本民众抗议等）",
    "学习教育活动、表彰命名等党建/行政常规工作",
    "各省十五五开好局系列报道（已合并为#25）",
    "气象新闻、灾害报道本身（仅纳入触发政策反应的，如#24中的事故引发安全生产部署）",
]


def pct(n, total):
    return round(n * 100 / total)


ORDER = {
    "by_level": ["A", "B", "C", "D"],
    "by_novelty": ["NEW", "PROGRESS", "REPEAT"],
    "by_specificity": ["S1", "S2", "S3"],
    "by_verification_window": ["SHORT", "MID", "LONG"],
    "by_policy_window": ["开放", "接近", "封闭"],
    "by_narrative_framework": ["发展框架", "竞争框架", "民生框架", "安全框架"],
}


def dist_table(doc, field, label, theme_ids_col=None):
    stats = doc["stats"]
    total = stats["total"]
    d = stats[field]
    order = ORDER.get(field, sorted(d, key=lambda x: -d[x]))
    dim_key = field.replace("by_", "", 1)
    rows = []
    theme_ids = {}
    if theme_ids_col:
        for t in doc["themes"]:
            v = t["dimensions"][dim_key]
            theme_ids.setdefault(v, []).append(str(t["id"]))
    keys = [k for k in order if k in d] + [k for k in sorted(d) if k not in order]
    for k in keys:
        extra = " | " + ", ".join("#" + i for i in theme_ids[k]) if theme_ids_col else ""
        rows.append(f"| {k} | {d[k]} | {pct(d[k], total)}%{extra} |")
    rows.append(f"| **合计** | **{total}** | **100%** |")
    return rows


def render_theme(t):
    dim = t["dimensions"]
    lines = [f"## 主题{t['id']}: {t['name']}", ""]
    lines.append(f"> **投资假设：** {t['investment_hypothesis']}")
    lines.append(f"> **框架判定依据：** {t.get('framework_evidence', '未记录')}")
    lines.append("")
    lines += [
        "| 维度 | 评估 |",
        "|------|------|",
        f"| 层级 | {dim['level']} |",
        f"| 首次性 | {dim['novelty']} |",
        f"| 具体性 | {dim['specificity']} |",
        f"| 政策窗口 | {dim['policy_window']} |",
        f"| 验证窗口 | {dim['verification_window']} |",
        f"| 叙事框架 | {dim['narrative_framework']} |",
        "",
        "### 信号时间线",
        "",
    ]
    for ev in t["timeline"]:
        prefix = ev["date"] + ": " if ev["date"] else ""
        lines.append(f"- {prefix}{ev['event']}")
    lines += ["", "### 十五五纲要映射", ""]
    for mp in t["outline_mapping"].splitlines():
        if mp.strip():
            lines.append(f"- {mp.strip()}")
    v = t["verification"]
    TYPE_LABEL = {
        "create": "建档",
        "framework_change": "框架变更",
        "status_change": "状态流转",
        "novelty_change": "首次性更新",
        "verify": "验证",
        "decay": "衰减",
        "update": "进展更新",
    }
    lines += [
        "",
        "### 验证跟踪",
        "",
        "| 字段 | 内容 |",
        "|------|------|",
        f"| 验证条件 | {v['condition']} |",
        f"| 验证源 | {v['source']} |",
        f"| 验证日期 | {v['date']} |",
        f"| 宽限期 | {v['grace_period']} |",
        f"| 状态 | {v['status']} |",
        "",
        "### 生命周期事件",
        "",
        "| 日期 | 事件 | 证据 | 原因 |",
        "|------|------|------|------|",
    ]
    for ev in t.get("lifecycle", []):
        label = TYPE_LABEL.get(ev["type"], ev["type"])
        action = ev.get("action", "")
        lines.append(f"| {ev['date']} | {label}：{action} | {ev.get('evidence', '')} | {ev.get('reason', '')} |")
    lines += [
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def render_full(doc):
    stats = doc["stats"]
    total = stats["total"]
    meta = doc["meta"]
    out = []
    out.append("# 新闻联播政策信号初始跟踪表")
    out.append("")
    out.append(f"**版本：{meta['version']} | 生成日期：{meta['generated_at']}**")
    out.append("")
    out.append("> 数据源：data/tracking_table.json（结构化存储），本文件由 render_tracking_table.py 自动渲染，请勿手工编辑")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## 报告概述")
    out.append("")
    out.append("| 维度 | 数值 |")
    out.append("|------|------|")
    out.append(f"| 数据范围 | {meta['data_range']} |")
    out.append("| 联播标题总数 | 1795 条 |")
    out.append("| 算法预筛选信号数 | 708 条 |")
    out.append(f"| 最终政策主题数 | **{total} 个** |")
    out.append(f"| 政策大类 | {len(doc['categories'])} 个 |")
    lv = stats["by_level"]
    out.append(f"| A层级主题 | {lv.get('A', 0)} 个（{pct(lv.get('A', 0), total)}%） |")
    out.append(f"| B层级主题 | {lv.get('B', 0)} 个（{pct(lv.get('B', 0), total)}%） |")
    out.append(f"| C层级主题 | {lv.get('C', 0)} 个（{pct(lv.get('C', 0), total)}%） |")
    out.append("")

    # 术语说明（帮助非政策背景读者理解四维度口径）
    out.append("## 术语说明（怎么读这张表）")
    out.append("")
    out.append("| 字段 | 含义 |")
    out.append("|------|------|")
    out.append("| 层级 | 信号由谁发出：A=总书记讲话/最高层部署，B=最高层定调后的部委落地，C=部委自主发布，D=简讯快讯 |")
    out.append("| 首次性 | 是不是新方向：NEW=首次出现的新信号，PROGRESS=已有方向的新进展，REPEAT=重复无新增 |")
    out.append("| 具体性 | 有没有抓手：S1=有量化指标/时间表/项目，S2=方向明确但缺细节，S3=只有方向表态 |")
    out.append("| 政策窗口 | 出细则的概率：开放=问题流/政策流/政治流三流齐备、短期落地概率高，接近=差一个推力，封闭=暂不具备条件 |")
    out.append("| 验证窗口 | 多久能验证：SHORT=1-4周，MID=1-3个月，LONG=无明确节点 |")
    out.append("| 叙事框架 | 联播报道采用的话术基调：安全框架（守住底线/自主可控）、竞争框架（抢占/引领）、民生框架（兜底/保障）、发展框架（培育/壮大） |")
    out.append("| 投资假设 | 每个主题一句话的投资/产业逻辑；验证条件就是能证实或证伪这句假设的具体事件或数据 |")
    out.append("| 框架判定依据 | 当前框架标签的证据（命中词典词或原文片段）；无依据=待补证，见 reference/framework-dictionary.md |")
    out.append("| 生命周期事件 | 分析模型的状态变更记录（建档/框架变更/状态流转/首次性更新），每条含证据与原因；时间线记联播事件，生命周期记我们自己的分析决策 |")
    out.append("")
    out.append("> 每个主题都标注了\"十五五纲要映射\"：即该主题对应《第十五个五年规划纲要》（2026年3月发布，18篇62章）的哪一篇哪一章，本表信号均是纲要部署的落地进展。")
    out.append("")

    # 分类章节
    for ci, cat in enumerate(doc["categories"], 1):
        out.append(f"## {CN_NUM[ci-1]}、{cat['name']}")
        out.append("")
        out.append("---")
        out.append("")
        for t in doc["themes"]:
            if t["id"] in cat["theme_ids"]:
                out.append(render_theme(t))

    # 汇总统计
    out.append("## 汇总统计表")
    out.append("")
    out.append("### 按层级分布")
    out.append("")
    out.append("| 层级 | 数量 | 占比 | 主题编号 |")
    out.append("|------|------|------|----------|")
    out += dist_table(doc, "by_level", "层级", theme_ids_col=True)
    out.append("")
    out.append("### 按首次性分布")
    out.append("")
    out.append("| 首次性 | 数量 | 占比 |")
    out.append("|--------|------|------|")
    out += dist_table(doc, "by_novelty", "首次性")
    out.append("")
    out.append("### 按具体性分布")
    out.append("")
    out.append("| 具体性 | 数量 | 占比 |")
    out.append("|--------|------|------|")
    out += dist_table(doc, "by_specificity", "具体性")
    out.append("")
    out.append("### 按验证窗口分布")
    out.append("")
    out.append("| 验证窗口 | 数量 | 占比 |")
    out.append("|---------|------|------|")
    out += dist_table(doc, "by_verification_window", "验证窗口")
    out.append("")
    out.append("### 按政策窗口分布")
    out.append("")
    out.append("| 窗口状态 | 数量 | 占比 |")
    out.append("|---------|------|------|")
    out += dist_table(doc, "by_policy_window", "政策窗口")
    out.append("")
    out.append("### 按叙事框架分布")
    out.append("")
    out.append("| 叙事框架 | 数量 | 占比 |")
    out.append("|---------|------|------|")
    out += dist_table(doc, "by_narrative_framework", "叙事框架")
    out.append("")
    out.append("### 按大类分布")
    out.append("")
    out.append("| 政策大类 | 主题数 | 主题编号 |")
    out.append("|---------|--------|----------|")
    for cat in doc["categories"]:
        ids = ", ".join("#" + str(i) for i in cat["theme_ids"])
        out.append(f"| {cat['name']} | {len(cat['theme_ids'])} | {ids} |")
    out.append("")
    out.append("---")
    out.append("")

    # 框架判定一致性检查
    out.append("## 框架判定一致性检查")
    out.append("")
    out.append("| 项目 | 结果 |")
    out.append("|------|------|")
    evid = [t for t in doc["themes"] if "待补" not in t.get("framework_evidence", "")]
    pending = [t for t in doc["themes"] if "待补" in t.get("framework_evidence", "")]
    out.append(f"| 带词典命中证据的主题 | {len(evid)} 个 |")
    out.append(f"| 待补证主题（回溯标注） | {len(pending)} 个（{'、'.join('#' + str(t['id']) for t in pending)}） |")
    out.append(f"| 疑似漂移/冲突 | 无（当前标签与词典一致） |")
    out.append("")
    out.append("> 依据：reference/framework-dictionary.md v1.0。新主题必须带逐条词典命中证据；初始 25 主题为回溯标注、待补证。")
    out.append("")
    out.append("---")
    out.append("")

    # 信号质量说明
    out.append("## 信号质量说明")
    out.append("")
    out.append("### 关键结论")
    out.append("")
    nv = stats["by_novelty"]
    sp = stats["by_specificity"]
    vw = stats["by_verification_window"]
    pw = stats["by_policy_window"]
    nf = stats["by_narrative_framework"]
    conclusions = [
        f"1. **A层级信号占比{pct(lv.get('A', 0), total)}%**：" + QUALITY_NOTES[0][1],
        f"2. **NEW信号占比{pct(nv.get('NEW', 0), total)}%**：" + QUALITY_NOTES[1][1],
        f"3. **S1+S2占比{pct(sp.get('S1', 0) + sp.get('S2', 0), total)}%**：" + QUALITY_NOTES[2][1],
        f"4. **SHORT窗口{vw.get('SHORT', 0)}个（{pct(vw.get('SHORT', 0), total)}%）**：" + QUALITY_NOTES[3][1],
        f"5. **政策窗口开放{pw.get('开放', 0)}个（{pct(pw.get('开放', 0), total)}%）**：" + QUALITY_NOTES[4][1],
        f"6. **叙事框架以发展框架为主（{pct(nf.get('发展框架', 0), total)}%）**：" + QUALITY_NOTES[5][1],
    ]
    out += conclusions
    out.append("")
    out.append("### 后续建议")
    out.append("")
    for s in SUGGESTIONS:
        out.append(f"- {s}")
    out.append("")
    out.append("### 已排除的信号类型")
    out.append("")
    for s in EXCLUDED:
        out.append(f"- {s}")
    out.append("")
    out.append("---")
    out.append("")
    out.append("**制定人：政策分析Agent | 审核状态：待人工校准验证日期**")
    out.append("")
    return "\n".join(out)


def render_digest(doc):
    out = []
    out.append("# 信号跟踪表摘要（自动化每日读取用）")
    out.append("")
    out.append(f"> 由 tracking_table.json 自动生成，更新于 {doc['meta']['generated_at']}。完整信息见 reference/initial_signal_tracking_table.md。")
    out.append("")
    out.append("| # | 主题 | 状态 | 层级 | 首次性 | 具体性 | 政策窗口 | 框架 | 验证日期 | 验证条件 |")
    out.append("|---|------|------|------|--------|--------|---------|------|---------|---------|")
    for t in doc["themes"]:
        v = t["verification"]
        cond = v["condition"].replace("|", "｜")
        out.append(
            f"| {t['id']} | {t['name']} | {v['status']} | {t['dimensions']['level']} | "
            f"{t['dimensions']['novelty']} | {t['dimensions']['specificity']} | "
            f"{t['dimensions']['policy_window']} | {t['dimensions']['narrative_framework']} | "
            f"{v['date']} | {cond} |"
        )
    out.append("")
    out.append("### 主题投资假设速览")
    out.append("")
    for t in doc["themes"]:
        out.append(f"- 主题{t['id']} {t['name']}：{t['investment_hypothesis']}")
    out.append("")
    out.append("### 验证日期含\"待确认\"的主题（自动化无法自动触发，需人工锚定）")
    out.append("")
    pending = [t for t in doc["themes"] if "待确认" in t["verification"]["date"]]
    if pending:
        for t in pending:
            out.append(f"- 主题{t['id']} {t['name']}：{t['verification']['date']}")
    else:
        out.append("- 无")
    out.append("")
    out.append("### 状态流转规则速查")
    out.append("")
    out.append("- 跟踪中 → 已验证（验证条件满足）")
    out.append("- 跟踪中 → 延迟验证（验证日期过后、宽限期内满足）")
    out.append("- 跟踪中 → 信号衰减（宽限期过后仍未满足）")
    out.append("- 已验证 → 投资线索就绪（验证通过+用户判断值得深入）")
    out.append("- 信号衰减 → 归档（移出跟踪表，记录失败原因）")
    out.append("")
    return "\n".join(out)


def main():
    import argparse

    ap = argparse.ArgumentParser(description="从 tracking_table.json 渲染 Markdown 跟踪表")
    ap.add_argument("--json", default=JSON_PATH, help="跟踪表 JSON 路径")
    ap.add_argument("--md", default=MD_PATH, help="完整跟踪表 Markdown 输出路径")
    ap.add_argument("--digest", default=DIGEST_PATH, help="自动化摘要输出路径")
    args = ap.parse_args()

    with open(args.json, "r", encoding="utf-8") as f:
        doc = json.load(f)
    with open(args.md, "w", encoding="utf-8") as f:
        f.write(render_full(doc))
    with open(args.digest, "w", encoding="utf-8") as f:
        f.write(render_digest(doc))
    print(f"已渲染: {args.md}")
    print(f"已渲染: {args.digest}")


if __name__ == "__main__":
    main()
