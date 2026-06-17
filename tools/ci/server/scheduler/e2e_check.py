#!/usr/bin/env python3
# implements: FR-14, FR-21
"""端到端集成自检（本机 / 部署后均可跑，无 docker、无网络）。
起真实 webhook HTTP server → POST 内部开源 push payload → 入队 → 幂等重发 → 无 token 拒绝 →
worker 真实 git checkout 本地仓 + 编译比对评测 → GET 查状态/日志 → MCP 查。全链路真实组件。
内网代码仓用本地临时 git repo 模拟（git clone 本地路径）。用法：python3 e2e_check.py（全过退出 0）。"""
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
_R = HERE
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
DEMO = os.path.join(os.path.dirname(HERE), "demo", "qsort")


def _git(args, cwd):
    subprocess.check_call(["git"] + args, cwd=cwd,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def eval_qsort(ws, log):
    """demo 评测 pipeline：编译 ws/qsort.c → 逐 cases.txt 比对。返回 0=全过。"""
    binp = os.path.join(ws, "qsort.bin")
    if subprocess.call(["cc", "-O2", "-o", binp, os.path.join(ws, "qsort.c")],
                       stdout=log, stderr=log) != 0:
        return 1
    with open(os.path.join(ws, "cases.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            inp, exp = line.split("|")
            r = subprocess.run([binp] + inp.split(), stdout=subprocess.PIPE)
            if r.stdout.decode().strip() != exp.strip():
                return 1
    return 0


def main():
    tmp = tempfile.mkdtemp()
    os.environ["WEBHOOK_SECRET"] = "e2e-secret"
    os.environ["CI_DB_PATH"] = os.path.join(tmp, "ci.db")
    sys.path[:0] = [_R, os.path.join(_R, "server/scheduler"),
                    os.path.join(_R, "server/webhook"), os.path.join(_R, "local/mcp")]
    import ci_control_server
    import db
    import receiver
    import worker
    db.init(os.environ["CI_DB_PATH"])

    # 用本地 git repo 模拟内网代码仓
    origin = os.path.join(tmp, "origin")
    os.makedirs(origin)
    for fn in ("qsort.c", "cases.txt"):
        with open(os.path.join(DEMO, fn), encoding="utf-8") as r, \
                open(os.path.join(origin, fn), "w", encoding="utf-8") as w:
            w.write(r.read())
    _git(["init", "-q"], origin)
    _git(["config", "user.email", "t@t"], origin)
    _git(["config", "user.name", "t"], origin)
    _git(["add", "."], origin)
    _git(["commit", "-q", "-m", "demo"], origin)
    sha = subprocess.check_output(["git", "-C", origin, "rev-parse", "HEAD"]).decode().strip()

    httpd = receiver.build_server("127.0.0.1", 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def req(method, path, body=None, auth=True):
        h = {"X-Devcloud-Token": "e2e-secret"} if auth else {}
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        return r.status, r.read().decode()

    payload = json.dumps({"object_kind": "push", "checkout_sha": sha, "ref": "refs/heads/master",
                          "project": {"git_ssh_url": origin}})
    checks = []
    s, _ = req("POST", "/", payload)
    checks.append(("webhook 入队(202)", s == 202))
    s, b = req("POST", "/", payload)
    checks.append(("幂等重发(200 duplicate)", s == 200 and "duplicate" in b))
    s, _ = req("POST", "/", payload, auth=False)
    checks.append(("无 token 拒绝(401)", s == 401))

    cfg = worker.Cfg(os.environ["CI_DB_PATH"], os.path.join(tmp, "ws"),
                     os.path.join(tmp, "log"), "ssh", "", "")
    worker.run_one(cfg, run_pipeline=eval_qsort)
    checks.append(("worker checkout+评测(passed)",
                   db.get(os.environ["CI_DB_PATH"], 1)["state"] == "passed"))

    s, b = req("GET", "/tasks/1", auth=False)
    checks.append(("GET 状态网页(200)", s == 200 and "passed" in b))
    s, b = req("GET", "/tasks/1/log", auth=False)
    checks.append(("GET 日志(200)", s == 200 and len(b) > 0))
    mcp = ci_control_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": "get_task_status",
                                               "arguments": {"task_id": 1}}})
    checks.append(("MCP 查询(passed)", "passed" in mcp["result"]["content"][0]["text"]))
    checks.append(("幂等只 1 任务", len(db.list_tasks(os.environ["CI_DB_PATH"])) == 1))

    httpd.shutdown()
    ok = all(p for _, p in checks)
    for name, passed in checks:
        print("  [%s] %s" % ("PASS" if passed else "FAIL", name))
    print("=== 端到端%s ===" % ("通过" if ok else "未通过"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
