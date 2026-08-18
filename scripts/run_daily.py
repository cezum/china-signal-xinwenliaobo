#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""每日自动化主流程：抓取 → LLM 分析 → 更新跟踪表 → 渲染 → 生成日报 → 可选推送。

用法：
    python scripts/run_daily.py                      # 默认分析昨日（北京时间）
    python scripts/run_daily.py --date 2026-08-12    # 指定日期
    python scripts/run_daily.py --mock               # 内置样例响应测试全流程（不调 API，输出写临时目录）
    python scripts/run_daily.py --dry-run            # 真实抓取/分析，但输出写临时目录，不改真实数据

环境变量：
    LLM_API_KEY    必填（OpenAI 兼容接口 key，如 DeepSeek）
    LLM_BASE_URL   可选，默认 https://api.deepseek.com（空值视为未设置）
    LLM_MODEL      可选，默认 deepseek-chat（空值视为未设置）
    NOTIFY_TYPE    可选：serverchan / wecom
    NOTIFY_WEBHOOK 可选：对应推送渠道的 webhook 地址
    VERIFY_LIMIT   可选：每轮外部查证的主题数上限，默认 5

修复背景（代码审查 2026-08-16）：
- P1-2 可选环境变量空值覆盖默认值：env_or() 把空字符串视为未设置。
- P1-3 关键文件原子写入 + .bak 备份/恢复：见 common.py。
- P1-4 渲染/推送失败只降级为警告，不阻断主流程（数据落盘不受影响）。
- P1-5 LLM 输出 schema 校验，失败回传错误重试一次；ID 统一 int；
       新主题按名称去重；空跟踪表不崩溃。
- P1-1 更新主题后实时重算 stats 并刷新 meta.generated_at。
- 次要 1 假设检验到期检查：可解析日期+宽限期自动流转状态。
- 次要 3 默认“昨日”改用 Asia/Shanghai 时区。
- 次要 7 --mock/--dry-run 输出写入临时目录，不污染真实数据。
- 安全 5/6 LLM 错误日志脱敏；webhook 协议校验。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # Python < 3.9 或系统无 tzdata
    CN_TZ = timezone(timedelta(hours=8))

from common import read_text, write_atomic, read_json, write_json, recompute_stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
DATA = os.path.join(ROOT, "data")
REF = os.path.join(ROOT, "reference")

# 路径集中管理：--dry-run / --mock 时整体替换为临时目录
PATHS = {
    "raw": os.path.join(DATA, "raw"),
    "tracking": os.path.join(DATA, "tracking_table.json"),
    "digest": os.path.join(DATA, "tracking_table_digest.md"),
    "tracking_md": os.path.join(ROOT, "tracking.md"),
    "reports": os.path.join(ROOT, "reports"),
}

PROMPT_MD = os.path.join(ROOT, "PROMPT.md")
DICT_MD = os.path.join(REF, "framework-dictionary.md")
STRUCT_MD = os.path.join(REF, "15fyp-outline-reference.md")

DIM_KEYS = {
    "level", "novelty", "specificity", "policy_window",
    "verification_window", "narrative_framework",
}
VER_KEYS = {"condition", "source", "date", "grace_period", "status", "external_url"}
LIFECYCLE_TYPES = {
    "create", "framework_change", "status_change",
    "novelty_change", "verify", "decay", "update",
}
DIM_VALUES = {
    "level": {"A", "B", "C", "D"},
    "novelty": {"NEW", "PROGRESS", "REPEAT"},
    "specificity": {"S1", "S2", "S3"},
    "policy_window": {"开放", "接近", "封闭"},
    "verification_window": {"SHORT", "MID", "LONG"},
    "narrative_framework": {"发展框架", "竞争框架", "民生框架", "安全框架"},
}
VER_STATUS = {"跟踪中", "已验证", "延迟验证", "待复核", "信号衰减", "投资线索就绪", "归档"}
DEFAULT_CATEGORY = "产业政策与科技创新"


def env_or(name, default=""):
    """环境变量存在但为空字符串时视为未设置，返回默认值（P1-2）。"""
    return os.environ.get(name) or default


