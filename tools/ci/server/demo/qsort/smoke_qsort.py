#!/usr/bin/env python3
# implements: FR-13
"""
qsort 冒烟验证（role=server/demo，Python 3.8 标准库）。
对预生成的 qsort.c 端到端验证：编译 → 逐用例经 limited_run 限制运行 → 与期望比对 → 产出状态。
结果写 artifacts/checks/qsort.json。编译产物入 artifacts（不污染源码树）。
用法（CI 中或本地）: python3 smoke_qsort.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_R = HERE
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
CI_ROOT = _R
LIMITED = os.path.join(CI_ROOT, "server", "harness", "limited_run.py")
SRC = os.path.join(HERE, "qsort.c")
CASES = os.path.join(HERE, "cases.txt")
OUT_DIR = os.path.join(os.environ.get("CI_PROJECT_DIR", CI_ROOT), "artifacts", "checks")


def load_cases():
    cases = []
    with open(CASES, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            inp, expected = line.split("|")
            cases.append((inp.strip().split(), expected.strip()))
    return cases


def _write(result):
    with open(os.path.join(OUT_DIR, "qsort.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    result = {"check": "qsort_smoke", "status": "fail", "steps": [], "passed": 0, "total": 0}

    binp = os.path.join(OUT_DIR, "qsort.bin")   # 产物入 artifacts，不污染源码树（B5）
    try:
        subprocess.check_call(["cc", "-O2", "-o", binp, SRC])
        result["steps"].append("compile: ok")
    except Exception as e:  # noqa
        result["steps"].append("compile: FAIL (%s)" % e)
        _write(result)
        print("[qsort_smoke] 编译失败")
        sys.exit(1)

    cases = load_cases()
    result["total"] = len(cases)
    for args, expected in cases:
        try:
            # 经 limited_run 限制运行（墙钟由 config [limits] wall_sec 控制）；外层 180s 仅作兜底
            r = subprocess.run(["python3", LIMITED, HERE, binp] + args,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
            got = r.stdout.decode().strip()
            ok = (got == expected)
            result["steps"].append("case %s -> got '%s' expect '%s' : %s"
                                   % (" ".join(args), got, expected, "OK" if ok else "FAIL"))
            if ok:
                result["passed"] += 1
        except Exception as e:  # noqa
            result["steps"].append("case %s : ERROR %s" % (" ".join(args), e))

    result["status"] = "ok" if result["passed"] == result["total"] else "fail"
    _write(result)
    print("[qsort_smoke] %d/%d 用例通过，status=%s"
          % (result["passed"], result["total"], result["status"]))
    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
