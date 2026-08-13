#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""每日自动化主流程：抓取 → LLM 分析 → 更新跟踪表 → 渲染 → 生成日报 → 可选推送。

用法：
    python scripts/run_daily.py                      # 默认分析昨日（UTC 日期-1）
    python scripts/run_daily.py --date 2026-08-12    # 指定日期
    python scripts/run_daily.py --mock               # 内置样例响应，测试全流程（不调 API）

环境变量：
    LLM_API_KEY    必填（OpenAI 兼容接口 key，如 DeepSeek）
    LLM_BASE_URL   可选，默认 https://api.deepseek.com
    LLM_MODEL      可选，默认 deepseek-chat
    NOTIFY_TYPE    可选：serverchan / wecom
    NOTIFY_WEBHOOK 可选：对应推送渠道的 webhook 地址
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
DATA = os.path.join(ROOT, "data")
RAW_DIR = os.path.join(DATA, "raw")
REF = os.path.join(ROOT, "reference")
REPORTS = os.path.join(ROOT, "reports")

TRACKING_JSON = os.path.join(DATA, "tracking_table.json")
DIGEST_MD = os.path.join(DATA, "tracking_table_digest.md")
PROMPT_MD = os.path.join(ROOT, "PROMPT.md")
DICT_MD = os.path.join(REF, "framework-dictionary.md")
STRUCT_MD = os.path.join(REF, "15fyp-outline-reference.md")

DIM_KEYS = {
    "level", "novelty", "specificity", "policy_window",
    "verification_window", "narrative_framework",
}
VER_KEYS = {"condition", "source", "date", "grace_period", "status"}
LIFECYCLE_TYPES = {
    "create", "framework_change", "status_change",
    "novelty_change", "verify", "decay", "update",
}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def fetch_transcript(target_date):
    os.makedirs(RAW_DIR, exist_ok=True)
    cmd = [sys.executable, os.path.join(SCRIPTS, "fetch_xwlb.py"),
           "--date", target_date, "--outdir", RAW_DIR]
    res = run(cmd, timeout=300)
    if res.returncode != 0:
        raise SystemExit(f"抓取失败：{res.stderr[-800:]}")
    path = os.path.join(RAW_DIR, f"xwlb_{target_date.replace('-', '')}_text.md")
    if not os.path.exists(path):
        raise SystemExit(f"抓取完成但未找到输出：{path}")
    return path


def build_messages(transcript_path):
    system = read(PROMPT_MD)
    user = "\n\n".join([
        f"## 当日联播全文（{os.path.basename(transcript_path)}）\n{read(transcript_path)}",
        f"## 信号跟踪表摘要\n{read(DIGEST_MD)}",
        f"## 框架判定词典\n{read(DICT_MD)}",
        f"## 十五五纲要结构参考\n{read(STRUCT_MD)}",
        "请按系统指令输出 JSON。",
    ])
    return system, user


