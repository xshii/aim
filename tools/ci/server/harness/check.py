#!/usr/bin/env python3
# implements: FR-2, FR-3, FR-6
"""
统一验证占位（role=server/harness；合并 run/sim/compare/quality 四类，M1）。
用法: python3 check.py <run|sim|compare|quality>
对预生成代码做对应验证，写 artifacts/checks/<kind>.json 供 metrics/report.py 聚合。
运行型由 .gitlab-ci.yml 经 limited_run 包裹（NFR-3）；真实逻辑后续按 kind 填充。
"""
import json
import os
import sys

KINDS = {
    "run": "运行型（经 limited_run 超时+资源限制执行）",
    "sim": "仿真型（喂仿真软件，严格串行 D-003）",
    "compare": "比对型（与参考答案比对，不实际运行）",
    "quality": "质量检查型（静态：风格/复杂度/规则）",
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in KINDS:
        print("用法: check.py <%s>" % "|".join(KINDS), file=sys.stderr)
        sys.exit(2)
    kind = sys.argv[1]
    out_dir = os.path.join(os.environ.get("CI_PROJECT_DIR", "."), "artifacts", "checks")
    os.makedirs(out_dir, exist_ok=True)
    result = {"check": kind, "status": "ok", "output": "placeholder"}
    with open(os.path.join(out_dir, kind + ".json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print("[check:%s] placeholder ok — %s" % (kind, KINDS[kind]))


if __name__ == "__main__":
    main()
