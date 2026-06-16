#!/usr/bin/env python3
# implements: FR-3, NFR-2
"""
GitLab Runner 离线安装 + 注册（role=server/runner，Python 3.8 标准库）。
从 config.ini 取 runner 标签/并发；从 deps_dir 取离线包。注册需 URL 与 Token（命令行传入，
C-10 不编造）。注册 token 经 ci_config.run(redact=...) 脱敏，不落日志（C-1）。
用法: python3 setup_runner.py --url <URL> --token <TOKEN>
"""
import argparse
import os
import subprocess
import sys

_R = os.path.dirname(os.path.abspath(__file__))
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
sys.path.insert(0, _R)
import ci_config  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="GitLab 注册地址")
    ap.add_argument("--token", required=True, help="Runner 注册 Token")
    args = ap.parse_args()

    cfg = ci_config.load()
    deps_dir = ci_config.get_deps_dir(cfg)
    deb = ci_config.get(cfg, "offline", "runner_archive")
    runner_deps = ci_config.get(cfg, "offline", "runner_deps", "")
    tag = ci_config.get(cfg, "runner", "runner_tag")
    name = ci_config.get(cfg, "runner", "runner_name")
    concurrent = ci_config.get(cfg, "runner", "concurrent", "1")
    pkg = os.path.join(deps_dir, deb)

    if not os.path.exists(pkg):
        raise SystemExit("找不到 Runner 安装包：%s（请离线放好）" % pkg)

    debs = []
    for d in [x.strip() for x in runner_deps.split(",") if x.strip()]:
        dp = os.path.join(deps_dir, d)
        if not os.path.exists(dp):
            raise SystemExit(
                "找不到 Runner 依赖包：%s\n新版 gitlab-runner 依赖 helper-images 等，离线须一并提供。\n"
                "查依赖：apt-cache depends gitlab-runner；下载：apt-get download <包名>。"
                "详见 docs/OFFLINE_DEPENDENCIES.md。" % dp)
        debs.append(dp)
    debs.append(pkg)

    print("[1/4] 离线安装 gitlab-runner（含依赖 %d 个）" % (len(debs) - 1))
    try:
        ci_config.run(["apt-get", "install", "-y"] + debs)
    except subprocess.CalledProcessError:
        print("apt 安装失败，回退 dpkg 多包安装")
        ci_config.run(["dpkg", "-i"] + debs)

    print("[2/4] 注册 Runner（shell executor, tag=%s）" % tag)
    ci_config.run(["gitlab-runner", "register", "--non-interactive",
                   "--url", args.url, "--registration-token", args.token,
                   "--executor", "shell", "--description", name,
                   "--tag-list", tag, "--run-untagged=false", "--locked=true"],
                  redact={"--registration-token"})

    print("[3/4] 设置 concurrent=%s（仿真串行）" % concurrent)
    cfg_path = "/etc/gitlab-runner/config.toml"
    with open(cfg_path, encoding="utf-8") as f:
        lines = f.readlines()
    out, replaced = [], False
    for ln in lines:
        if ln.strip().startswith("concurrent"):
            out.append("concurrent = %s\n" % concurrent)
            replaced = True
        else:
            out.append(ln)
    if not replaced:
        out.insert(0, "concurrent = %s\n" % concurrent)
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.writelines(out)

    print("[4/4] 重启 Runner")
    ci_config.run(["gitlab-runner", "restart"])
    ci_config.run(["gitlab-runner", "list"])
    print("完成：%s 已注册，concurrent=%s。" % (name, concurrent))


if __name__ == "__main__":
    main()
