#!/usr/bin/env python3
# implements: FR-6, FR-7
"""
聚合各验证 output/状态 + 质量门禁（role=server/metrics；合并 aggregate + quality_gate，M2）。
读 artifacts/checks/*.json → 写 reports/summary.json → 按 [gate] min_pass_ratio 判定。
0 个 check 视为失败（fail-closed，避免“无产物=全过”，B2）。
"""
import json
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
sys.path.insert(0, _R)
import ci_config  # noqa: E402

ROOT = os.environ.get("CI_PROJECT_DIR", ".")
CHECKS = os.path.join(ROOT, "artifacts", "checks")
REPORTS = os.path.join(ROOT, "reports")


def aggregate():
    summary = {"checks": [], "total": 0, "ok": 0}
    if os.path.isdir(CHECKS):
        for name in sorted(os.listdir(CHECKS)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(CHECKS, name), encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError) as e:
                print("[report] 跳过坏产物 %s：%s" % (name, e), file=sys.stderr)
                continue
            summary["checks"].append(data)
            summary["total"] += 1
            if data.get("status") == "ok":
                summary["ok"] += 1
    os.makedirs(REPORTS, exist_ok=True)
    with open(os.path.join(REPORTS, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary


def gate(summary):
    cfg = ci_config.load()
    threshold = float(ci_config.get(cfg, "gate", "min_pass_ratio", "1.0"))
    total, ok = summary["total"], summary["ok"]
    if total == 0:
        print("[report] 无任何 check 产物，门禁判失败（fail-closed）。", file=sys.stderr)
        sys.exit(1)
    ratio = ok / total
    print("[report] %d/%d 通过，通过率 %.2f，阈值 %.2f" % (ok, total, ratio, threshold))
    if ratio < threshold:
        print("[report] 低于阈值，阻断。", file=sys.stderr)
        sys.exit(1)
    print("[report] 通过。")


def main():
    gate(aggregate())


if __name__ == "__main__":
    main()
