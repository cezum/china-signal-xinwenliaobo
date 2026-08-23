#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""共享工具：原子写入、损坏恢复、统计重算（仅使用 Python 标准库）。

被 fetch_xwlb.py / run_daily.py / render_tracking_table.py 共用。

修复背景（代码审查 2026-08-16）：
- P1-3 关键文件非原子写入：write_atomic() 用“同目录临时文件 + os.replace”
  原子替换，进程中断不会留下半截文件；可选写入前备份 .bak。
- P1-3 读取损坏恢复：read_json() 检测 JSON 损坏后自动回退 .bak。
- P1-1 统计失真：recompute_stats() 基于 themes 实时重算，渲染与更新共用。
"""

import json
import os
import tempfile

# 维度字段 → stats 中对应分布键
DIMENSION_FIELDS = (
    ("level", "by_level"),
    ("novelty", "by_novelty"),
    ("specificity", "by_specificity"),
    ("policy_window", "by_policy_window"),
    ("verification_window", "by_verification_window"),
    ("narrative_framework", "by_narrative_framework"),
)

UNLABELED = "未标注"

# 主表（极简跟踪表 / 日报摘要）只展示的"活跃"状态；
# 已验证 / 投资线索就绪 / 信号衰减 / 归档 属于已结项，移入副区（完整表保留全量）。
MAIN_STATUSES = {"跟踪中", "延迟验证", "待复核"}


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_atomic(path, text, backup=False):
    """原子写入：先写同目录临时文件，再 os.replace() 替换。

    进程在写入途中中断时，目标文件保持旧内容或新内容二选一，
    不会出现半截文件。backup=True 时先把手头的旧文件改名 .bak。
    """
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        if backup and os.path.exists(path):
            try:
                os.replace(path, path + ".bak")
            except OSError as e:
                print(f"[warn] 备份失败（继续写入）：{e}")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def read_json(path):
    """读取 JSON；文件损坏时自动尝试从 .bak 恢复。"""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        bak = path + ".bak"
        if os.path.exists(bak):
            print(f"[recover] {os.path.basename(path)} 损坏（{e}），已从 .bak 恢复")
            with open(bak, "r", encoding="utf-8") as f:
                return json.load(f)
        raise


def write_json(path, obj, backup=False):
    """原子写入 JSON（末尾带换行）。"""
    write_atomic(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                 backup=backup)


def recompute_stats(doc):
    """基于 doc["themes"] 实时重算 stats，回写 doc 并返回。

    更新主题后必须调用，保证日报/跟踪表的分布统计与主题一致；
    渲染脚本也应在渲染前调用，忽略可能过期的旧统计。
    """
    themes = doc["themes"]
    total = len(themes)
    stats = {key: {} for _, key in DIMENSION_FIELDS}
    for t in themes:
        dims = t.get("dimensions")
        dims = dims if isinstance(dims, dict) else {}
        for field, key in DIMENSION_FIELDS:
            value = str(dims.get(field, UNLABELED))
            stats[key][value] = stats[key].get(value, 0) + 1
    theme_ids = {t["id"] for t in themes}
    stats["by_category"] = {}
    for cat in doc.get("categories", []):
        ids = [i for i in cat.get("theme_ids", []) if i in theme_ids]
        stats["by_category"][cat["name"]] = len(ids)
    stats["total"] = total
    doc["stats"] = stats
    return stats
