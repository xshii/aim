#!/usr/bin/env python3
# implements: FR-9, FR-11
"""Jenkins 离线部署（.deb + apt，role=server/deploy，python3 标准库）。需 root。
离线件（jenkins/java 的 .deb + plugins/）由有网机 fetch_offline.py 产出，放 [offline] deps_dir。
  sudo python3 deploy.py all     # check → init(apt 装 deb + 内源 UC 装插件 + JCasC) → service(systemd)
或分步：check / init / service
宪法：遇缺失即停（C-10）；参数来自 config.ini，密钥来自 config.local.ini（C-7, C-1）。"""
import argparse
import glob
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
import constants   # noqa: E402

ALLOWED_PORTS = constants.ALLOWED_PORTS
ENV_FILE = "/etc/ci-jenkins.env"                       # systemd EnvironmentFile（0600，存密钥）
JENKINS_HOME = "/var/lib/jenkins"                      # jenkins .deb 固定
CASC = os.path.join(JENKINS_HOME, "jenkins.yaml")      # JCasC 落地处
DROPIN = "/etc/systemd/system/jenkins.service.d/override.conf"  # 覆盖 deb 自带 jenkins.service


def _port(cfg, section, key, default):
    try:
        return int(ci_config.get(cfg, section, key, default).rsplit(":", 1)[-1])
    except ValueError:
        return -1


def _deps_dir(cfg):
    return ci_config.expand(ci_config.get(cfg, "offline", "deps_dir", "/opt/ci/local/offline"))


def _debs(deps):
    return sorted(glob.glob(os.path.join(deps, "*.deb")))


def check_env():
    print("=== 环境自检 ===")
    ok = True
    print("python3:", sys.version.split()[0])
    if os.geteuid() != 0:
        print("[ERROR] 需 root：sudo python3 deploy.py <action>。")
        ok = False
    for tool in ("git", "systemctl", "apt-get", "dpkg"):
        found = subprocess.run(["which", tool], stdout=subprocess.PIPE).returncode == 0
        print("命令 %s:" % tool, "有" if found else "缺失")
        ok = ok and found
    cfg = ci_config.load()
    jport = _port(cfg, "jenkins", "http_port", "8080")
    wport = _port(cfg, "webhook", "listen", "0.0.0.0:8090")
    for label, p in (("Jenkins", jport), ("webhook", wport)):
        good = p in ALLOWED_PORTS
        print("%s 端口 %s:" % (label, p), "允许" if good else "[超范围! 仅 80-90 / 443 / 8080-8090]")
        ok = ok and good
    if jport == wport:
        print("[ERROR] Jenkins 与 webhook 端口相同（%s），须不同。" % jport)
        ok = False
    deps = _deps_dir(cfg)
    debs = _debs(deps)
    has_jenkins = any("jenkins" in os.path.basename(d) for d in debs)
    print("离线 .deb（%s）：%s" % (deps, " ".join(os.path.basename(d) for d in debs) or "无"))
    if not has_jenkins:
        print("[ERROR] 缺 jenkins .deb（先在有网机跑 fetch_offline.py）。")
        ok = False
    has_pm = os.path.isfile(os.path.join(deps, "jenkins-plugin-manager.jar"))
    print("plugin-cli 工具:", "有" if has_pm else "[缺 jenkins-plugin-manager.jar]")
    ok = ok and has_pm
    uc = ci_config.get(cfg, "jenkins", "update_center_url", "").strip()
    print("内源 Update Center:", uc or "[未配置! 填 config.ini [jenkins] update_center_url]")
    ok = ok and bool(uc)
    print("=== 自检%s ===" % ("通过" if ok else "未通过"))
    return ok


def _run(cmd, check=True):
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd, check=check, env=env)


