#!/usr/bin/env python3
# implements: FR-2, FR-3
"""端到端冒烟 demo：建临时 git 仓库（含 qsort.c + cases.txt）→ 入队 → worker 真实 checkout
→ 编译 + 逐用例比对 → 断言 passed。演示「代码仓 push → 调度 → 评测」完整链路（webhook 之后那段）。
用法：python3 smoke_scheduler.py"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import db      # noqa: E402
import worker  # noqa: E402

DEMO = os.path.join(os.path.dirname(HERE), "demo", "qsort")


def eval_qsort(ws, log):
    """demo 评测 pipeline：编译 ws/qsort.c → 逐 cases.txt 比对。返回 0=全过（passed）。"""
    binp = os.path.join(ws, "qsort.bin")
    if subprocess.call(["cc", "-O2", "-o", binp, os.path.join(ws, "qsort.c")],
                       stdout=log, stderr=log) != 0:
        return 1
    with open(os.path.join(ws, "cases.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            inp, expected = line.split("|")
            r = subprocess.run([binp] + inp.split(), stdout=subprocess.PIPE)
            if r.stdout.decode().strip() != expected.strip():
                log.write("case %s -> got '%s' expect '%s'\n"
                          % (inp.strip(), r.stdout.decode().strip(), expected.strip()))
                return 1
    return 0


def main():
    tmp = tempfile.mkdtemp()
    origin = os.path.join(tmp, "origin")
    os.makedirs(origin)
    for fn in ("qsort.c", "cases.txt"):
        with open(os.path.join(DEMO, fn), encoding="utf-8") as r, \
                open(os.path.join(origin, fn), "w", encoding="utf-8") as w:
            w.write(r.read())
    for c in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "."], ["commit", "-q", "-m", "demo"]):
        subprocess.check_call(["git"] + c, cwd=origin,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    path = os.path.join(tmp, "ci.db")
    db.init(path)
    tid = db.enqueue(path, origin, "HEAD")        # 模拟 webhook 入队
    print("[demo] 入队 task %d  repo=%s" % (tid, origin))
    cfg = worker.Cfg(db_path=path, workspace_dir=os.path.join(tmp, "ws"),
                     log_dir=os.path.join(tmp, "log"), git_auth="ssh", ssh_key="", http_token="")
    worker.run_one(cfg, run_pipeline=eval_qsort)   # 真实 checkout + 评测

    row = db.list_tasks(path)[0]
    print("[demo] 任务终态: %s  exit=%s  log=%s" % (row["state"], row["exit_code"], row["log_path"]))
    sys.exit(0 if row["state"] == "passed" else 1)


if __name__ == "__main__":
    main()
