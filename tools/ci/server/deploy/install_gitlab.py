#!/usr/bin/env python3
# implements: FR-9, FR-15
"""
GitLab CE 离线安装（role=server/deploy，Python 3.8 标准库）。
从 config.ini [offline] deps_dir 取预置 .deb 离线安装。external_url 由 deploy.py 传入
（host + 探测锁定端口）。宪法 C-1：安装后须按 features.md 禁用对外遥测。
用法: python3 install_gitlab.py --external-url http://10.0.0.10:8929
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
    ap.add_argument("--external-url", required=True, help="GitLab 对外地址，如 http://10.0.0.10:8929")
    args = ap.parse_args()

    cfg = ci_config.load()
    deps_dir = ci_config.get_deps_dir(cfg)
    deb = ci_config.get(cfg, "offline", "gitlab_archive")
    gitlab_deps = ci_config.get(cfg, "offline", "gitlab_deps", "")
    pkg = os.path.join(deps_dir, deb)

    if not os.path.exists(pkg):
        raise SystemExit("找不到 GitLab 安装包：%s\n请按 docs/OFFLINE_DEPENDENCIES.md 预先放好。" % pkg)

    debs = []
    for d in [x.strip() for x in gitlab_deps.split(",") if x.strip()]:
        dp = os.path.join(deps_dir, d)
        if not os.path.exists(dp):
            raise SystemExit("找不到 GitLab 依赖包：%s（请离线放好）" % dp)
        debs.append(dp)
    debs.append(pkg)

    print("[1/3] 离线安装 GitLab CE: %s （EXTERNAL_URL=%s）" % (pkg, args.external_url))
    env = dict(os.environ, EXTERNAL_URL=args.external_url)
    try:
        subprocess.check_call(["apt-get", "install", "-y"] + debs, env=env)
    except subprocess.CalledProcessError:
        print("apt 安装失败，回退 dpkg 多包安装")
        subprocess.check_call(["dpkg", "-i"] + debs, env=env)

    print("[2/3] reconfigure")
    ci_config.run(["gitlab-ctl", "reconfigure"])
    print("[3/3] 状态检查")
    ci_config.run(["gitlab-ctl", "status"])

    print("\n完成。后续：")
    print("  1) 按 server/deploy/features.md 编辑 /etc/gitlab/gitlab.rb，禁用遥测、开所需特性")
    print("  2) gitlab-ctl reconfigure")
    print("  3) 浏览器打开 %s，建 Private 项目，拿 Runner Token" % args.external_url)


if __name__ == "__main__":
    main()
