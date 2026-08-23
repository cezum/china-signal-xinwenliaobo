#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""日报自动化增强：昨日回访 / 周报月报 / 静默主题检测。

2026-08-23 新增（review 待办1）。LLM 生成日报正文后，由 run_daily.py
调用本模块程序化生成增强区块，保证输出稳定、可单元测试：

- 昨日回访：昨日有 lifecycle/timeline 事件的主题，标注今日是否继续有进展；
  插入到“今日要点”之后、“读报指南”之前。
- 本周回顾（周报）：每周日生成，覆盖本周周一至周日。
- 本月回顾（月报）：每月最后一天生成，覆盖本月 1 日至当日。
- 静默主题检测：跟踪中/延迟验证/待复核主题，距最近事件 >= 14 天无更新时提示；
  >= 30 天标注“长期静默”。

2026-08-23 追加（方案 A）：correct_factual_claims() 在落库后用真实跟踪表校正
日报中可机器校验的标注——信号块“已纳入跟踪表主题N（类型）”的编号/类型、
“验证打卡”表格的状态标记；只校结构化标注，不改写叙事文字。
"""

import re
from datetime import date, datetime, timedelta

ACTIVE_SILENCE_STATUSES = {"跟踪中", "延迟验证", "待复核"}
SILENT_DAYS = 14
LONG_SILENT_DAYS = 30
WEEKLY_DAY = 6  # 周日（weekday()：周一=0）
MAX_PERIOD_ROWS = 15  # 周报/月报最多展示的主题行数

STATUS_BADGE = {
    "已验证": "✅ 已验证",
    "延迟验证": "⏳ 延迟验证",
    "待复核": "🔍 待复核",
    "信号衰减": "❌ 信号衰减",
    "归档": "🗄️ 归档",
    "投资线索就绪": "💡 线索",
    "跟踪中": "🟢 跟踪中",
}

CLAIM_RE = re.compile(
    r"已纳入跟踪表主题\s*(\d+)\s*（\s*(首次纳入|进展更新|状态变更|状态流转)\s*）")

TYPE_LABEL = {
    "create": "建档",
    "framework_change": "框架变更",
    "status_change": "状态流转",
    "novelty_change": "首次性更新",
    "verify": "验证",
    "decay": "衰减",
    "update": "进展更新",
}

_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _iso_date(value):
    """把 YYYY-MM-DD / date / datetime 归一为 date；无法解析返回 None。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    m = _ISO.fullmatch(str(value or "").strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
    except ValueError:
        return None


def _esc(value):
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def _event_dates(theme):
    """主题 lifecycle + timeline 中可解析的日期列表。"""
    dates = []
    for ev in theme.get("lifecycle", []):
        if isinstance(ev, dict):
            d = _iso_date(ev.get("date"))
            if d:
                dates.append(d)
    for ev in theme.get("timeline", []):
        if isinstance(ev, dict):
            d = _iso_date(ev.get("date"))
            if d:
                dates.append(d)
    return dates


def last_activity(theme):
    """主题最近一次有记录活动的日期；无任何日期时返回 None。"""
    dates = _event_dates(theme)
    return max(dates) if dates else None


def themes_touched_on(doc, day):
    """返回在 day 当天有 lifecycle/timeline 事件的主题列表。"""
    day = _iso_date(day)
    if day is None:
        return []
    return [t for t in doc.get("themes", [])
            if any(d == day for d in _event_dates(t))]


def _event_actions_on(theme, day):
    """主题在 day 当天的事件摘要（lifecycle 动作 + timeline 事件）。"""
    day = _iso_date(day)
    if day is None:
        return []
    out = []
    for ev in theme.get("lifecycle", []):
        if isinstance(ev, dict) and _iso_date(ev.get("date")) == day:
            label = TYPE_LABEL.get(ev.get("type"), str(ev.get("type") or ""))
            action = str(ev.get("action") or "").strip()
            if action and (action.startswith(f"{label}：") or
                           (label and action.startswith(label))):
                out.append(action)  # 动作自带类型前缀（如"进展更新：…"），避免重复
            else:
                out.append(f"{label}：{action}" if action else label)
    for ev in theme.get("timeline", []):
        if isinstance(ev, dict) and _iso_date(ev.get("date")) == day:
            out.append(f"联播事件：{str(ev.get('event') or '').strip()[:60]}")
    return out


def build_followup_section(doc, today):
    """昨日回访区块：昨日有变动的主题，今日是否继续有进展。"""
    today = _iso_date(today)
    if today is None:
        return ""
    yesterday = today - timedelta(days=1)
    touched = themes_touched_on(doc, yesterday)
    lines = ["## 昨日回访", ""]
    if not touched:
        lines.append(f"昨日（{yesterday.isoformat()}）无主题变动，今日无回访项。")
        lines.append("")
        return "\n".join(lines)
    today_ids = {t["id"] for t in themes_touched_on(doc, today)}
    lines.append(
        f"昨日（{yesterday.isoformat()}）共 {len(touched)} 个主题有变动，今日跟进：")
    lines.append("")
    lines.append("| 主题 | 昨日动作 | 今日跟进 |")
    lines.append("|------|---------|---------|")
    for t in sorted(touched, key=lambda x: int(x.get("id", 0))):
        v = t.get("verification") or {}
        actions = _event_actions_on(t, yesterday)
        action_text = "；".join(actions) if actions else "—"
        follow = "✅ 今日有进展" if t["id"] in today_ids else "⏳ 今日未提及（继续观察）"
        lines.append(
            f"| 主题{t['id']} {_esc(t.get('name', ''))} | {_esc(action_text)} | {follow} |")
    lines.append("")
    return "\n".join(lines)


def build_period_section(title, doc, start, end):
    """周报/月报通用：期间内 lifecycle 事件的主题及其事件数。"""
    start = _iso_date(start)
    end = _iso_date(end)
    if start is None or end is None:
        return ""
    rows = []
    for t in doc.get("themes", []):
        evs = [ev for ev in t.get("lifecycle", []) if isinstance(ev, dict)
               and (d := _iso_date(ev.get("date"))) and start <= d <= end]
        if evs:
            rows.append((t, evs))
    if not rows:
        return f"## {title}\n\n期间（{start} 至 {end}）无主题变动。\n"
    counts = {}
    for _, evs in rows:
        for ev in evs:
            counts[ev.get("type", "update")] = counts.get(ev.get("type", "update"), 0) + 1
    parts = []
    if counts.get("create"):
        parts.append(f"新增 {counts['create']} 个")
    if counts.get("update"):
        parts.append(f"更新 {counts['update']} 次")
    if counts.get("verify"):
        parts.append(f"验证 {counts['verify']} 次")
    if counts.get("decay"):
        parts.append(f"衰减 {counts['decay']} 次")
    if counts.get("status_change"):
        parts.append(f"状态流转 {counts['status_change']} 次")
    summary = f"期间（{start} 至 {end}）共 {len(rows)} 个主题有变动"
    if parts:
        summary += "：" + "、".join(parts)
    lines = ["## " + title, "", summary, "",
             "| 主题 | 事件数 | 最新状态 |", "|------|--------|---------|"]
    rows_sorted = sorted(rows, key=lambda r: -len(r[1]))
    for t, evs in rows_sorted[:MAX_PERIOD_ROWS]:
        v = t.get("verification") or {}
        lines.append(
            f"| 主题{t['id']} {_esc(t.get('name', ''))} | {len(evs)} | "
            f"{_esc(str(v.get('status', '')))} |")
    if len(rows_sorted) > MAX_PERIOD_ROWS:
        lines.append("")
        lines.append(
            f"（其余 {len(rows_sorted) - MAX_PERIOD_ROWS} 个主题略，完整清单见信号跟踪表）")
    lines.append("")
    return "\n".join(lines)


def build_weekly_section(doc, today):
    """本周回顾（周报）：周一至周日。"""
    today = _iso_date(today)
    if today is None:
        return ""
    start = today - timedelta(days=today.weekday())
    return build_period_section("本周回顾（周报）", doc, start, today)


def build_monthly_section(doc, today):
    """本月回顾（月报）：本月 1 日至当日。"""
    today = _iso_date(today)
    if today is None:
        return ""
    start = today.replace(day=1)
    return build_period_section("本月回顾（月报）", doc, start, today)


def build_silence_section(doc, today, silent_days=SILENT_DAYS,
                          long_silent_days=LONG_SILENT_DAYS):
    """静默主题检测：活跃状态但长时间无更新。"""
    today = _iso_date(today)
    if today is None:
        return ""
    rows = []
    for t in doc.get("themes", []):
        v = t.get("verification") or {}
        if str(v.get("status", "")) not in ACTIVE_SILENCE_STATUSES:
            continue
        last = last_activity(t)
        if last is None:
            continue
        days = (today - last).days
        if days >= silent_days:
            rows.append((t, last, days))
    lines = ["## 静默主题检测", ""]
    if not rows:
        lines.append(f"连续 {silent_days} 天无进展更新且仍在跟踪的主题：无。")
        lines.append("")
        return "\n".join(lines)
    lines.append(
        f"连续 ≥{silent_days} 天无进展更新（仍处跟踪中/延迟验证/待复核）的主题：")
    lines.append("")
    lines.append("| 主题 | 最近更新 | 静默天数 | 状态 | 验证日期 |")
    lines.append("|------|---------|---------|------|---------|")
    for t, last, days in sorted(rows, key=lambda r: -r[2]):
        v = t.get("verification") or {}
        flag = "（长期静默）" if days >= long_silent_days else ""
        lines.append(
            f"| 主题{t['id']} {_esc(t.get('name', ''))}{flag} | {last} | {days} 天 | "
            f"{_esc(str(v.get('status', '')))} | {_esc(str(v.get('date', '')))} |")
    lines.append("")
    return "\n".join(lines)


def yesterday_focus_block(doc, today):
    """给 LLM 的“昨日涉及主题”提示块（无昨日变动时返回空串）。"""
    today = _iso_date(today)
    if today is None:
        return ""
    yesterday = today - timedelta(days=1)
    touched = themes_touched_on(doc, yesterday)
    if not touched:
        return ""
    lines = [f"## 昨日涉及主题（{yesterday.isoformat()}）", "",
             "今日分析如涉及以下主题，请在今日要点/信号详析中一句话点明承接关系：", ""]
    for t in sorted(touched, key=lambda x: int(x.get("id", 0))):
        actions = _event_actions_on(t, yesterday)
        lines.append(f"- 主题{t['id']} {t.get('name', '')}："
                     f"{'；'.join(actions) if actions else '有变动'}")
    return "\n".join(lines)


def _last_month_day(d):
    if d.month == 12:
        return d.replace(day=31)
    return d.replace(month=d.month + 1, day=1) - timedelta(days=1)


def _insert_before_heading(md, section, heading):
    """把 section 插到 `## heading` 之前；找不到 heading 时追加到文末。"""
    m = re.search(rf"^##\s*{re.escape(heading)}", md, flags=re.MULTILINE)
    if not m:
        return md.rstrip() + "\n\n---\n\n" + section.strip() + "\n"
    return (md[:m.start()].rstrip() + "\n\n" + section.strip()
            + "\n\n" + md[m.start():])


def enrich_report(md, doc, today):
    """LLM 日报 → 增强版日报：插入昨日回访，追加周报/月报/静默检测。"""
    md = str(md or "")
    if not md.strip():
        return md
    today_d = _iso_date(today) or date.today()
    follow = build_followup_section(doc, today_d)
    if follow:
        md = _insert_before_heading(md, follow, "读报指南")
    extras = []
    if today_d.weekday() == WEEKLY_DAY:
        extras.append(build_weekly_section(doc, today_d))
    if today_d == _last_month_day(today_d):
        extras.append(build_monthly_section(doc, today_d))
    extras.append(build_silence_section(doc, today_d))
    extras = [s for s in extras if s]
    if extras:
        md = md.rstrip() + "\n\n---\n\n" + "\n\n".join(extras).rstrip() + "\n"
    return md


def _event_kind_label(theme, day):
    """主题当天 lifecycle 事件 → 声明类型标签；当天无事件返回 None。"""
    day = _iso_date(day)
    if day is None:
        return None
    kinds = [ev.get("type") for ev in theme.get("lifecycle", [])
             if isinstance(ev, dict) and _iso_date(ev.get("date")) == day]
    if "create" in kinds:
        return "首次纳入"
    if any(k in kinds for k in ("status_change", "verify", "decay")):
        return "状态变更"
    if "update" in kinds:
        return "进展更新"
    return None


def _actual_claim(sig, themes, day):
    """按落库结果给出信号对应的“已纳入跟踪表主题N（类型）”声明；无法确定返回 None。"""
    if sig is None:
        return None
    if sig.get("new_theme"):
        name = str((sig.get("new_theme") or {}).get("name") or "").strip()
        if not name:
            return None
        # apply_result 按名称去重；新主题落库后以名称为准反查 id
        cands = [t for t in themes.values() if t.get("name") == name]
        if not cands:
            return None  # 重复信号被跳过或未落库，保留原文
        t = max(cands, key=lambda x: int(x.get("id", 0)))
        kind = _event_kind_label(t, day)
        return f"已纳入跟踪表主题{t['id']}（{kind}）" if kind else f"已纳入跟踪表主题{t['id']}"
    if sig.get("existing_theme_id") is not None:
        try:
            tid = int(sig["existing_theme_id"])
        except (TypeError, ValueError):
            return None
        t = themes.get(tid)
        if t is None:
            return None
        kind = _event_kind_label(t, day)
        return f"已纳入跟踪表主题{tid}（{kind}）" if kind else f"已纳入跟踪表主题{tid}"
    return None


def _correct_claims_in_block(block, sig, themes, day):
    """把单个信号块里的“已纳入跟踪表主题N（类型）”声明替换为落库真实值。"""
    def repl(m):
        claim = _actual_claim(sig, themes, day)
        return claim if claim else m.group(0)
    return CLAIM_RE.sub(repl, block)


def _correct_checkin_status(md, themes):
    """校正“验证打卡”表格里的状态标记（只替换核验结果单元格开头标记）。"""
    m = re.search(r"(^##\s*验证打卡\s*$.*?)(?=^##\s|\n---|\Z)",
                  md, flags=re.MULTILINE | re.DOTALL)
    if not m:
        return md
    section = m.group(1)

    def row_repl(row):
        tm = re.match(r"^\|\s*(\d+)\s*\|", row)
        if not tm:
            return row
        theme = themes.get(int(tm.group(1)))
        if theme is None:
            return row
        status = str((theme.get("verification") or {}).get("status", ""))
        badge = STATUS_BADGE.get(status)
        if not badge:
            return row
        # 只替换最后一个单元格开头的状态标记，保留后面的解释文字
        def cell_repl(cm):
            return "| " + badge + (cm.group(1) or "").rstrip() + " |"
        return re.sub(
            r"\|\s*(?:✅|⏳|🔍|❌|🗄️|💡|🟢)\s*[^—|：:]*([—|：:][^|]*)?\|\s*$",
            cell_repl, row)

    fixed = "\n".join(row_repl(line) for line in section.split("\n"))
    return md[:m.start(1)] + fixed + md[m.end(1):]


def correct_factual_claims(md, doc, signals, target_date):
    """落库后校正日报中可机器校验的标注（方案 A）。

    - 信号块“已纳入跟踪表主题N（类型）”按实际落库 id/事件类型校正；
    - “验证打卡”表格状态标记按主题实际 verification.status 校正。
    只校结构化标注，不改写叙事文字；无法确定时保留原文。
    """
    day = _iso_date(target_date)
    if day is None:
        return md
    themes = {t["id"]: t for t in doc.get("themes", [])}
    blocks = re.split(r"(?=^###\s*信号)", md, flags=re.MULTILINE)
    signal_blocks = [b for b in blocks if re.match(r"^###\s*信号", b, flags=re.MULTILINE)]
    fixed_blocks = []
    sig_idx = 0
    for idx, block in enumerate(blocks):
        if not re.match(r"^###\s*信号", block, flags=re.MULTILINE):
            fixed_blocks.append(block)
            continue
        sig = signals[sig_idx] if sig_idx < len(signals) else None
        fixed_blocks.append(_correct_claims_in_block(block, sig, themes, day))
        sig_idx += 1
    md = "".join(fixed_blocks)
    md = _correct_checkin_status(md, themes)
    return md
