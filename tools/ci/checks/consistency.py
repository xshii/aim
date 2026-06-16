#!/usr/bin/env python3
# implements: C-8
"""
一致性检查（CI 闸门）。
校验 spec 中的需求编号与 server/ local/ 代码里的 `implements: FR-N` 注释双向对齐。
不一致则非零退出，使流水线失败。宪法 C-8：不依赖自觉，机器强制对齐。

用法：python tools/ci/checks/consistency.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CI_ROOT = os.path.dirname(HERE)                 # tools/ci
SPEC = os.path.join(CI_ROOT, "docs", "01_spec.md")
CONSTITUTION = os.path.join(CI_ROOT, "docs", "00_constitution.md")
# 角色目录全扫（server/ local/ + 闸门自身）
SCAN_DIRS = [os.path.join(CI_ROOT, d) for d in ("server", "local", "checks")]
# 根目录共享脚本
EXTRA_SCAN = [os.path.join(CI_ROOT, f)
              for f in ("ci_config.py", "gen_quick_deploy.py")]

REQ_PATTERN = re.compile(r'\b((?:FR|NFR|C)-\d+)\b')
IMPL_PATTERN = re.compile(r'implements:\s*([A-Za-z0-9,\s\-]+)')


def read(path):
    # 只读文本源码，跳过二进制/缓存（如 .pyc）
    if path.endswith((".pyc", ".pyo", ".so", ".tar", ".gz", ".deb")):
        return ""
    if "__pycache__" in path:
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, UnicodeDecodeError):
        return ""


def collect_defined_requirements():
    """从 spec 与宪法收集已定义的需求编号。"""
    text = read(SPEC) + "\n" + read(CONSTITUTION)
    return set(REQ_PATTERN.findall(text))


def collect_implemented_references():
    """从 server/ local/ 与根目录脚本收集 implements: 引用的编号 -> 文件列表。"""
    refs = {}

    def scan_file(path):
        content = read(path)
        for m in IMPL_PATTERN.finditer(content):
            ids = re.findall(r'(?:FR|NFR|C)-\d+', m.group(1))
            for rid in ids:
                refs.setdefault(rid, []).append(
                    os.path.relpath(path, CI_ROOT))

    for base in SCAN_DIRS:
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            for name in files:
                scan_file(os.path.join(root, name))
    for path in EXTRA_SCAN:
        if os.path.exists(path):
            scan_file(path)
    return refs


def main():
    defined = collect_defined_requirements()
    refs = collect_implemented_references()

    errors = []
    warnings = []

    if not defined:
        errors.append("未在 spec/宪法 中找到任何需求编号，请检查文档路径。")

    # 检查 1：代码 implements 的编号必须存在于 spec/宪法
    for rid, files in refs.items():
        if rid not in defined:
            errors.append(
                f"代码引用了未定义/已失效的需求 {rid}（出现于：{', '.join(set(files))}）")

    # 检查 2（提示级）：定义了但无任何代码引用的需求（可能是僵尸需求或尚未实现）
    for rid in sorted(defined):
        if rid not in refs:
            warnings.append(f"需求 {rid} 暂无代码引用（若应已实现，请检查是否为僵尸需求）")

    print("=== 一致性检查 ===")
    print(f"已定义需求：{len(defined)}  代码引用编号：{len(refs)}")

    for w in warnings:
        print(f"[WARN] {w}")
    for e in errors:
        print(f"[ERROR] {e}")

    if errors:
        print(f"\n失败：{len(errors)} 个错误。请修复文档/代码对齐后重试（不要绕过本检查）。")
        sys.exit(1)

    print("\n通过：spec 与代码 implements 引用一致。")
    sys.exit(0)


if __name__ == "__main__":
    main()
