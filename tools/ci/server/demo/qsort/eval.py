#!/usr/bin/env python3
# implements: FR-13, FR-6, FR-7
"""qsort 评测 demo：两个 CI 项——功能(正确性) + 性能(耗时)。
- 功能：编译 qsort.c → 跑 cases.txt 用例比对期望输出。
- 性能：多规模随机数组跑，测 wall 耗时 + 校验结果仍正确（与 python sorted 比对）。
输出可读摘要 + 结构化 json（CI_PROJECT_DIR/qsort_eval.json）。可作 worker 的评测 pipeline。
用法：python3 eval.py [代码目录，默认本目录]"""
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def _run(binp, nums):
    r = subprocess.run([binp] + [str(x) for x in nums], stdout=subprocess.PIPE)
    return r.stdout.decode().strip()


def functional(binp, srcdir):
    cases = []
    with open(os.path.join(srcdir, "cases.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            inp, exp = line.split("|")
            cases.append((inp.split(), exp.strip()))
    detail, passed = [], 0
    for args, exp in cases:
        got = _run(binp, args)
        ok = got == exp
        passed += ok
        detail.append({"input": " ".join(args), "expect": exp, "got": got, "pass": ok})
    return {"check": "functional", "passed": passed, "total": len(cases),
            "status": "pass" if passed == len(cases) else "fail", "cases": detail}


def performance(binp):
    random.seed(42)
    detail, status = [], "pass"
    for n in (1000, 5000, 20000):
        arr = [random.randint(-10 ** 6, 10 ** 6) for _ in range(n)]
        t0 = time.perf_counter()
        got = _run(binp, arr)
        ms = (time.perf_counter() - t0) * 1000.0
        correct = got == " ".join(str(x) for x in sorted(arr))
        if not correct:
            status = "fail"
        detail.append({"size": n, "ms": round(ms, 1), "correct": correct})
    return {"check": "performance", "status": status, "samples": detail}


def main():
    srcdir = sys.argv[1] if len(sys.argv) > 1 else HERE
    binp = os.path.join(srcdir, "qsort.bin")
    if subprocess.call(["cc", "-O2", "-o", binp, os.path.join(srcdir, "qsort.c")]) != 0:
        print("[qsort_eval] 编译失败")
        sys.exit(1)

    func = functional(binp, srcdir)
    perf = performance(binp)
    overall = "pass" if func["status"] == "pass" and perf["status"] == "pass" else "fail"
    report = {"project": "qsort", "status": overall, "checks": [func, perf]}

    print("==================== qsort CI 评测 ====================")
    print("【功能 functional】%s  —  %d/%d 用例通过"
          % (func["status"].upper(), func["passed"], func["total"]))
    for c in func["cases"]:
        print("   %s  %-22s -> %s" % ("✓" if c["pass"] else "✗", c["input"], c["got"]))
    print("【性能 performance】%s" % perf["status"].upper())
    print("   %-8s %10s   %s" % ("规模", "耗时(ms)", "结果正确"))
    for s in perf["samples"]:
        print("   n=%-6d %9.1f   %s" % (s["size"], s["ms"], "是" if s["correct"] else "否"))
    print("------------------------------------------------------")
    print("总状态: %s" % overall.upper())

    out = os.path.join(os.environ.get("CI_PROJECT_DIR", srcdir), "qsort_eval.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    sys.exit(0 if overall == "pass" else 1)


if __name__ == "__main__":
    main()
