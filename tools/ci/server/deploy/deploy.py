#!/usr/bin/env python3
# implements: FR-9, FR-11
"""本地一键部署（role=server/deploy，python3 标准库）。装调度器：自检 → 初始化 → systemd 服务。
需 root（sudo python3 deploy.py all）。GitLab 路线已弃用（D-013）。
  sudo python3 deploy.py all       # check → init(sqlite/目录) → service(webhook+worker)
或分步：check / init / service
宪法：遇缺失即停（C-10）；参数来自 config.ini（C-7）。"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))            # server/deploy
_R = HERE
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
CI_ROOT = _R
sys.path.insert(0, _R)
import ci_config  # noqa: E402

ALLOWED_PORTS = set(range(80, 91)) | {443} | set(range(8080, 8091))


def check_env():
    print("=== 环境自检 ===")
    ok = True
    print("python3:", sys.version.split()[0])
    if sys.version_info < (3, 8):
        print("[WARN] 期望 python3 >= 3.8")
    if os.geteuid() != 0:
        print("[ERROR] 需 root：sudo python3 deploy.py <action>（或 sudo -i 切 root）。")
        ok = False
    for tool in ("git", "systemctl"):
        found = subprocess.run(["which", tool], stdout=subprocess.PIPE).returncode == 0
        print("命令 %s:" % tool, "有" if found else "缺失")
        ok = ok and found
    cfg = ci_config.load()
    listen = ci_config.get(cfg, "webhook", "listen", "0.0.0.0:8080")
    try:
        port = int(listen.rsplit(":", 1)[-1])
    except ValueError:
        port = -1
    in_range = port in ALLOWED_PORTS
    print("webhook 端口 %s:" % port,
          "允许" if in_range else "[超范围! 仅 80-90 / 443 / 8080-8090]")
    ok = ok and in_range
    print("=== 自检%s ===" % ("通过" if ok else "未通过"))
    return ok


def _sched(cfg, key, default):
    return ci_config.expand(ci_config.get(cfg, "scheduler", key, default))


def step_init():
    cfg = ci_config.load()
    base = os.path.dirname(HERE)  # server/ 上层 = 部署目录
    db_path = _sched(cfg, "db_path", os.path.join(base, "var/ci.db"))
    ws = _sched(cfg, "workspace_dir", os.path.join(base, "var/ws"))
    log = _sched(cfg, "log_dir", os.path.join(base, "var/log"))
    for d in (os.path.dirname(db_path), ws, log):
        os.makedirs(d, exist_ok=True)
        print("[init] 目录就绪:", d)
    sys.path.insert(0, os.path.join(CI_ROOT, "server", "scheduler"))
    import db
    db.init(db_path)
    print("[init] sqlite 初始化:", db_path)


def step_service():
    src = os.path.join(HERE, "systemd")
    for unit in ("ci-webhook.service", "ci-worker.service"):
        with open(os.path.join(src, unit), encoding="utf-8") as f:
            content = f.read().replace("@@CI_ROOT@@", CI_ROOT)
        dst = "/etc/systemd/system/" + unit
        with open(dst, "w", encoding="utf-8") as f:
            f.write(content)
        print("[service] 写入", dst)
    ci_config.run(["systemctl", "daemon-reload"])
    for unit in ("ci-webhook", "ci-worker"):
        ci_config.run(["systemctl", "enable", "--now", unit])
    ci_config.run(["systemctl", "--no-pager", "status", "ci-webhook", "ci-worker"],
                  check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["check", "init", "service", "all"])
    args = ap.parse_args()
    if args.action == "check":
        sys.exit(0 if check_env() else 1)
    if not check_env():
        print("自检未通过，停止（勿绕过）。", file=sys.stderr)
        sys.exit(1)
    if args.action in ("init", "all"):
        step_init()
    if args.action in ("service", "all"):
        step_service()
    print("\n完成。验证：systemctl status ci-webhook ci-worker；浏览器开 http://<host>:<端口>/ 看任务。")


if __name__ == "__main__":
    main()