def _redact(text, secrets):
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---------------------------------------------------------------- 抓取与 LLM

def fetch_transcript(target_date):
    os.makedirs(PATHS["raw"], exist_ok=True)
    cmd = [sys.executable, os.path.join(SCRIPTS, "fetch_xwlb.py"),
           "--date", target_date, "--outdir", PATHS["raw"]]
    res = run(cmd, timeout=300)
    if res.returncode != 0:
        raise SystemExit(f"抓取失败：{_redact(res.stderr, [env_or('LLM_API_KEY')])[-800:]}")
    path = os.path.join(PATHS["raw"], f"xwlb_{target_date.replace('-', '')}_text.md")
    if not os.path.exists(path):
        raise SystemExit(f"抓取完成但未找到输出：{path}")
    return path


def build_messages(transcript_path):
    system = read_text(PROMPT_MD)
    parts = [f"## 当日联播全文（{os.path.basename(transcript_path)}）\n{read_text(transcript_path)}"]
    if os.path.exists(PATHS["digest"]):
        parts.append(f"## 信号跟踪表摘要\n{read_text(PATHS['digest'])}")
    parts += [
        f"## 框架判定词典\n{read_text(DICT_MD)}",
        f"## 十五五纲要结构参考\n{read_text(STRUCT_MD)}",
        "请按系统指令输出 JSON。",
    ]
    return system, "\n\n".join(parts)


