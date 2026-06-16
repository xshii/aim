#!/usr/bin/env python3
# implements: FR-9, FR-11, FR-15, NFR-2
"""
本地一键部署（role=server/deploy：代码到位后【在 CI 服务器上】直接运行，Python 3.8 标准库）。
首次远端 bootstrap 见 local/admin/deploy_remote.py（SSH/SCP 推码+依赖，D-010）；本脚本只管
服务器本地安装。GitLab 装本机、HTTP 直达，端口由 probe_port.py 探测锁定（避开被占用端口）。

  python3 deploy.py all       # 自检 → 锁 host → 锁端口 → 装 GitLab(手输root密码) → 全自动注册 Runner
  python3 deploy.py runner    # 全自动注册 Runner（gitlab-rails 建项目+签 token，GitLab 16+ 新流程）
或分步：check / host / port / gitlab / runner（runner 可加 --token glrt- 手动 fallback）
宪法：遇缺失即停（C-10）；参数来自 config.ini（C-7）。
"""
import argparse
import getpass
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))            # server/deploy
SERVER = os.path.dirname(HERE)                               # server
_R = HERE
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
sys.path.insert(0, _R)
import ci_config  # noqa: E402


def py(relpath, *args, redact=None, base=None):
    base = base or HERE
    return ci_config.run(["python3", os.path.join(base, relpath)] + list(args), redact=redact)


def check_env():
    print("=== 环境自检 ===")
    ok = True
    print("python3:", sys.version.split()[0])
    if sys.version_info < (3, 8):
        print("[WARN] 期望 python3 >= 3.8")
    found = subprocess.run(["which", "dpkg"], stdout=subprocess.PIPE).returncode == 0
    print("命令 dpkg:", "有" if found else "缺失")
    if not found:
        ok = False
    cfg = ci_config.load()
    deps = ci_config.get_deps_dir(cfg)
    print("离线依赖目录:", deps, "存在" if os.path.isdir(deps) else "[缺失]")
    if not os.path.isdir(deps):
        ok = False
    print("=== 自检%s ===" % ("通过" if ok else "未通过"))
    return ok


def set_root_password_env():
    """装 GitLab 前交互手输 root 初始密码（getpass 不回显），回车用 config 默认值。
    经环境变量传给 install_gitlab 子进程，不走命令行/不入仓（C-1）。远端经 ssh -tt 传入。"""
    if os.environ.get("GITLAB_ROOT_PASSWORD"):
        return                                      # 已由上游注入则不重复询问
    if os.path.exists("/opt/gitlab"):
        # omnibus 仅在首次 reconfigure 初始化 DB 时读取该变量；已装则设了也不生效，跳过免误导。
        print("[deploy] GitLab 已安装，跳过 root 密码设置（仅首次安装生效；改密用 gitlab-rails）。")
        return
    cfg = ci_config.load()
    default = ci_config.get(cfg, "gitlab", "root_password_default", "88888888")
    try:
        pw = getpass.getpass("GitLab root 初始密码（回车用默认 %s，≥8 位）: " % default)
    except EOFError:                                # 非交互(无 TTY)→ 用默认；Ctrl-C 不捕获，自然中止
        print("\n非交互环境，用默认密码。")
        pw = ""
    pw = pw.strip() or default
    if len(pw) < 8:
        raise SystemExit("密码至少 8 位（GitLab 要求），停止。")
    os.environ["GITLAB_ROOT_PASSWORD"] = pw
    print("[deploy] root 初始密码已设定（脱敏），经环境变量注入 GitLab 安装。")


def step_host():
    cfg = ci_config.load()
    host = ci_config.get(cfg, "server", "host", "").strip()
    if host:
        print("\n=== host 已设定：%s（复用）===" % host)
        return
    ip = ci_config.local_ip()
    ci_config.set_value("server", "host", ip)
    print("\n=== 探测并锁定 host：%s（写入 config.ini [server] host）===" % ip)
    if ip == "127.0.0.1":
        print("[提醒] 未探测到内网 IP，已用 127.0.0.1。多机访问请手动改 host。")


def step_port():
    print("\n=== 探测并锁定 GitLab 端口 ===")
    py("probe_port.py")


def external_url():
    return ci_config.external_url(ci_config.load())


def step_gitlab():
    print("\n=== 安装 GitLab CE ===")
    set_root_password_env()
    url = external_url()
    print("external_url =", url)
    py("install_gitlab.py", "--external-url", url)
    print("GitLab 安装完成。Runner 将由 deploy.py 全自动注册（gitlab-rails 签 token）。")


def step_runner(token=None):
    print("\n=== 安装并全自动注册 Runner ===")
    extra = ["--token", token] if token else []
    py("setup_runner.py", "--url", external_url(), *extra,
       redact={"--token"}, base=os.path.join(SERVER, "runner"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["check", "host", "port", "gitlab", "runner", "all"])
    ap.add_argument("--token", help="Runner authentication token(glrt-)；省略则全自动签发")
    args = ap.parse_args()

    if args.action == "check":
        sys.exit(0 if check_env() else 1)

    if not check_env():
        print("自检未通过，停止（勿绕过）。", file=sys.stderr)
        sys.exit(1)

    if args.action in ("host", "all"):
        step_host()
    if args.action in ("port", "all"):
        step_port()
    if args.action in ("gitlab", "all"):
        step_gitlab()
    if args.action in ("runner", "all"):
        step_runner(args.token)

    print("\n完成。验证见 docs/tasks/iter1_skeleton.md。")


if __name__ == "__main__":
    main()
