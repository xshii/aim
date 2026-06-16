#!/usr/bin/env python3
# implements: FR-3, NFR-2
"""
GitLab Runner 离线安装 + 全自动注册（role=server/runner，Python 3.8 标准库）。
GitLab 16.0 起废弃、16.6 起移除 registration token；本仓 GitLab 为 19.x，故用新流程：
在服务器本地以 gitlab-rails 创建（或复用）项目 + 签发【项目级 authentication token(glrt-)】，
再 `gitlab-runner register --token <glrt->`。无需网页、无需 PAT。concurrent=1 保串行（D-003）。
用法:
  python3 setup_runner.py                 # 全自动：gitlab-rails 建项目+签 token+注册
  python3 setup_runner.py --token glrt-x  # 手动给 authentication token（fallback）
  python3 setup_runner.py --url http://h:p # 可选，默认从 config 推导 host:port
token 经 ci_config.run(redact=...) 脱敏，不落日志（C-1）。
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

# 在服务器本地以管理员特权创建/复用项目并签发项目级 runner token。
# 参数经 ENV 传入（避免 Ruby 字符串注入）；失败用 abort 输出可诊断的标记。
RUBY = r"""# encoding: utf-8
u = User.find_by_username('root') or abort('NO_ROOT_USER: 找不到 root 用户')
path = ENV['CI_PROJECT_PATH']
name = ENV['CI_PROJECT_NAME']
project = Project.find_by_full_path("#{u.username}/#{path}")
if project.nil?
  project = ::Projects::CreateService.new(u, {
    name: name, path: path, namespace_id: u.namespace_id,
    visibility_level: 0, initialize_with_readme: true
  }).execute
  abort("PROJECT_CREATE_FAILED: #{project.errors.full_messages.join('; ')}") unless project.persisted?
end
res = ::Ci::Runners::CreateRunnerService.new(
  user: u, type: :project_type, scope: project,
  params: { description: ENV['CI_RUNNER_NAME'], tag_list: [ENV['CI_RUNNER_TAG']],
            run_untagged: false, locked: true }
).execute
abort("RUNNER_CREATE_FAILED: #{res.errors.join('; ')}") unless res.success?
puts "RUNNER_TOKEN=#{res.payload[:runner].token}"
"""


def runner_registered():
    """config.toml 已有 [[runners]] 即视为已注册——幂等：避免二次运行重复注册（累积僵尸 runner）。"""
    try:
        with open("/etc/gitlab-runner/config.toml", encoding="utf-8") as f:
            return "[[runners]]" in f.read()
    except FileNotFoundError:
        return False


def auto_runner_token(cfg):
    """gitlab-rails 建项目 + 签发项目级 authentication token，返回 glrt- token。"""
    pname = ci_config.get(cfg, "gitlab", "project_name", "CI Eval")
    ppath = ci_config.get(cfg, "gitlab", "project_path", "ci-eval")
    env = dict(os.environ,
               CI_PROJECT_NAME=pname, CI_PROJECT_PATH=ppath,
               CI_RUNNER_NAME=ci_config.get(cfg, "runner", "runner_name", "sim-runner"),
               CI_RUNNER_TAG=ci_config.get(cfg, "runner", "runner_tag", "sim-license"))
    print("[auto] gitlab-rails 建项目/签项目级 runner token（GitLab 16+ 新流程，项目 root/%s）..." % ppath)
    p = subprocess.run(["gitlab-rails", "runner", "-"], input=RUBY.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    out = p.stdout.decode("utf-8", "replace")
    for line in out.splitlines():
        if line.startswith("RUNNER_TOKEN="):
            return line[len("RUNNER_TOKEN="):].strip()
    # 未拿到 token：输出不含敏感 token，可整体打印用于诊断（C-10 不编造、明确报告）。
    raise SystemExit(
        "自动签发 runner token 失败（gitlab-rails 输出如下）：\n%s\n"
        "回退手动：GitLab 网页 → 项目 → Settings → CI/CD → Runners → New project runner，"
        "拿 authentication token(glrt-)，再：python3 setup_runner.py --token <glrt->。" % out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="GitLab 地址（默认从 config 推导 host:port）")
    ap.add_argument("--token", help="Runner authentication token(glrt-)；省略则 gitlab-rails 全自动签发")
    args = ap.parse_args()

    cfg = ci_config.load()
    deps_dir = ci_config.get_deps_dir(cfg)
    deb = ci_config.get(cfg, "offline", "runner_archive")
    runner_deps = ci_config.get(cfg, "offline", "runner_deps", "")
    name = ci_config.get(cfg, "runner", "runner_name")
    tag = ci_config.get(cfg, "runner", "runner_tag")
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

    if not args.token and runner_registered():
        print("[2/4] config.toml 已注册 Runner，跳过注册（幂等，避免二次运行重复注册）。\n"
              "      重注册请先：gitlab-runner unregister --all-runners")
    else:
        url = (args.url or ci_config.external_url(cfg)).strip()
        token = args.token.strip() if args.token else auto_runner_token(cfg)
        print("[2/4] 注册 Runner（shell executor, tag=%s；GitLab 16+ authentication token）" % tag)
        # 新流程：tag/locked/run_untagged 已在 gitlab-rails 建 runner 时设定；register 只需 url+token+executor。
        ci_config.run(["gitlab-runner", "register", "--non-interactive",
                       "--url", url, "--token", token,
                       "--executor", "shell", "--description", name],
                      redact={"--token"})

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