def call_llm(system, user, retry_error=None):
    api_key = env_or("LLM_API_KEY")
    if not api_key:
        raise SystemExit("缺少环境变量 LLM_API_KEY")
    base = env_or("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = env_or("LLM_MODEL", "deepseek-chat")

    if retry_error:
        user = user + f"\n\n上次输出解析/校验失败：{_redact(retry_error, [api_key])}\n请重新输出严格 JSON。"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    def post(pl):
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=json.dumps(pl).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        data = post(payload)
    except urllib.error.HTTPError as e:
        if e.code == 400 and payload.get("response_format"):
            payload.pop("response_format")  # 部分接口不支持 json_object
            data = post(payload)
        else:
            detail = _redact(e.read().decode("utf-8", "ignore")[-500:], [api_key])
            raise SystemExit(f"LLM 调用失败 HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"LLM 网络错误：{e.reason}")

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"LLM 响应缺少预期字段：{type(e).__name__}: {e}")
    return parse_json(content)


def parse_json(content):
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    return json.loads(text)


def _validate_report_structure(report):
    """校验日报双层 HTML 结构：闭合、嵌套顺序、每卡配对、summary 固定文案。"""
    errors = []
    speed = re.search(
        r"^##\s*🎯\s*今日速览\s*$(.*?)"
        r"(?=^##\s*📌\s*风险与验证打卡\s*$|^##\s*⚠️\s*风险提示\s*$|\Z)",
        report,
        flags=re.MULTILINE | re.DOTALL,
    )
    cards = re.findall(r"^####\s*\d+\.\s*\S", speed.group(1), flags=re.MULTILINE) if speed else []

    details_open = report.count("<details>")
    details_close = report.count("</details>")
    summary_open = report.count("<summary>")
    summary_close = report.count("</summary>")

    if details_open != details_close:
        errors.append(
            f"report_markdown 中 <details> 与 </details> 数量不一致"
            f"（{details_open} 对 {details_close}）")
    if summary_open != summary_close:
        errors.append(
            f"report_markdown 中 <summary> 与 </summary> 数量不一致"
            f"（{summary_open} 对 {summary_close}）")
    if details_open == 0 or summary_open == 0:
        errors.append("report_markdown 必须使用双层 <details> 结构：每个速览卡片后都要有证据与方法底稿")
    if summary_open != details_open:
        errors.append(
            f"report_markdown 中 <details> 与 <summary> 数量不一致"
            f"（{details_open} 个 details，{summary_open} 个 summary）")
    if cards and len(cards) != details_open:
        errors.append(
            f"report_markdown 今日速览有 {len(cards)} 张卡片，"
            f"但只有 {details_open} 个 <details>，每张卡片后必须对应一个折叠底稿")

    for i, text in enumerate(re.findall(r"<summary>(.*?)</summary>", report, re.DOTALL), 1):
        if text.strip() != "📂 证据与方法底稿":
            errors.append(
                f"report_markdown 第 {i} 个 <summary> 内容必须固定为"
                f"「📂 证据与方法底稿」")

    stack = []
    tokens = re.findall(r"</?details>|</?summary>", report, flags=re.IGNORECASE)
    for token in tokens:
        tag = token.lower()
        if tag == "<details>":
            stack.append("details")
        elif tag == "<summary>":
            if not stack or stack[-1] != "details":
                errors.append("report_markdown 中 <summary> 必须位于 <details> 内")
                break
            stack.append("summary")
        elif tag == "</summary>":
            if not stack or stack[-1] != "summary":
                errors.append("report_markdown 中 </summary> 缺少对应的 <summary>")
                break
            stack.pop()
        elif tag == "</details>":
            if not stack or stack[-1] != "details":
                errors.append("report_markdown 中 </details> 缺少对应的 <details>")
                break
            stack.pop()
    else:
        if stack:
            errors.append("report_markdown 中 HTML 标签未正确闭合或嵌套")
    return errors


# ---------------------------------------------------------------- 输出校验

def validate_llm_result(result):
    """校验 LLM 输出结构，返回 (errors, warnings)。

    errors（类型/结构硬错误）：回传 LLM 重试，重试后仍失败则中止；
    warnings（枚举值偏离等软问题）：记日志并回退默认值，不阻断流程。
    """
    errors, warnings = [], []
    if not isinstance(result, dict):
        return ["顶层不是 JSON 对象"], warnings

    signals = result.get("signals")
    if not isinstance(signals, list):
        errors.append("signals 必须是数组")
    else:
        for i, sig in enumerate(signals):
            tag = f"signals[{i}]"
            if not isinstance(sig, dict):
                errors.append(f"{tag} 不是对象")
                continue
            has_new = bool(sig.get("new_theme"))
            has_existing = sig.get("existing_theme_id") is not None
            if has_new == has_existing:
                errors.append(f"{tag} 必须二选一：new_theme 或 existing_theme_id")
            if has_new:
                nt = sig["new_theme"]
                if not isinstance(nt, dict):
                    errors.append(f"{tag}.new_theme 不是对象")
                    continue
                name = nt.get("name")
                if not isinstance(name, str) or not name.strip():
                    errors.append(f"{tag}.new_theme.name 缺失或为空")
                dims = nt.get("dimensions")
                if not isinstance(dims, dict):
                    errors.append(f"{tag}.new_theme.dimensions 必须是对象")
                else:
                    for k, allowed in DIM_VALUES.items():
                        v = dims.get(k)
                        if v is None:
                            warnings.append(f"{tag}.new_theme.dimensions.{k} 缺失，回退默认值")
                        elif v not in allowed:
                            warnings.append(f"{tag}.new_theme.dimensions.{k} 非法值 {v!r}，回退默认值")
                for key in ("lifecycle", "timeline"):
                    if key in nt and not isinstance(nt[key], list):
                        errors.append(f"{tag}.new_theme.{key} 必须是数组")
                if not isinstance(nt.get("verification"), dict):
                    errors.append(f"{tag}.new_theme.verification 必须是对象")
                elif "status" in nt["verification"] and nt["verification"]["status"] not in VER_STATUS:
                    warnings.append(f"{tag}.new_theme.verification.status 非法值，回退默认值")
                if "public_conduction" in nt and not isinstance(nt["public_conduction"], str):
                    errors.append(f"{tag}.new_theme.public_conduction 必须是字符串")
                if "category" in nt and not isinstance(nt["category"], str):
                    errors.append(f"{tag}.new_theme.category 必须是字符串")
            else:
                tid = sig["existing_theme_id"]
                if not (isinstance(tid, int) or (isinstance(tid, str) and tid.strip().isdigit())):
                    errors.append(f"{tag}.existing_theme_id 必须是整数或数字字符串：{tid!r}")
                upd = sig.get("update", {})
                if not isinstance(upd, dict):
                    errors.append(f"{tag}.update 必须是对象")
                    continue
                dims = upd.get("dimensions")
                if dims is not None:
                    if not isinstance(dims, dict):
                        errors.append(f"{tag}.update.dimensions 必须是对象")
                    else:
                        for k, v in dims.items():
                            if k in DIM_VALUES and v not in DIM_VALUES[k]:
                                errors.append(f"{tag}.update.dimensions.{k} 非法值：{v!r}")
                if "lifecycle_events" in upd and not isinstance(upd["lifecycle_events"], list):
                    errors.append(f"{tag}.update.lifecycle_events 必须是数组")
                ver = upd.get("verification")
                if ver is not None:
                    if not isinstance(ver, dict):
                        errors.append(f"{tag}.update.verification 必须是对象")
                    elif "status" in ver and ver["status"] not in VER_STATUS:
                        errors.append(f"{tag}.update.verification.status 非法值：{ver['status']!r}")
                if "public_conduction" in upd and not isinstance(upd["public_conduction"], str):
                    errors.append(f"{tag}.update.public_conduction 必须是字符串")

    report = result.get("report_markdown")
    if not isinstance(report, str) or not report.strip():
        errors.append("report_markdown 缺失或为空")
    else:
        errors.extend(_validate_report_structure(report))

    summary = result.get("report_summary")
    if not isinstance(summary, str) or not summary.strip():
        warnings.append("report_summary 缺失或为空，推送将回退解析日报正文")
    if not isinstance(result.get("expiry_check"), str):
        warnings.append("expiry_check 缺失，视为无到期检验点")
    return errors, warnings


# ---------------------------------------------------------------- 跟踪表更新

def apply_result(doc, result, target_date):
    """把 LLM 返回的 signals 应用到跟踪表；重算 stats 后原子写回。"""
    themes = doc["themes"]
    categories = doc["categories"]
    max_id = max((t["id"] for t in themes), default=0)
    stats = {"new": 0, "updated": 0, "duplicates": 0, "missing": 0}

    for sig in result.get("signals", []):
        if sig.get("new_theme"):
            nt = sig["new_theme"]
            name = str(nt.get("name") or "").strip() or f"主题{max_id + 1}"
            # 新主题按名称去重（防止重复运行/LLM 漂移累积重复主题）
            dup = next((t for t in themes if t.get("name") == name), None)
            if dup is not None:
                print(f"        跳过重复新主题：{name}（已存在，id={dup['id']}）")
                stats["duplicates"] += 1
                continue
            max_id += 1
            dims_raw = nt.get("dimensions") if isinstance(nt.get("dimensions"), dict) else {}
            ver = nt.get("verification") if isinstance(nt.get("verification"), dict) else {}
            theme = {
                "id": max_id,
                "name": name,
                "investment_hypothesis": str(nt.get("investment_hypothesis") or ""),
                "public_conduction": str(nt.get("public_conduction") or ""),
                "dimensions": {
                    k: (dims_raw.get(k) if dims_raw.get(k) in DIM_VALUES[k] else "未标注")
                    for k in DIM_VALUES
                },
                "framework_evidence": str(nt.get("framework_evidence") or ""),
                "lifecycle": [ev for ev in nt.get("lifecycle", []) if isinstance(ev, dict)],
                "timeline": [ev for ev in nt.get("timeline", []) if isinstance(ev, dict)],
                "outline_mapping": str(nt.get("outline_mapping") or ""),
                "verification": {
                    "condition": str(ver.get("condition") or ""),
                    "source": str(ver.get("source") or "联播"),
                    "date": str(ver.get("date") or ""),
                    "grace_period": str(ver.get("grace_period") or ""),
                    "status": ver.get("status") if ver.get("status") in VER_STATUS else "跟踪中",
                    "external_url": str(ver.get("external_url") or ""),
                },
                "category": str(nt.get("category") or DEFAULT_CATEGORY),
            }
            themes.append(theme)
            cat = next((c for c in categories if c["name"] == theme["category"]), None)
            if cat is None:
                categories.append({"name": theme["category"], "theme_ids": []})
                cat = categories[-1]
            if max_id not in cat["theme_ids"]:
                cat["theme_ids"].append(max_id)
            stats["new"] += 1
            continue

        if sig.get("existing_theme_id") is not None:
            # 统一 int() 转换，避免字符串主题 ID 被静默忽略（P1-5）
            try:
                tid = int(sig["existing_theme_id"])
            except (TypeError, ValueError):
                print(f"        忽略无法解析的 existing_theme_id：{sig['existing_theme_id']!r}")
                stats["missing"] += 1
                continue
            theme = next((t for t in themes if t["id"] == tid), None)
            if theme is None:
                print(f"        忽略不存在的主题 id：{tid}")
                stats["missing"] += 1
                continue
            upd = sig.get("update") or {}
            for ev in upd.get("lifecycle_events", []):
                if isinstance(ev, dict):
                    if ev.get("type") not in LIFECYCLE_TYPES:
                        ev["type"] = "update"
                    theme.setdefault("lifecycle", []).append(ev)
            dims = upd.get("dimensions")
            if isinstance(dims, dict):
                for k, v in dims.items():
                    if k in DIM_KEYS and v in DIM_VALUES[k]:
                        theme["dimensions"][k] = v
            if upd.get("framework_evidence"):
                theme["framework_evidence"] = upd["framework_evidence"]
            if upd.get("investment_hypothesis"):
                theme["investment_hypothesis"] = upd["investment_hypothesis"]
            if upd.get("public_conduction"):
                theme["public_conduction"] = upd["public_conduction"]
            ver = upd.get("verification")
            if isinstance(ver, dict):
                for k, v in ver.items():
                    if k not in VER_KEYS:
                        continue
                    if k == "status" and v not in VER_STATUS:
                        continue
                    theme["verification"][k] = v
            stats["updated"] += 1

    # P1-1：更新后实时重算统计并刷新生成日期，再原子写回（P1-3）
    recompute_stats(doc)
    doc["meta"]["generated_at"] = target_date
    write_json(PATHS["tracking"], doc, backup=True)
    return stats


def apply_expiry_checks(doc, today):
    """假设检验到期检查：可解析的验证日期+宽限期自动流转状态。

    仅处理 ISO 日期与 “+N天” 形式的宽限期；自由文本日期交给
    LLM 的 expiry_check 与人工校准（digest 中会列出待确认项）。
    返回发生流转的主题数。
    """
    try:
        today_d = datetime.strptime(today, "%Y-%m-%d").date()
    except ValueError:
        return 0
    changed = 0
    for t in doc["themes"]:
        v = t.get("verification") or {}
        if v.get("status") not in ("跟踪中", "延迟验证"):
            continue
        date_str = str(v.get("date") or "").strip()
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})", date_str)
        if not m:
            continue
        due = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        if due >= today_d:
            continue
        grace = 0
        gm = re.fullmatch(r"\+?(\d+)\s*天", str(v.get("grace_period") or "").strip())
        if gm:
            grace = int(gm.group(1))
        if today_d > due + timedelta(days=grace):
            # 宽限期已过但并未确认"事实未发生"：外部事件型验证点可能早已
            # 发生而联播未报道，自动判"信号衰减"会误杀。因此只流转到
            # "待复核"，终判交给人工或外部查证。
            new_status, ev_type = "待复核", "status_change"
        else:
            new_status, ev_type = "延迟验证", "status_change"
        if v.get("status") == new_status:
            continue
        old = v["status"]
        v["status"] = new_status
        t.setdefault("lifecycle", []).append({
            "date": today,
            "type": ev_type,
            "action": f"验证日期到期自动流转：{old} → {new_status}",
            "evidence": f"验证日期 {date_str}（宽限期 {v.get('grace_period') or '无'}）",
            "reason": ("到期检查自动触发" if new_status == "延迟验证"
                       else "宽限期已过且联播无验证信号，转人工外部核验（外部事件型验证点可能已发生而未上联播）"),
        })
        changed += 1
    return changed


