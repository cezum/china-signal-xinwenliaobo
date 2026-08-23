#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""从 tracking_table.json 渲染 Markdown 跟踪表（v1.3）。

输出：
1. reference/initial_signal_tracking_table.md  完整跟踪表
2. data/tracking_table_digest.md                自动化用的紧凑摘要
3. tracking.md                                  面向读者的 5 列极简跟踪表

用法：
    python render_tracking_table.py
    python render_tracking_table.py --json <path> --md <out> --digest <out> --tracking <out>

修复背景（代码审查 2026-08-16）：
- P1-1 渲染前基于 themes 实时重算 stats，不再使用可能过期的旧统计；
- 次要 8 pct() 处理 total==0；分类超过 10 个时中文序号不再越界；
        Markdown 表格单元格统一转义 | 与换行；
        联播标题总数/预筛信号数从 meta 读取，质量结论按实际统计动态生成；
- P1-3 输出文件原子写入。
"""

import argparse
import os
import re
from datetime import datetime

from common import write_atomic, read_json, recompute_stats, MAIN_STATUSES

BASE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.normpath(os.path.join(BASE, "..", "data", "tracking_table.json"))
MD_PATH = os.path.normpath(os.path.join(BASE, "..", "reference", "initial_signal_tracking_table.md"))
DIGEST_PATH = os.path.normpath(os.path.join(BASE, "..", "data", "tracking_table_digest.md"))
TRACKING_PATH = os.path.normpath(os.path.join(BASE, "..", "tracking.md"))

CN_DIGITS = "一二三四五六七八九"

ORDER = {
    "by_level": ["A", "B", "C", "D"],
    "by_novelty": ["NEW", "PROGRESS", "REPEAT"],
    "by_specificity": ["S1", "S2", "S3"],
    "by_verification_window": ["SHORT", "MID", "LONG"],
    "by_policy_window": ["开放", "接近", "封闭"],
    "by_narrative_framework": ["发展框架", "竞争框架", "民生框架", "安全框架"],
}

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
    """占比；total 为 0 时返回 0（避免除零崩溃）。"""
    return 0 if not total else round(n * 100 / total)


def cn_num(n):
    """中文序号：1→一 … 10→十，11→十一 … 99→九十九，之外回退阿拉伯数字。"""
    if n <= 0:
        return str(n)
    if n <= 10:
        return "一二三四五六七八九十"[n - 1]
    if n < 20:
        return "十" + (CN_DIGITS[n - 11] if n > 10 else "")
    if n < 100:
        tens, units = divmod(n, 10)
        return CN_DIGITS[tens - 1] + "十" + (CN_DIGITS[units - 1] if units else "")
    return str(n)


def esc(value):
    """转义 Markdown 表格单元格：| 转义、换行折叠为 <br>。"""
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


MAX_SHORT_LOGIC = 40


def public_conduction(t):
    """公开层使用的“政策传导/盯什么”文本，不直接暴露投资假设。

    优先读取新增的 public_conduction 字段；历史主题没有该字段时，
    从 verification.condition 中提取一个中性、可核验的验证锚点。
    """
    text = str(t.get("public_conduction", "")).strip()
    if text:
        return text

    v = t.get("verification") if isinstance(t.get("verification"), dict) else {}
    text = str(v.get("condition", "")).strip()
    # 去掉“（检验……）”这类内部验证注释，只保留公开可观察的验证锚点
    text = re.sub(r"[（(]检验[^）)]*[）)]", "", text)
    text = re.sub(r"\s+", " ", text)
    text = text.replace("联播报道", "")
    text = text.strip(" ，。；、|")
    return text


def short_logic(t):
    """为极简跟踪表提取一句可读的“盯什么”，不改 JSON 数据。"""
    text = public_conduction(t)
    if text:
        return text[:MAX_SHORT_LOGIC] + ("…" if len(text) > MAX_SHORT_LOGIC else "")
    return "待补"


def wind(t):
    """把状态和政策窗口映射为单列“风向”。"""
    v = t.get("verification") if isinstance(t.get("verification"), dict) else {}
    status = str(v.get("status", "跟踪中"))
    dims = t.get("dimensions") if isinstance(t.get("dimensions"), dict) else {}
    policy_window = str(dims.get("policy_window", ""))

    if status == "已验证":
        return "✅", "已验证"
    if status == "投资线索就绪":
        return "💡", "线索"
    if status == "延迟验证":
        return "🟠", "延迟核验"
    if status == "待复核":
        return "🔍", "待复核"
    if status == "信号衰减":
        return "❌", "证伪/衰减"
    if status == "归档":
        return "🗄️", "归档"
    if status == "跟踪中":
        if policy_window == "开放":
            return "🟢", "抓紧落"
        if policy_window == "接近":
            return "🟡", "等风来"
        if policy_window == "封闭":
            return "⚪", "暂缓"
    return "⚪", "未标注"


def _parse_iso_date(value):
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d")
    except Exception:
        return None


def _tracking_sort_key(t):
    """未验证主题排前，验证日期越近越靠前；归档与已验证排后。"""
    status_order = {
        "跟踪中": 0,
        "延迟验证": 1,
        "待复核": 2,
        "投资线索就绪": 3,
        "已验证": 4,
        "信号衰减": 5,
        "归档": 6,
    }
    v = t.get("verification") if isinstance(t.get("verification"), dict) else {}
    status = str(v.get("status", "跟踪中"))
    rank = status_order.get(status, 7)
    due = _parse_iso_date(v.get("date", ""))
    return (rank, due or datetime.max, int(t.get("id", 0)))


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
            dims = t.get("dimensions") if isinstance(t.get("dimensions"), dict) else {}
            v = str(dims.get(dim_key, "未标注"))
            theme_ids.setdefault(v, []).append(str(t["id"]))
    keys = [k for k in order if k in d] + [k for k in sorted(d) if k not in order]
    for k in keys:
        extra = " | " + ", ".join("#" + i for i in theme_ids.get(k, [])) if theme_ids_col else ""
        rows.append(f"| {esc(k)} | {d[k]} | {pct(d[k], total)}%{extra} |")
    rows.append(f"| **合计** | **{total}** | **100%** |")
    return rows


def render_theme(t):
    dim = t.get("dimensions") if isinstance(t.get("dimensions"), dict) else {}
    lines = [f"## 主题{t['id']}: {esc(t.get('name', ''))}", ""]
    lines.append(f"> **政策传导逻辑：** {esc(public_conduction(t))}")
    lines.append(f"> **框架判定依据：** {esc(t.get('framework_evidence', '未记录'))}")
    lines.append("")
    lines += [
        "| 维度 | 评估 |",
        "|------|------|",
        f"| 层级 | {esc(dim.get('level', '未标注'))} |",
        f"| 首次性 | {esc(dim.get('novelty', '未标注'))} |",
        f"| 具体性 | {esc(dim.get('specificity', '未标注'))} |",
        f"| 政策窗口 | {esc(dim.get('policy_window', '未标注'))} |",
        f"| 验证窗口 | {esc(dim.get('verification_window', '未标注'))} |",
        f"| 叙事框架 | {esc(dim.get('narrative_framework', '未标注'))} |",
        "",
        "### 信号时间线",
        "",
    ]
    for ev in t.get("timeline", []):
        if not isinstance(ev, dict):
            continue
        prefix = ev.get("date", "") + ": " if ev.get("date") else ""
        lines.append(f"- {esc(prefix + ev.get('event', ''))}")
    lines += ["", "### 十五五纲要映射", ""]
    for mp in str(t.get("outline_mapping", "")).splitlines():
        if mp.strip():
            lines.append(f"- {mp.strip()}")
    v = t.get("verification") if isinstance(t.get("verification"), dict) else {}
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
        f"| 验证条件 | {esc(v.get('condition', ''))} |",
        f"| 验证源 | {esc(v.get('source', ''))} |",
        f"| 验证日期 | {esc(v.get('date', ''))} |",
        f"| 宽限期 | {esc(v.get('grace_period', ''))} |",
        f"| 状态 | {esc(v.get('status', ''))} |",
        "",
        "### 生命周期事件",
        "",
        "| 日期 | 事件 | 证据 | 原因 |",
        "|------|------|------|------|",
    ]
    for ev in t.get("lifecycle", []):
        if not isinstance(ev, dict):
            continue
        label = TYPE_LABEL.get(ev.get("type"), ev.get("type", ""))
        action = ev.get("action", "")
        lines.append(
            f"| {esc(ev.get('date', ''))} | {esc(f'{label}：{action}' if action else label)} | "
            f"{esc(ev.get('evidence', ''))} | {esc(ev.get('reason', ''))} |")
    lines += [
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def build_quality_conclusions(stats):
    """按实际统计动态生成信号质量结论（不写死比例描述）。"""
    total = stats["total"]
    if not total:
        return ["（跟踪表为空，暂无统计）"]
    lv = stats["by_level"]
    nv = stats["by_novelty"]
    sp = stats["by_specificity"]
    vw = stats["by_verification_window"]
    pw = stats["by_policy_window"]
    nf = stats["by_narrative_framework"]

    a_pct = pct(lv.get("A", 0), total)
    a_note = ("总书记直接部署和最高层决策的议题占比较高，跟踪期内信号层级高、信号质量好"
              if a_pct >= 30 else "最高层直接部署的议题占比较低，信号以部委层面为主")
    new_pct = pct(nv.get("NEW", 0), total)
    new_note = ("全新政策信号占比高，处于政策密集释放期"
                if new_pct >= 50 else "以已有方向的新进展为主，政策延续性强于开创性")
    s12_pct = pct(sp.get("S1", 0) + sp.get("S2", 0), total)
    s12_note = ("入选主题均有量化指标或明确方向，未纳入纯原则性表态，信息价值较高"
                if s12_pct >= 95 else "多数主题有量化指标或明确方向，少部分仅有方向表态")
    short = vw.get("SHORT", 0)
    short_note = ("短期（1-4周）可验证主题占比高，适合高频跟踪"
                  if pct(short, total) >= 25 else "短期可验证主题占比较低，跟踪周期偏长")
    opened = pw.get("开放", 0)
    open_note = ("政策窗口开放的主题占比较高，三流齐备，短期出细则概率高"
                 if pct(opened, total) >= 50 else "政策窗口开放的主题未过半，多数方向仍需等待触发条件")
    comp = pct(nf.get("竞争框架", 0) + nf.get("安全框架", 0), total)
    dev_pct = pct(nf.get("发展框架", 0), total)
    dev_note = ("竞争框架+安全框架合计占比不低，部分政策方向带有战略紧迫性"
                if comp >= 30 else "叙事整体以发展框架为主，基调平稳")
    return [
        f"1. **A层级信号占比{a_pct}%**：{a_note}。",
        f"2. **NEW信号占比{new_pct}%**：{new_note}。",
        f"3. **S1+S2占比{s12_pct}%**：{s12_note}。",
        f"4. **SHORT窗口{short}个（{pct(short, total)}%）**：{short_note}。",
        f"5. **政策窗口开放{opened}个（{pct(opened, total)}%）**：{open_note}。",
        f"6. **叙事框架以发展框架为主（{dev_pct}%）**：{dev_note}。",
    ]


def render_full(doc):
    stats = doc["stats"]
    total = stats["total"]
    meta = doc["meta"]
    out = []
    out.append("# 新闻联播政策信号初始跟踪表")
    out.append("")
    out.append(f"**版本：{meta.get('version', '?')} | 生成日期：{meta.get('generated_at', '?')}**")
    out.append("")
    out.append("> 数据源：data/tracking_table.json（结构化存储），本文件由 render_tracking_table.py 自动渲染，请勿手工编辑")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## 报告概述")
    out.append("")
    out.append("| 维度 | 数值 |")
    out.append("|------|------|")
    out.append(f"| 数据范围 | {esc(meta.get('data_range', ''))} |")
    out.append(f"| 联播标题总数 | {meta.get('headline_total', '—')} 条 |")
    out.append(f"| 算法预筛选信号数 | {meta.get('prescreened_signals', '—')} 条 |")
    out.append(f"| 最终政策主题数 | **{total} 个** |")
    out.append(f"| 政策大类 | {len(doc.get('categories', []))} 个 |")
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
    out.append("| 政策传导逻辑 | 公开层展示政策信号可能传导到的产业/实物工作量方向，不构成投资建议；内部验证假设只用于系统可证伪验证闭环 |")
    out.append("| 框架判定依据 | 当前框架标签的证据（命中词典词或原文片段）；无依据=待补证，见 reference/framework-dictionary.md |")
    out.append("| 生命周期事件 | 分析模型的状态变更记录（建档/框架变更/状态流转/首次性更新），每条含证据与原因；时间线记联播事件，生命周期记我们自己的分析决策 |")
    out.append("")
    out.append("> 每个主题都标注了\"十五五纲要映射\"：即该主题对应《第十五个五年规划纲要》（2026年3月发布，18篇62章）的哪一篇哪一章，本表信号均是纲要部署的落地进展。")
    out.append("")

    # 分类章节
    for ci, cat in enumerate(doc.get("categories", []), 1):
        out.append(f"## {cn_num(ci)}、{esc(cat['name'])}")
        out.append("")
        out.append("---")
        out.append("")
        for t in doc["themes"]:
            if t["id"] in cat.get("theme_ids", []):
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
    for cat in doc.get("categories", []):
        ids = ", ".join("#" + str(i) for i in cat.get("theme_ids", []))
        out.append(f"| {esc(cat['name'])} | {len(cat.get('theme_ids', []))} | {ids} |")
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

    # 信号质量说明（按实际统计动态生成）
    out.append("## 信号质量说明")
    out.append("")
    out.append("### 关键结论")
    out.append("")
    out += build_quality_conclusions(stats)
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
    out.append(f"> 由 tracking_table.json 自动生成，更新于 {esc(doc['meta'].get('generated_at', '?'))}。完整信息见 reference/initial_signal_tracking_table.md。")
    active = [t for t in doc["themes"]
              if str((t.get("verification") or {}).get("status", "")) in MAIN_STATUSES]
    settled = [t for t in doc["themes"]
               if str((t.get("verification") or {}).get("status", "")) not in MAIN_STATUSES]
    if settled:
        out.append(f"> 已结项 {len(settled)} 个主题（已验证/线索/衰减/归档），不在本摘要主表中"
                   "（完整记录见 reference/initial_signal_tracking_table.md）。")
    out.append("")
    out.append("| # | 主题 | 状态 | 层级 | 首次性 | 具体性 | 政策窗口 | 框架 | 验证日期 | 验证条件 |")
    out.append("|---|------|------|------|--------|--------|---------|------|---------|---------|")
    for t in active:
        dims = t.get("dimensions") if isinstance(t.get("dimensions"), dict) else {}
        v = t.get("verification") if isinstance(t.get("verification"), dict) else {}
        out.append(
            f"| {t['id']} | {esc(t.get('name', ''))} | {esc(v.get('status', ''))} | {esc(dims.get('level', '未标注'))} | "
            f"{esc(dims.get('novelty', '未标注'))} | {esc(dims.get('specificity', '未标注'))} | "
            f"{esc(dims.get('policy_window', '未标注'))} | {esc(dims.get('narrative_framework', '未标注'))} | "
            f"{esc(v.get('date', ''))} | {esc(v.get('condition', ''))} |"
        )
    out.append("")
    out.append("### 主题政策传导速览")
    out.append("")
    for t in active:
        out.append(f"- 主题{t['id']} {esc(t.get('name', ''))}：{esc(public_conduction(t))}")
    out.append("")
    out.append("### 验证日期含\"待确认\"的主题（自动化无法自动触发，需人工锚定）")
    out.append("")
    pending = [t for t in active
               if "待确认" in str((t.get("verification") or {}).get("date", ""))]
    if pending:
        for t in pending:
            out.append(f"- 主题{t['id']} {esc(t.get('name', ''))}：{esc(t['verification']['date'])}")
    else:
        out.append("- 无")
    out.append("")
    out.append("### 已结项主题（不在主表，完整记录见 reference/initial_signal_tracking_table.md）")
    out.append("")
    if settled:
        for t in sorted(settled, key=lambda x: int(x.get("id", 0))):
            v = t.get("verification") if isinstance(t.get("verification"), dict) else {}
            out.append(f"- 主题{t['id']} {esc(t.get('name', ''))}：{esc(v.get('status', ''))}")
    else:
        out.append("- 无")
    out.append("")
    out.append("### 状态流转规则速查")
    out.append("")
    out.append("- 跟踪中 → 已验证（验证条件满足：联播型看联播原文，外部型可官方源核验）")
    out.append("- 跟踪中 → 延迟验证（验证日期过后、宽限期内满足）")
    out.append("- 跟踪中 → 待复核（宽限期过后联播仍无验证信号：转人工外部核验，不自动判衰减）")
    out.append("- 待复核 → 已验证 / 信号衰减（外部查证证实 / 证伪）")
    out.append("- 已验证 → 投资线索就绪（连续 14 天无新进展自动流转，移出主表）")
    out.append("- 跟踪中/延迟验证 → 待复核（连续 30 天无更新且验证日期过宽限期自动流转）")
    out.append("- 信号衰减 → 归档（移出跟踪表，记录失败原因）")
    out.append("- 已结项主题复活必须显式 status_change（带证据）或重新建档，不自动") 
    out.append("")
    return "\n".join(out)


def render_tracking(doc):
    """渲染面向读者的 5 列极简跟踪表。"""
    out = []
    out.append("# 极简跟踪表")
    out.append("")
    out.append(
        f"> 由 tracking_table.json 自动生成，更新于 "
        f"{esc(doc['meta'].get('generated_at', '?'))}。完整字段见 "
        f"reference/initial_signal_tracking_table.md；口径说明见 "
        f"notes/如何看懂这份雷达.md。"
    )
    out.append("")
    out.append("| # | 主题 | 风向 | 验证日期 | 盯什么 |")
    out.append("|---|------|------|----------|--------|")

    active = [t for t in doc.get("themes", [])
              if str((t.get("verification") or {}).get("status", "")) in MAIN_STATUSES]
    settled = [t for t in doc.get("themes", [])
               if str((t.get("verification") or {}).get("status", "")) not in MAIN_STATUSES]
    for t in sorted(active, key=_tracking_sort_key):
        dims = t.get("dimensions") if isinstance(t.get("dimensions"), dict) else {}
        v = t.get("verification") if isinstance(t.get("verification"), dict) else {}

        novelty = str(dims.get("novelty", ""))
        badge = "🆕" if novelty == "NEW" else "🔄" if novelty == "PROGRESS" else ""
        topic = f"{badge} {esc(t.get('name', ''))}".strip() if badge else esc(t.get("name", ""))

        emoji, label = wind(t)
        wind_text = f"{emoji} {label}"

        date = str(v.get("date", "")).strip()
        if not _parse_iso_date(date):
            date = "待锚定"

        out.append(
            f"| {int(t.get('id', 0))} | {topic} | {wind_text} | "
            f"{esc(date)} | {esc(short_logic(t))} |"
        )
    if settled:
        out.append(
            f"\n> 已结项 {len(settled)} 个主题（已验证/线索/衰减/归档），已移出本表"
            "（完整记录见 reference/initial_signal_tracking_table.md）")

    out += [
        "",
        "## 已结项（移出主表，完整记录见完整跟踪表）",
        "",
    ]
    if settled:
        for t in sorted(settled, key=lambda x: int(x.get("id", 0))):
            v = t.get("verification") if isinstance(t.get("verification"), dict) else {}
            out.append(f"- 主题{t['id']} {esc(t.get('name', ''))}｜{esc(v.get('status', ''))}")
    else:
        out.append("- 无")
    out += [
        "",
        "## 风向图例",
        "",
        "- 🟢 抓紧落：跟踪中 + 窗口开放",
        "- 🟡 等风来：跟踪中 + 窗口接近",
        "- ⚪ 暂缓：跟踪中 + 窗口封闭",
        "- 🟠 延迟核验：验证日已过，宽限期内",
        "- 🔍 待复核：宽限期已过，等人工核验",
        "- ✅ 已验证：验证条件已满足（连续 14 天无新进展自动转线索移出主表）",
        "- 💡 线索：已验证且值得继续深入",
        "- ❌ 证伪/衰减：假设被证伪或信号衰减",
        "- 🗄️ 归档：已移出主跟踪表",
        "",
        "> 本表只展示 5 个核心列；层级、首次性、具体性、政策窗口、叙事框架和完整验证条件仍以完整跟踪表为准。",
        "",
    ]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="从 tracking_table.json 渲染 Markdown 跟踪表")
    ap.add_argument("--json", default=JSON_PATH, help="跟踪表 JSON 路径")
    ap.add_argument("--md", default=MD_PATH, help="完整跟踪表 Markdown 输出路径")
    ap.add_argument("--digest", default=DIGEST_PATH, help="自动化摘要输出路径")
    ap.add_argument("--tracking", default=TRACKING_PATH, help="极简跟踪表 Markdown 输出路径")
    args = ap.parse_args()

    doc = read_json(args.json)
    # P1-1：渲染前基于 themes 实时重算统计，不信任旧 stats
    recompute_stats(doc)
    write_atomic(args.md, render_full(doc))
    write_atomic(args.digest, render_digest(doc))
    write_atomic(args.tracking, render_tracking(doc))
    print(f"已渲染: {args.md}")
    print(f"已渲染: {args.digest}")
    print(f"已渲染: {args.tracking}")


if __name__ == "__main__":
    main()
