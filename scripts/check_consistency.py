#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""检查私有自动化库与公有库的共享源文件是否一致。

用于防止 prompt / 脚本 / 词典 / 测试在两侧分别修改后发生漂移。
以当前仓库为基准，逐一比较本仓库与另一份 checkout 中的共享文件哈希。
比较前先做行尾归一化（CRLF/LF 差异不算内容漂移），
避免两侧 checkout 的行尾策略不同导致误报（2026-08 review 修复）。

用法：
    python scripts/check_consistency.py --other ../public-src

返回码：
    0 = 全部一致；
    1 = 存在缺失或哈希不一致。
"""

import argparse
import hashlib
import os
import sys

SHARED_FILES = [
    "LICENSE",
    "PROMPT.md",
    "scripts/common.py",
    "scripts/fetch_xwlb.py",
    "scripts/run_daily.py",
    "scripts/render_tracking_table.py",
    "scripts/verify_external.py",
    "scripts/report_enhance.py",
    "reference/design.md",
    "reference/framework-dictionary.md",
    "reference/15fyp-outline-reference.md",
    "tests/test_apply.py",
    "tests/test_common.py",
    "tests/test_fetch.py",
    "tests/test_render.py",
    "tests/test_validate.py",
    "tests/test_verify.py",
    "tests/test_report_enhance.py",
]


def normalized_bytes(path):
    """读文件并统一为 \\n 行尾，供一致性比较。"""
    with open(path, "rb") as f:
        data = f.read()
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def norm_sha256(path):
    h = hashlib.sha256()
    h.update(normalized_bytes(path))
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="检查公私库共享源文件一致性")
    ap.add_argument("--other", required=True, help="另一个仓库的本地 checkout 路径")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    other = os.path.abspath(args.other)
    problems = []

    for rel in SHARED_FILES:
        left = os.path.join(root, rel)
        right = os.path.join(other, rel)
        if not os.path.exists(left):
            problems.append(f"当前仓库缺失：{rel}")
            continue
        if not os.path.exists(right):
            problems.append(f"对比仓库缺失：{rel}")
            continue
        left_hash = norm_sha256(left)
        right_hash = norm_sha256(right)
        if left_hash != right_hash:
            problems.append(f"不一致：{rel}")

    if problems:
        print("发现公私库漂移：")
        for p in problems:
            print(f"- {p}")
        return 1
    print(f"共享源文件一致：{len(SHARED_FILES)} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