# ---------------------------------------------------------------- 通知

def _strip_html(text):
    """去掉 <details> 折叠块和 HTML 标签，返回纯文本。"""
    text = re.sub(r"<details>.*?</details>", "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def build_notify_text(md):
    """从日报 Markdown 中提取适合推送的纯文本摘要。"""
    parts = []

    title = re.search(r"^#\s+.*$", md, flags=re.M)
    if title:
        parts.append(title.group(0).strip())

    one_line = re.search(r">\s*今日一句[：:]\s*(.*)", md)
    if one_line:
        parts.append("今日一句：" + one_line.group(1).strip())

    cards = re.search(
        r"##\s*🎯\s*今日速览(.*?)(?=\n##\s*📌\s*风险与验证打卡|\n##\s*⚠️\s*风险提示)",
        md, flags=re.S)
    if cards:
        body = _strip_html(cards.group(1))
        if body:
            parts.append("🎯 今日速览\n" + body)

    verify = re.search(
        r"##\s*📌\s*风险与验证打卡(.*?)(?=\n##\s*⚠️\s*风险提示|\Z)",
        md, flags=re.S)
    if verify:
        body = _strip_html(verify.group(1))
        if body:
            parts.append("📌 风险与验证打卡\n" + body)

    return "\n\n".join(parts) if parts else _strip_html(md)


def notify(report_path, summary=None):
    """推送日报简报；任何失败只降级为警告，不阻断主流程（P1-4）。"""
    try:
        notify_type = env_or("NOTIFY_TYPE").strip().lower()
        webhook = env_or("NOTIFY_WEBHOOK").strip()
        if not notify_type or not webhook:
            return
        parsed = urllib.parse.urlparse(webhook)
        if parsed.scheme not in ("http", "https"):
            print(f"警告：NOTIFY_WEBHOOK 协议非法（{parsed.scheme or '空'}），跳过推送")
            return

        md = read_text(report_path)
        text = (_strip_html(summary or "") if summary else "") or build_notify_text(md)
        text = text[:1200]
        title = f"联播风向标 {os.path.basename(report_path)[:10]}"

        if notify_type == "serverchan":
            body = urllib.parse.urlencode({"title": title, "desp": text}).encode("utf-8")
            req = urllib.request.Request(webhook, data=body, method="POST")
            with urllib.request.urlopen(req, timeout=60):
                pass
        elif notify_type == "wecom":
            payload = {"msgtype": "markdown", "markdown": {"content": f"## {title}\n{text}"}}
            req = urllib.request.Request(
                webhook, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=60):
                pass
        else:
            print(f"警告：未知 NOTIFY_TYPE：{notify_type}，跳过推送")
    except Exception as e:
        print(f"警告：通知推送失败（不影响主流程）：{type(e).__name__}: {e}")


# ---------------------------------------------------------------- 主流程

def setup_temp_paths():
    """--dry-run / --mock：所有输出重定向到临时目录，不碰真实数据。

    可用环境变量 XWLB_TMP_ROOT 指定输出根目录（默认为系统临时目录）。
    """
    base = env_or("XWLB_TMP_ROOT") or tempfile.mkdtemp(prefix="xwlb_run_")
    tmp = os.path.abspath(base)
    tmp_data = os.path.join(tmp, "data")
    tmp_reports = os.path.join(tmp, "reports")
    tmp_ref = os.path.join(tmp, "reference")
    os.makedirs(os.path.join(tmp_data, "raw"), exist_ok=True)
    os.makedirs(tmp_reports, exist_ok=True)
    os.makedirs(tmp_ref, exist_ok=True)
    if not os.path.exists(PATHS["tracking"]):
        raise SystemExit("tracking_table.json 不存在，无法运行（dry-run 也基于现有跟踪表）")
    write_json(os.path.join(tmp_data, "tracking_table.json"), read_json(PATHS["tracking"]))
    if os.path.exists(PATHS["digest"]):
        write_atomic(os.path.join(tmp_data, "tracking_table_digest.md"),
                     read_text(PATHS["digest"]))
    PATHS.update({
        "raw": os.path.join(tmp_data, "raw"),
        "tracking": os.path.join(tmp_data, "tracking_table.json"),
        "digest": os.path.join(tmp_data, "tracking_table_digest.md"),
        "tracking_md": os.path.join(tmp, "tracking.md"),
        "reports": tmp_reports,
    })
    return tmp


def main():
    ap = argparse.ArgumentParser(description="每日自动化主流程")
    ap.add_argument("--date", help="分析日期 YYYY-MM-DD（默认昨日，北京时间）")
    ap.add_argument("--mock", action="store_true",
                    help="用内置样例响应测试流程（不调 API，输出写入临时目录）")
    ap.add_argument("--dry-run", action="store_true",
                    help="真实抓取/分析，但输出写入临时目录，不改真实数据")
    args = ap.parse_args()

    dry_run = args.dry_run or args.mock
    tmp_root = None
    if dry_run:
        tmp_root = setup_temp_paths()
        print(f"[dry-run] 输出写入临时目录：{tmp_root}")

    # 默认“昨日”按北京时间计算（凌晨 0-8 点也不会拿到前天）
    target_date = args.date or (datetime.now(CN_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"[1/7] 日期：{target_date}")

    if args.mock:
        result = {
            "signals": [
                {
                    "existing_theme_id": None,
                    "new_theme": {
                        "name": "示例测试主题",
                        "investment_hypothesis": "测试假设 → 测试产业链",
                        "dimensions": {"level": "C", "novelty": "NEW", "specificity": "S2",
                                       "policy_window": "接近", "verification_window": "MID",
                                       "narrative_framework": "发展框架"},
                        "framework_evidence": "mock 判定依据",
                        "lifecycle": [{"date": target_date, "type": "create",
                                       "action": "主题建档（首次纳入跟踪）",
                                       "evidence": "mock 证据", "reason": "mock 测试"}],
                        "timeline": [{"date": target_date, "event": "mock 联播事件"}],
                        "outline_mapping": "第五篇 第16章（有效投资）",
                        "verification": {"condition": "联播报道 mock 检验条件", "source": "联播",
                                         "date": "2026-12-31", "grace_period": "+30天",
                                         "status": "跟踪中"},
                        "category": DEFAULT_CATEGORY,
                    },
                }
            ],
            "expiry_check": "mock：无检验点到期",
            "report_summary": (
                f"联播风向标 | {target_date}\n"
                "今日一句：mock 测试信号。\n"
                "🎯 今日速览：示例测试主题，测试假设 → 测试产业链。\n"
                "📌 验证打卡：暂无。"
            ),
            "report_markdown": (
                f"# 联播风向标 | {target_date}\n\n"
                "> 今日一句：mock 测试信号。\n\n"
                "## 🎯 今日速览\n\n"
                "#### 1. 🆕 示例测试主题\n\n"
                "- **联播怎么说：** mock 联播事件。\n"
                "- **行业传导：** 测试产业链。\n"
                "- **接下来盯：** 联播报道 mock 检验条件。\n"
                "- **📈 叙事：卷发展 · 🆕 新建主题**\n\n"
                "<details>\n"
                "<summary>📂 证据与方法底稿</summary>\n\n"
                "- **联播原文：** mock 证据\n"
                "- **维度：** C / NEW / S2 / 接近 / MID\n"
                "- **叙事框架：** 发展框架（mock 判定依据）\n"
                "- **投资假设：** 测试假设 → 测试产业链\n"
                "- **验证条件：** 联播报道 mock 检验条件\n"
                "- **验证日期：** 2026-12-31\n"
                "- **十五五映射：** 第五篇 第16章（有效投资）\n\n"
                "</details>\n\n"
                "---\n\n"
                "## 📌 风险与验证打卡\n\n"
                "- ✅ 无到期验证\n\n"
                "## ⚠️ 风险提示\n\n"
                "- mock 风险提示。\n"
            ),
        }
    else:
        print("[2/7] 抓取联播全文...")
        transcript = fetch_transcript(target_date)
        system, user = build_messages(transcript)
        print("[3/7] 调用 LLM 分析...")
        result = None
        retry_error = None
        for attempt in (1, 2):
            try:
                result = call_llm(system, user, retry_error=retry_error)
            except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
                retry_error = f"{type(e).__name__}: {e}"
                if attempt == 1:
                    print("LLM 输出解析失败，重试一次...")
                    continue
                raise SystemExit(f"LLM 输出连续两次解析失败：{retry_error}")
            errors, warnings = validate_llm_result(result)
            for w in warnings:
                print(f"        [validate] 警告：{w}")
            if errors:
                if attempt == 1:
                    retry_error = "；".join(errors[:5])
                    print(f"        [validate] 校验失败，回传错误重试一次：{retry_error}")
                    continue
                raise SystemExit(
                    "LLM 输出连续两次校验失败：\n  - " + "\n  - ".join(errors))
            break

    if not result.get("report_markdown"):
        raise SystemExit("LLM 输出缺少 report_markdown，中止（未修改跟踪表）")

    print("[4/7] 更新跟踪表...")
    doc = read_json(PATHS["tracking"])
    stats = apply_result(doc, result, target_date)
    print(f"       新增主题 {stats['new']} 个，更新 {stats['updated']} 个，"
          f"重复跳过 {stats['duplicates']} 个，无效 id {stats['missing']} 个")

    expiry_changed = apply_expiry_checks(doc, target_date)
    if expiry_changed:
        write_json(PATHS["tracking"], doc, backup=True)
        print(f"       到期检查自动流转 {expiry_changed} 个主题")
    else:
        print("       到期检查：无到期检验点")

    # 第二档：到期主题外部查证（联网核实外部型验证点，避免单一信源假阴性）。
    # 失败/超时只降级为警告，不影响主流程（P1-4 精神）。
    if not dry_run:
        print("[4.5/7] 外部查证到期主题...")
        try:
            verify_limit = int(env_or("VERIFY_LIMIT") or 5)
        except ValueError:
            verify_limit = 5
        try:
            res = run([sys.executable, os.path.join(SCRIPTS, "verify_external.py"),
                       "--date", target_date, "--limit", str(verify_limit)],
                      timeout=600)
            if res.returncode != 0:
                detail = _redact(res.stderr, [env_or('LLM_API_KEY')])[-300:]
                print(f"警告：外部查证失败（不影响主流程）：{detail}")
        except subprocess.TimeoutExpired:
            print("警告：外部查证超时（不影响主流程）")

    print("[5/7] 生成日报...")
    report_path = os.path.join(PATHS["reports"], f"{target_date}.md")
    write_atomic(report_path, result["report_markdown"])

    print("[6/7] 渲染跟踪表...")
    render_cmd = [sys.executable, os.path.join(SCRIPTS, "render_tracking_table.py"),
                  "--json", PATHS["tracking"], "--digest", PATHS["digest"],
                  "--tracking", PATHS["tracking_md"]]
    if dry_run:
        render_cmd += ["--md", os.path.join(tmp_root, "reference",
                                            "initial_signal_tracking_table.md")]
    try:
        res = run(render_cmd, timeout=120)
        if res.returncode != 0:
            print(f"警告：渲染失败 {_redact(res.stderr, [env_or('LLM_API_KEY')])[-400:]}")
    except subprocess.TimeoutExpired:
        print("警告：渲染超时（不影响主流程，数据已落盘）")

    print("[7/7] 推送通知...")
    if dry_run:
        print("        dry-run：跳过真实推送")
    else:
        notify(report_path, summary=result.get("report_summary"))

    if dry_run:
        print(f"完成（dry-run）：{report_path}")
        print(f"临时目录：{tmp_root}（查看输出后请自行删除）")
    else:
        print(f"完成：{report_path}")


if __name__ == "__main__":
    main()