def step_init():
    cfg = ci_config.load()
    deps = _deps_dir(cfg)
    debs = _debs(deps)
    if not any("jenkins" in os.path.basename(d) for d in debs):
        raise SystemExit("缺 jenkins .deb 于 %s：先在有网机跑 fetch_offline.py（C-10）。" % deps)

    # apt 装本地 .deb（jenkins + java 一起，apt 解依赖）；失败回退 dpkg。
    print("[init] apt 安装离线 .deb：%s" % " ".join(os.path.basename(d) for d in debs))
    if _run(["apt-get", "install", "-y"] + debs, check=False).returncode != 0:
        print("[init] apt-get 失败，回退 dpkg -i（如缺依赖，请把依赖 .deb 一并放进 deps_dir）。")
        _run(["dpkg", "-i"] + debs, check=False)
        _run(["apt-get", "install", "-y", "-f"], check=False)
    # apt 装会按 deb 默认配置自动起 jenkins；停掉，待插件/JCasC/drop-in 就位后由 service 用完整配置起。
    _run(["systemctl", "stop", "jenkins"], check=False)

    # 从内源 Update Center 装插件（CI 服务器直连内源库；plugin-cli + plugins.txt）。
    uc = ci_config.get(cfg, "jenkins", "update_center_url", "").strip()
    if not uc:
        raise SystemExit("config.ini [jenkins] update_center_url 为空：填内源 Update Center 地址（C-10）。")
    pm_jar = os.path.join(deps, "jenkins-plugin-manager.jar")
    if not os.path.isfile(pm_jar):
        raise SystemExit("缺 %s（fetch_offline.py 应已下载并随 offline/ 推来）。" % pm_jar)
    plugins_dst = os.path.join(JENKINS_HOME, "plugins")
    os.makedirs(plugins_dst, exist_ok=True)
    cmd = ["/usr/bin/java", "-jar", pm_jar,
           "--jenkins-update-center", uc,
           "--plugin-file", os.path.join(HERE, "plugins.txt"),
           "--plugin-download-directory", plugins_dst]
    version = ci_config.get(cfg, "fetch", "jenkins_version", "")  # 单源版本（与 .deb 同）
    if version:
        cmd += ["--jenkins-version", version]
    _run(cmd)
    print("[init] 从内源 UC 装插件 → %s" % plugins_dst)

    # 渲染 JCasC：用 config.ini 填 @@占位@@（密码仍 ${JENKINS_ADMIN_PASSWORD} 运行时注入）。
    admin = ci_config.get(cfg, "jenkins", "admin_user", "admin")
    job = ci_config.get(cfg, "jenkins", "job_name", "qsort-eval")
    port = _port(cfg, "jenkins", "http_port", "8080")
    with open(os.path.join(HERE, "jenkins.yaml"), encoding="utf-8") as fp:
        casc = (fp.read().replace("@@ADMIN_USER@@", admin)
                .replace("@@HTTP_PORT@@", str(port))
                .replace("@@JOB_NAME@@", job)
                .replace("@@CI_TOOLING@@", CI_ROOT))
    with open(CASC, "w", encoding="utf-8") as fp:
        fp.write(casc)
    _run(["chown", "-R", "jenkins:jenkins", plugins_dst, CASC], check=False)
    print("[init] 写 JCasC:", CASC)


def _write_env_file(cfg):
    """密钥从 config.local.ini 写入 systemd EnvironmentFile（0600，不入仓 C-1）。缺即停（C-10）。"""
    secret = ci_config.secret("WEBHOOK_SECRET", cfg, "secrets", "webhook_secret")
    admin_pw = ci_config.secret("JENKINS_ADMIN_PASSWORD", cfg, "secrets", "jenkins_admin_password")
    missing = [n for n, v in (("webhook_secret", secret),
                              ("jenkins_admin_password", admin_pw)) if not v]
    if missing:
        raise SystemExit("config.local.ini [secrets] 缺 %s：填好再部署（C-10, C-1）。"
                         % "、".join(missing))
    fd = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("WEBHOOK_SECRET=%s\nJENKINS_ADMIN_PASSWORD=%s\n" % (secret, admin_pw))
    print("[service] 写密钥环境文件:", ENV_FILE, "(0600)")


def _render(unit_tmpl, repl):
    with open(os.path.join(HERE, "systemd", unit_tmpl), encoding="utf-8") as f:
        content = f.read()
    for k, v in repl.items():
        content = content.replace(k, v)
    return content


def step_service():
    cfg = ci_config.load()
    port = _port(cfg, "jenkins", "http_port", "8080")
    _write_env_file(cfg)

    # Jenkins：覆盖 deb 自带 jenkins.service（端口/JCasC/跳过向导/admin 密码）。
    os.makedirs(os.path.dirname(DROPIN), exist_ok=True)
    with open(DROPIN, "w", encoding="utf-8") as f:
        f.write(_render("jenkins-override.conf",
                        {"@@ENV_FILE@@": ENV_FILE, "@@CASC@@": CASC, "@@HTTP_PORT@@": str(port)}))
    print("[service] 写 Jenkins drop-in:", DROPIN)

    # webhook 适配器服务。
    dst = "/etc/systemd/system/ci-webhook.service"
    with open(dst, "w", encoding="utf-8") as f:
        f.write(_render("ci-webhook.service", {"@@ENV_FILE@@": ENV_FILE, "@@CI_ROOT@@": CI_ROOT}))
    print("[service] 写入", dst)

    ci_config.run(["systemctl", "daemon-reload"])
    ci_config.run(["systemctl", "enable", "jenkins", "ci-webhook"], check=False)
    # 用 restart（非 enable --now）：apt 装时 jenkins 可能已用默认配置起过，必须 restart 才应用 drop-in。
    for unit in ("jenkins", "ci-webhook"):
        ci_config.run(["systemctl", "restart", unit], check=False)
    ci_config.run(["systemctl", "--no-pager", "status", "jenkins", "ci-webhook"], check=False)


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
    cfg = ci_config.load()
    port = _port(cfg, "jenkins", "http_port", "8080")
    print("\n完成。验证：systemctl status jenkins ci-webhook；"
          "浏览器开 http://<host>:%s/（admin + config.local 里的密码登录）。" % port)


if __name__ == "__main__":
    main()
