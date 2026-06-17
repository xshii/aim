#!/usr/bin/env python3
# implements: FR-2, FR-3, NFR-2
"""单 worker 守护：claim→checkout→harness→报告→finish。concurrency=1 即仿真串行。
经 systemd 守护；启动 reset_stale 清悬挂。run_one 注入 checkout/pipeline 便于测试。"""
import collections
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_R = HERE
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
sys.path.insert(0, _R)
import ci_config          # noqa: E402
import checkout as _checkout  # noqa: E402
import constants as C     # noqa: E402
import db                 # noqa: E402

CI_ROOT = _R
Cfg = collections.namedtuple(
    "Cfg", "db_path workspace_dir log_dir git_auth ssh_key http_token")


def load_cfg():
    c = ci_config.load()
    g = lambda k, d="": ci_config.get(c, "scheduler", k, d)  # noqa: E731
    base = os.path.dirname(os.path.dirname(HERE))  # 部署目录（server/ 的上层）
    return Cfg(
        db_path=ci_config.expand(g("db_path", os.path.join(base, "var/ci.db"))),
        workspace_dir=ci_config.expand(g("workspace_dir", os.path.join(base, "var/ws"))),
        log_dir=ci_config.expand(g("log_dir", os.path.join(base, "var/log"))),
        git_auth=g("git_auth", "ssh"),
        ssh_key=ci_config.secret("CI_SSH_KEY", c, "scheduler", "ssh_key"),
        http_token=ci_config.secret("CI_HTTP_TOKEN", c, "scheduler", "http_token"))


def run_pipeline(workspace, log):
    """在 workspace 顺序跑评测 harness；任一非零即失败。返回退出码。"""
    import subprocess
    stages = [["python3", os.path.join(CI_ROOT, "server/harness/check.py"), s]
              for s in ("run", "sim", "compare", "quality")]
    stages.append(["python3", os.path.join(CI_ROOT, "server/metrics/report.py")])
    for cmd in stages:
        rc = subprocess.call(cmd, cwd=workspace, stdout=log, stderr=log)
        if rc != 0:
            return rc
    return 0


def run_one(cfg, do_checkout=_checkout.checkout, run_pipeline=run_pipeline):
    """处理一个任务；无任务返回 False。"""
    row = db.claim(cfg.db_path)
    if not row:
        return False
    tid = row["id"]
    os.makedirs(cfg.log_dir, exist_ok=True)
    log_path = os.path.join(cfg.log_dir, "%d.log" % tid)
    ws = os.path.join(cfg.workspace_dir, str(tid))
    with open(log_path, "w") as log:
        try:
            do_checkout(row["repo"], row["ref"], ws, git_auth=cfg.git_auth,
                        ssh_key=cfg.ssh_key, http_token=cfg.http_token, log=log)
            rc = run_pipeline(ws, log)
            db.finish(cfg.db_path, tid, C.ST_PASSED if rc == 0 else C.ST_FAILED, rc, log_path)
        except Exception as e:  # noqa: BLE001
            log.write("\n[worker] 任务失败：%s\n" % e)
            db.finish(cfg.db_path, tid, C.ST_ERROR, None, log_path)
    return True


def main():
    cfg = load_cfg()
    db.init(cfg.db_path)
    n = db.reset_stale(cfg.db_path)
    if n:
        print("[worker] 重置 %d 个悬挂任务为 error" % n)
    poll = float(ci_config.get(ci_config.load(), "scheduler", "poll_interval", "2"))
    print("[worker] 启动，db=%s 串行轮询 %ss" % (cfg.db_path, poll))
    while True:
        if not run_one(cfg):
            time.sleep(poll)


if __name__ == "__main__":
    main()