def call_llm(system, user, retry_error=None):
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise SystemExit("缺少环境变量 LLM_API_KEY")
    base = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.environ.get("LLM_MODEL", "deepseek-chat")

    if retry_error:
        user = user + f"\n\n上次输出解析失败：{retry_error}\n请重新输出严格 JSON。"

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
            raise SystemExit(f"LLM 调用失败 HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[-500:]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"LLM 网络错误：{e.reason}")

    content = data["choices"][0]["message"]["content"]
    return parse_json(content)


def parse_json(content):
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    return json.loads(text)


def apply_result(doc, result, target_date):
    """把 LLM 返回的 signals 应用到跟踪表，返回更新统计。"""
    themes = doc["themes"]
    categories = doc["categories"]
    max_id = max(t["id"] for t in themes)
    stats = {"new": 0, "updated": 0}

    for sig in result.get("signals", []):
        if sig.get("new_theme"):
            nt = sig["new_theme"]
            max_id += 1
            theme = {
                "id": max_id,
                "name": nt.get("name", f"主题{max_id}"),
                "investment_hypothesis": nt.get("investment_hypothesis", ""),
                "dimensions": {
                    k: nt.get("dimensions", {}).get(k, "未标注")
                    for k in ["level", "novelty", "specificity",
                              "policy_window", "verification_window", "narrative_framework"]
                },
                "framework_evidence": nt.get("framework_evidence", ""),
                "lifecycle": nt.get("lifecycle", []),
                "timeline": nt.get("timeline", []),
                "outline_mapping": nt.get("outline_mapping", ""),
                "verification": {
                    "condition": nt.get("verification", {}).get("condition", ""),
                    "source": nt.get("verification", {}).get("source", "联播"),
                    "date": nt.get("verification", {}).get("date", ""),
                    "grace_period": nt.get("verification", {}).get("grace_period", ""),
                    "status": nt.get("verification", {}).get("status", "跟踪中"),
                },
                "category": nt.get("category", "产业政策与科技创新"),
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

        if sig.get("existing_theme_id"):
            tid = sig["existing_theme_id"]
            theme = next((t for t in themes if t["id"] == tid), None)
            if theme is None:
                continue
            upd = sig.get("update", {})
            for ev in upd.get("lifecycle_events", []):
                if ev.get("type") not in LIFECYCLE_TYPES:
                    ev["type"] = "update"
                theme.setdefault("lifecycle", []).append(ev)
            for k, v in upd.get("dimensions", {}).items():
                if k in DIM_KEYS:
                    theme["dimensions"][k] = v
            if upd.get("framework_evidence"):
                theme["framework_evidence"] = upd["framework_evidence"]
            if upd.get("investment_hypothesis"):
                theme["investment_hypothesis"] = upd["investment_hypothesis"]
            for k, v in upd.get("verification", {}).items():
                if k in VER_KEYS:
                    theme["verification"][k] = v
            stats["updated"] += 1

    write(TRACKING_JSON, json.dumps(doc, ensure_ascii=False, indent=2))
    return stats


def notify(report_path):
    notify_type = os.environ.get("NOTIFY_TYPE", "").strip().lower()
    webhook = os.environ.get("NOTIFY_WEBHOOK", "").strip()
    if not notify_type or not webhook:
        return

    md = read(report_path)
    m = re.search(r"## 今日要点(.*?)(?=\n## )", md, re.S)
    text = (m.group(1).strip() if m else md)[:1200]
    title = f"新闻联播政策信号日报 {os.path.basename(report_path)[:10]}"

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


def main():
    ap = argparse.ArgumentParser(description="每日自动化主流程")
    ap.add_argument("--date", help="分析日期 YYYY-MM-DD（默认昨日）")
    ap.add_argument("--mock", action="store_true", help="用内置样例响应测试流程，不调 API")
    args = ap.parse_args()

    target_date = args.date or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"[1/6] 日期：{target_date}")

    if args.mock:
        transcript = os.path.join(RAW_DIR, f"xwlb_{target_date.replace('-', '')}_text.md")
        os.makedirs(RAW_DIR, exist_ok=True)
        if not os.path.exists(transcript):
            write(transcript, "（mock 模式：无真实联播文本）\n")
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
                                         "date": "2026-12-31", "grace_period": "+30天", "status": "跟踪中"},
                        "category": "产业政策与科技创新",
                    },
                }
            ],
            "expiry_check": "mock：无检验点到期",
            "report_markdown": (
                f"# 新闻联播政策信号日报 | {target_date}\n\n"
                "## 今日要点\n\nmock 日报正文。\n\n"
                "## 读报指南\n\nmock 读报指南。\n\n"
                "## 信号详析\n\nmock 信号。\n\n"
                "## 信号跟踪表\n\nmock 跟踪表。\n\n"
                "## 风险提示\n\nmock 风险。\n"
            ),
        }
    else:
        print("[2/6] 抓取联播全文...")
        transcript = fetch_transcript(target_date)
        system, user = build_messages(transcript)
        print("[3/6] 调用 LLM 分析...")
        try:
            result = call_llm(system, user)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print("首次输出解析失败，重试一次...")
            result = call_llm(system, user, retry_error=str(e))

    if not result.get("report_markdown"):
        raise SystemExit("LLM 输出缺少 report_markdown，中止（未修改跟踪表）")

    print("[4/6] 更新跟踪表...")
    doc = json.loads(read(TRACKING_JSON))
    stats = apply_result(doc, result, target_date)
    print(f"       新增主题 {stats['new']} 个，更新主题 {stats['updated']} 个")

    print("[5/6] 生成日报 + 渲染...")
    report_path = os.path.join(REPORTS, f"{target_date}.md")
    write(report_path, result["report_markdown"])
    res = run([sys.executable, os.path.join(SCRIPTS, "render_tracking_table.py")], timeout=120)
    if res.returncode != 0:
        print(f"警告：渲染失败 {res.stderr[-400:]}")

    print("[6/6] 推送通知...")
    notify(report_path)
    print(f"完成：{report_path}")


if __name__ == "__main__":
    main()
