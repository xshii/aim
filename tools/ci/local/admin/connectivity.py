#!/usr/bin/env python3
# implements: FR-18
"""
连通性自测（role=local/admin，Python 3.8 标准库）。admin check —— 在【执行机】上 push 前自检。
供 deploy_remote 复用，也可独立排障（C-7）。与 server 的环境自检（deploy.py check）相互独立。
  python3 connectivity.py
检查：远端 SSH 可达 + 远端有 python3（若配 [remote] host）、GitLab HTTP/API + Token 有效
（若给 env GITLAB_API/TOKEN/PROJECT）、webhook 监听提示（若启用）。
失败明确报告缺失项并非零退出（C-10）。
"""
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

_R = os.path.dirname(os.path.abspath(__file__))
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
sys.path.insert(0, _R)
import ci_config  # noqa: E402


def tcp(host, port, timeout=5):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def ssh_cmd(user, host, port, ssh_opts, tty=False):
    """组装 ssh 命令前缀（含目标）。供 connectivity 与 deploy_remote 共用。
    tty=True 强制分配伪终端（-tt），供远端交互——如 deploy 远程执行时 getpass 手输 root 密码。"""
    base = ["ssh", "-p", str(port), "-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
    if tty:
        base.append("-tt")
    if ssh_opts and ssh_opts.strip():
        base += ssh_opts.split()
    base.append("%s@%s" % (user, host) if user else host)
    return base


def remote_python(user, host, port, ssh_opts):
    p = subprocess.run(ssh_cmd(user, host, port, ssh_opts) + ["python3", "--version"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
    return p.returncode, p.stdout.decode("utf-8", "replace").strip()


def gitlab_api(api, token, project, timeout=10):
    url = "%s/projects/%s" % (api.rstrip("/"), urllib.parse.quote(str(project), safe=""))
    r = urllib.request.Request(url)
    r.add_header("PRIVATE-TOKEN", token)
    # 内网 GitLab 直连，不经代理（D-008）；屏蔽环境里的 HTTP(S)_PROXY，免与依赖下载代理冲突。
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with direct.open(r, timeout=timeout) as resp:
        return resp.getcode()


def remote_admin(user, host, port, ssh_opts):
    """校验远端登录用户具备管理员权限。返回 'root' / 'sudo' / 'none'（或异常时空串）。
    'sudo' 含【免密 sudo】与【在 sudo/wheel/admin 组的需密码 sudo】——后者部署时经 sudo 交互输密码。
    一键部署需 dpkg/gitlab-ctl 等特权，故在 push 前先校验，避免部署中途才失败（C-10）。"""
    check = ('if [ "$(id -u)" = 0 ]; then echo root; '
             'elif sudo -n true 2>/dev/null; then echo sudo; '
             "elif id -nG 2>/dev/null | tr ' ' '\\n' | grep -qxE 'sudo|wheel|admin'; then echo sudo; "
             'else echo none; fi')
    p = subprocess.run(ssh_cmd(user, host, port, ssh_opts) + [check],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
    out = p.stdout.decode("utf-8", "replace").strip().splitlines()
    return out[-1] if out else ""


def looks_like_auth_fail(rc, out):
    """BatchMode 下 SSH 鉴权失败：rc==255 且输出含 publickey/Permission denied。
    与「连上了但远端无 python3」（其它 rc）区分，仅前者引导 ssh-copy-id。"""
    if rc != 255:
        return False
    low = out.lower()
    return "permission denied" in low or "publickey" in low


def have_local_pubkey():
    sshdir = os.path.expanduser("~/.ssh")
    return os.path.isdir(sshdir) and any(f.endswith(".pub") for f in os.listdir(sshdir))


def offer_copy_id(user, host, port, ssh_opts):
    """SSH 端口通但密钥认证失败时，交互引导 ssh-copy-id 安装本地公钥。
    经用户确认才执行、不自动改远端（C-10）；继承当前 TTY 由用户交互输一次密码。成功返回 True。"""
    print("[conn] SSH 端口可达但密钥认证失败（远端未配公钥免登？）。", file=sys.stderr)
    if not have_local_pubkey():
        print("[conn] 本地 ~/.ssh 无公钥，请先生成：ssh-keygen -t ed25519，再重试。", file=sys.stderr)
        return False
    target = ("%s@%s" % (user, host)) if user else host
    ans = input("[conn] 运行 ssh-copy-id 安装本地公钥到 %s（将交互输入一次密码）？[y/N] " % target)
    if ans.strip().lower() not in ("y", "yes"):
        print("[conn] 已跳过 ssh-copy-id。", file=sys.stderr)
        return False
    cmd = ["ssh-copy-id", "-p", str(port)]
    if ssh_opts and ssh_opts.strip():
        cmd += ssh_opts.split()
    cmd.append(target)
    print("[conn] 运行：%s" % " ".join(cmd))
    if subprocess.call(cmd) != 0:                       # 继承 TTY，交互输密码
        print("[conn] ssh-copy-id 失败。", file=sys.stderr)
        return False
    print("[conn] 公钥已安装，重新校验 ...")
    return True


def main():
    cfg = ci_config.load()
    fails = []

    rhost = ci_config.get(cfg, "remote", "host", "").strip() if cfg.has_section("remote") else ""
    if rhost:
        ruser = ci_config.get(cfg, "remote", "user", "root")
        rport = ci_config.get(cfg, "remote", "port", "22")
        ropts = ci_config.get(cfg, "remote", "ssh_opts", "")
        print("[conn] 远端 TCP %s:%s ..." % (rhost, rport))
        if not tcp(rhost, rport):
            fails.append("SSH 端口不可达 %s:%s" % (rhost, rport))
        else:
            try:
                rc, out = remote_python(ruser, rhost, rport, ropts)
                # 端口通但密钥认证失败 + 交互式终端：引导 ssh-copy-id 装公钥后重测。
                if rc != 0 and looks_like_auth_fail(rc, out) and sys.stdin.isatty():
                    if offer_copy_id(ruser, rhost, rport, ropts):
                        rc, out = remote_python(ruser, rhost, rport, ropts)
                print("[conn] 远端 python3: rc=%d %s" % (rc, out))
                if rc != 0:
                    fails.append("远端无 python3 或 SSH 鉴权失败：%s" % out)
                else:
                    # 鉴权通过：一键部署前校验管理员权限，避免部署中途因权限失败（C-10）。
                    role = remote_admin(ruser, rhost, rport, ropts)
                    print("[conn] 远端管理员权限：%s" % (role or "未知"))
                    if role not in ("root", "sudo"):
                        fails.append("远端用户 %s 无管理员权限（需 root，或在 sudo/wheel/admin 组），"
                                     "一键部署将失败" % ruser)
                    elif role == "sudo" and ruser != "root":
                        print("[conn] 远端非 root，将以 sudo 运行 deploy.py（部署时可能需输一次 sudo 密码）。")
            except Exception as e:  # noqa
                fails.append("SSH 执行失败：%s" % e)
    else:
        print("[conn] 未配置 [remote] host，跳过 SSH 检查。")

    api = os.environ.get("GITLAB_API", "").rstrip("/")
    token = os.environ.get("GITLAB_TOKEN", "")
    project = os.environ.get("GITLAB_PROJECT", "")
    if api and token and project:
        print("[conn] GitLab API %s 项目 %s ..." % (api, project))
        try:
            code = gitlab_api(api, token, project)
            print("[conn] GitLab API HTTP %s" % code)
            if code != 200:
                fails.append("GitLab API 非 200：%s" % code)
        except urllib.error.HTTPError as e:
            fails.append("GitLab API HTTP %s（Token/项目？）" % e.code)
        except Exception as e:  # noqa
            fails.append("GitLab API 不可达：%s" % e)
    else:
        print("[conn] 未给 GITLAB_API/TOKEN/PROJECT 环境变量，跳过 GitLab 检查。")

    if cfg.has_section("webhook") and \
            ci_config.get(cfg, "webhook", "enabled", "false").lower() == "true":
        print("[conn] webhook 接收器监听：%s（启服务时占用此端口）"
              % ci_config.get(cfg, "webhook", "listen", "0.0.0.0:9100"))

    print("=== 连通性%s ===" % ("通过" if not fails else "未通过"))
    for f in fails:
        print("[FAIL]", f, file=sys.stderr)
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
