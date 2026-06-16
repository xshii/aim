#!/usr/bin/env python3
# implements: FR-9, FR-11, FR-15, NFR-2
"""
本地一键部署（role=server/deploy：代码到位后【在 CI 服务器上】直接运行，Python 3.8 标准库）。
首次远端 bootstrap 见 local/admin/deploy_remote.py（SSH/SCP 推码+依赖，D-010）；本脚本只管
服务器本地安装。GitLab 装本机、HTTP 直达，端口由 probe_port.py 探测锁定（避开被占用端口）。

  python3 deploy.py all                       # 自检 → 锁 host → 锁端口 → 装 GitLab
  python3 deploy.py runner --url U --token T   # 拿到 Token 后注册 Runner
或分步：check / host / port / gitlab / runner
宪法：遇缺失即停（C-10）；参数来自 config.ini（C-7）。
"""
import argparse
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
    cfg = ci_config.load()
    if cfg.has_option("gitlab", "external_url") and ci_config.get(cfg, "gitlab", "external_url"):
        return ci_config.get(cfg, "gitlab", "external_url")
    host = ci_config.get(cfg, "server", "host", "").strip()
    if not host:
        raise SystemExit("host 未锁定，请先运行：python3 deploy.py host（或 all）")
    port = ci_config.get(cfg, "gitlab", "http_port", "")
    if not port:
        raise SystemExit("http_port 未锁定，请先运行：python3 deploy.py port")
    return "http://%s:%s" % (host, port)


def step_gitlab():
    print("\n=== 安装 GitLab CE ===")
    url = external_url()
    print("external_url =", url)
    py("install_gitlab.py", "--external-url", url)
    print("下一步：浏览器打开", url, "建 Private 项目、拿 Runner Token，")
    print("再运行：python3 deploy.py runner --url <URL> --token <TOKEN>")


def step_runner(url, token):
    print("\n=== 安装并注册 Runner ===")
    py("setup_runner.py", "--url", url, "--token", token,
       redact={"--token"}, base=os.path.join(SERVER, "runner"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["check", "host", "port", "gitlab", "runner", "all"])
    ap.add_argument("--url")
    ap.add_argument("--token")
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
    if args.action == "runner":
        if not args.url or not args.token:
            print("runner 需要 --url 与 --token（勿编造）。", file=sys.stderr)
            sys.exit(1)
        step_runner(args.url, args.token)

    print("\n完成。验证见 docs/tasks/iter1_skeleton.md。")


if __name__ == "__main__":
    main()
