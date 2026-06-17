#!/usr/bin/env python3
# implements: FR-16, FR-18
"""远端首次部署 bootstrap（role=local/admin：从执行机经 SSH/SCP，python3 标准库）。CI 框架=Jenkins（.deb）。
把全量 tools/ci 代码（含 offline/ 下的 .deb+插件）推到目标机，再经 SSH 远程执行
server/deploy/deploy.py all（非 root 自动 sudo）。ssh 私钥留 ~/.ssh（C-1, D-009）。

在执行机上：
  python3 deploy_remote.py check   # admin 连通性自检（SSH/远端 python3/管理员权限）
  python3 deploy_remote.py push    # scp 代码 + offline/ 到远端
  python3 deploy_remote.py all     # check → push → 远端 deploy.py all
缺地址即停（C-10）。离线件先在有网机跑 server/deploy/fetch_offline.py 产出到 tools/ci/offline/。"""
import argparse
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))            # local/admin
sys.path.insert(0, HERE)                                     # 同目录 connectivity
_R = HERE
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
CI_ROOT = _R
sys.path.insert(0, CI_ROOT)
import ci_config       # noqa: E402
import connectivity    # noqa: E402


def _remote(cfg):
    if not cfg.has_section("remote") or not ci_config.get(cfg, "remote", "host", "").strip():
        raise SystemExit("未配置 [remote] host：远端部署需目标机地址（勿编造，C-10）。")
    return (ci_config.get(cfg, "remote", "user", "root"),
            ci_config.get(cfg, "remote", "host"),
            ci_config.get(cfg, "remote", "port", "22"),
            ci_config.get(cfg, "remote", "dest", "/opt/ci"),
            ci_config.get(cfg, "remote", "ssh_opts", ""))


def step_check():
    print("=== admin 连通性自检 ===")
    if subprocess.call(["python3", os.path.join(HERE, "connectivity.py")]) != 0:
        raise SystemExit("连通性未通过，停止（勿绕过，C-10）。")


def step_push(cfg):
    user, host, port, dest, opts = _remote(cfg)
    target = ("%s@%s" % (user, host)) if user else host
    ci_config.run(connectivity.ssh_cmd(user, host, port, opts) + ["mkdir", "-p", dest])
    scp = ["scp", "-r", "-P", str(port)] + (opts.split() if opts.strip() else [])
    # 推全量 CI 代码 + offline/ 离线件（.deb/插件随 offline/ 目录一起；排除缓存与本地敏感配置）
    code = [p for p in glob.glob(os.path.join(CI_ROOT, "*"))
            if os.path.basename(p) not in ("__pycache__", "config.local.ini")]
    ci_config.run(scp + code + ["%s:%s/" % (target, dest)])
    print("[push] 代码 + offline/ 已推送到 %s:%s" % (target, dest))
    print("[push] 离线 .deb 落地 %s/offline（确认 config.ini [offline] deps_dir 与此一致）" % dest)


def step_remote_deploy(cfg):
    user, host, port, dest, opts = _remote(cfg)
    # 非 root 用户用 sudo 提权运行整个 deploy.py（脚本内部即 root，特权命令/getpass 全正常）。
    # tty=True：让 sudo 密码能在本地终端交互输入并传至远端。
    prefix = "" if user == "root" else "sudo "
    cmd = connectivity.ssh_cmd(user, host, port, opts, tty=True) + \
        ["cd %s && %spython3 server/deploy/deploy.py all" % (dest, prefix)]
    ci_config.run(cmd)
    print("[remote] 已在 %s 执行 deploy.py all（Jenkins：apt 装 .deb + JCasC + systemd）。" % host)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["check", "push", "all"])
    args = ap.parse_args()
    cfg = ci_config.load()
    if args.action == "check":
        step_check()
    elif args.action == "push":
        step_push(cfg)
    else:
        step_check()
        step_push(cfg)
        step_remote_deploy(cfg)
        print("\n远端 bootstrap 完成。")


if __name__ == "__main__":
    main()
