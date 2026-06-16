#!/usr/bin/env python3
# implements: FR-16, FR-17, FR-18
"""
远端首次部署 bootstrap（role=local/admin：从执行机经 SSH/SCP，Python 3.8 标准库）。
服务器本地部署（D-008）的首次补充（D-010）：把全量 tools/ci 代码 + 离线依赖推到目标机，
再经 SSH 远程执行 server/deploy/deploy.py。日常触发仍走 HTTP（FR-14），不依赖常驻隧道。
ssh 私钥留 ~/.ssh，勿入仓（C-1, D-009）。

在执行机上：
  python3 deploy_remote.py check   # admin 连通性自检（SSH/python3，+GitLab 若给 env）
  python3 deploy_remote.py fetch   # fetch=auto 时经代理下载依赖到本地 deps_dir
  python3 deploy_remote.py push    # scp 代码 + offline/*.deb 到远端 dest
  python3 deploy_remote.py all     # check → fetch → push → 远端 server/deploy/deploy.py all
缺地址/凭证即停（C-10）。
"""
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


def step_fetch(cfg):
    mode = (ci_config.get(cfg, "fetch", "mode", "manual").strip()
            if cfg.has_section("fetch") else "manual")
    if mode != "auto":
        print("=== fetch=manual：依赖请手动放入 deps_dir（FR-9），跳过下载 ===")
        return
    import urllib.request
    deps_dir = ci_config.get_deps_dir(cfg)
    os.makedirs(deps_dir, exist_ok=True)
    prox = ci_config.proxies(cfg)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(prox))
    items = [(ci_config.get(cfg, "offline", "gitlab_archive"),
              ci_config.get(cfg, "fetch", "gitlab_url", "")),
             (ci_config.get(cfg, "offline", "runner_archive"),
              ci_config.get(cfg, "fetch", "runner_url", ""))]
    rd = ci_config.get(cfg, "offline", "runner_deps", "")
    if rd.strip():
        items.append((rd.split(",")[0].strip(),
                      ci_config.get(cfg, "fetch", "runner_deps_url", "")))
    print("=== fetch=auto：经代理 %s 下载到 %s ===" % (list(prox) or "无", deps_dir))
    for fname, url in items:
        if not url.strip():
            raise SystemExit("[fetch] %s 缺下载 URL（config [fetch]），勿编造（C-10）。" % fname)
        dest = os.path.join(deps_dir, fname)
        if os.path.exists(dest):
            print("[fetch] 已存在，跳过：%s" % fname)
            continue
        print("[fetch] 下载 %s <- %s" % (fname, url))
        with opener.open(url, timeout=300) as r, open(dest, "wb") as f:
            f.write(r.read())
    print("[fetch] 完成。")


def step_push(cfg):
    user, host, port, dest, opts = _remote(cfg)
    target = ("%s@%s" % (user, host)) if user else host
    rdeps = dest.rstrip("/") + "/offline"
    ci_config.run(connectivity.ssh_cmd(user, host, port, opts) + ["mkdir", "-p", dest, rdeps])
    scp = ["scp", "-r", "-P", str(port)] + (opts.split() if opts.strip() else [])
    # 1) 推 CI 代码（排除离线包目录、缓存、本地敏感配置）
    code = [p for p in glob.glob(os.path.join(CI_ROOT, "*"))
            if os.path.basename(p) not in ("offline", "__pycache__", "config.local.ini")]
    ci_config.run(scp + code + ["%s:%s/" % (target, dest)])
    # 2) 推离线依赖
    deps_dir = ci_config.get_deps_dir(cfg)
    debs = sorted(glob.glob(os.path.join(deps_dir, "*.deb"))) if os.path.isdir(deps_dir) else []
    if not debs:
        raise SystemExit("本地 deps_dir 无 .deb：%s（先 fetch 或手动放好，C-10）。" % deps_dir)
    ci_config.run(scp + debs + ["%s:%s/" % (target, rdeps)])
    print("[push] 代码与依赖已推送到 %s:%s" % (target, dest))


def step_remote_deploy(cfg):
    user, host, port, dest, opts = _remote(cfg)
    # 非 root 用户用 sudo 提权运行整个 deploy.py（脚本内部即 root，特权命令/环境变量/getpass 全正常）。
    # tty=True：让 sudo 密码与 GitLab root 密码都能在本地终端交互输入并传至远端。
    prefix = "" if user == "root" else "sudo "
    cmd = connectivity.ssh_cmd(user, host, port, opts, tty=True) + \
        ["cd %s && %spython3 server/deploy/deploy.py all" % (dest, prefix)]
    ci_config.run(cmd)
    print("[remote] 已在 %s 执行 deploy.py all（含全自动 Runner 注册）。" % host)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["check", "fetch", "push", "all"])
    args = ap.parse_args()
    cfg = ci_config.load()
    if args.action == "check":
        step_check()
    elif args.action == "fetch":
        step_fetch(cfg)
    elif args.action == "push":
        step_push(cfg)
    else:
        step_check()
        step_fetch(cfg)
        step_push(cfg)
        step_remote_deploy(cfg)
        print("\n远端 bootstrap 完成。")


if __name__ == "__main__":
    main()
