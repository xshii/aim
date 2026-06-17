#!/usr/bin/env python3
# implements: FR-9, FR-11
"""Jenkins 离线部署（role=server/deploy，python3 标准库）。CI 框架=Jenkins（D-016）。
需 root（sudo python3 deploy.py all）。离线包由有网机 fetch_offline.py 产出，放 [offline] deps_dir。
  sudo python3 deploy.py all       # check → init(解包/放插件/JCasC) → service(systemd: jenkins+webhook)
或分步：check / init / service
宪法：遇缺失即停（C-10）；参数来自 config.ini，密钥来自 config.local.ini（C-7, C-1）。"""
import argparse
import os
import shutil
import subprocess
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))            # server/deploy
_R = HERE
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
CI_ROOT = _R
sys.path.insert(0, _R)
import ci_config  # noqa: E402
import constants   # noqa: E402

ALLOWED_PORTS = constants.ALLOWED_PORTS
ENV_FILE = "/etc/ci-jenkins.env"      # systemd EnvironmentFile（0600，存密钥，不入仓）


def _port(cfg, section, key, default):
    raw = ci_config.get(cfg, section, key, default)
    try:
        return int(raw.rsplit(":", 1)[-1])
    except ValueError:
        return -1


def _paths(cfg):
    """集中算各路径（init/service 共用，单一来源 C-7）。"""
    home = ci_config.expand(ci_config.get(cfg, "jenkins", "home", "/opt/ci/jenkins_home"))
    deps = ci_config.expand(ci_config.get(cfg, "offline", "deps_dir", "/opt/ci/offline"))
    pkg = ci_config.get(cfg, "offline", "package", "jenkins-offline.tar.gz")
    install = os.path.dirname(home) or "/opt/ci"        # 解包根（与 JENKINS_HOME 同级）
    extracted = os.path.join(install, "jenkins-offline")  # 包内顶层目录名
    java_home = ci_config.expand(ci_config.get(cfg, "jenkins", "java_home", ""))
    java = os.path.join(java_home, "bin", "java") if java_home else os.path.join(extracted, "jdk", "bin", "java")
    return {
        "home": home, "package": os.path.join(deps, pkg), "extracted": extracted,
        "war": os.path.join(extracted, "jenkins.war"),
        "plugins_src": os.path.join(extracted, "plugins"),
        "java": java, "casc": os.path.join(home, "jenkins.yaml"),
        "http_port": _port(cfg, "jenkins", "http_port", "8080"),
    }


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
    jport = _port(cfg, "jenkins", "http_port", "8080")
    wport = _port(cfg, "webhook", "listen", "0.0.0.0:8090")
    for label, p in (("Jenkins", jport), ("webhook", wport)):
        good = p in ALLOWED_PORTS
        print("%s 端口 %s:" % (label, p), "允许" if good else "[超范围! 仅 80-90 / 443 / 8080-8090]")
        ok = ok and good
    if jport == wport:
        print("[ERROR] Jenkins 与 webhook 端口相同（%s），须不同（同机两服务）。" % jport)
        ok = False
    p = _paths(cfg)
    has_pkg = os.path.isfile(p["package"])
    print("离线包 %s:" % p["package"], "有" if has_pkg else "缺失（先在有网机跑 fetch_offline.py）")
    ok = ok and has_pkg
    print("=== 自检%s ===" % ("通过" if ok else "未通过"))
    return ok


def step_init():
    cfg = ci_config.load()
    p = _paths(cfg)
    if not os.path.isfile(p["package"]):
        raise SystemExit("缺离线包 %s：先在有网机跑 fetch_offline.py（C-10，不臆造）。" % p["package"])

    print("[init] 解包 %s → %s" % (p["package"], p["extracted"]))
    shutil.rmtree(p["extracted"], ignore_errors=True)
    with tarfile.open(p["package"]) as t:
        t.extractall(os.path.dirname(p["extracted"]))     # noqa: S202  自产离线包，可信
    for must in (p["war"], p["plugins_src"], p["java"]):
        if not os.path.exists(must):
            raise SystemExit("[init] 离线包内容异常，缺 %s（重跑 fetch_offline.py）。" % must)
    os.chmod(p["java"], 0o755)

    plugins_dst = os.path.join(p["home"], "plugins")
    os.makedirs(plugins_dst, exist_ok=True)
    n = 0
    for f in os.listdir(p["plugins_src"]):
        if f.endswith((".jpi", ".hpi")):
            shutil.copy(os.path.join(p["plugins_src"], f), os.path.join(plugins_dst, f))
            n += 1
    print("[init] 放置插件 %d 个 → %s" % (n, plugins_dst))

    # 渲染 JCasC：用 config.ini 的值填 @@占位@@（密码仍是 ${JENKINS_ADMIN_PASSWORD} 运行时注入）。
    admin = ci_config.get(cfg, "jenkins", "admin_user", "admin")
    job = ci_config.get(cfg, "jenkins", "job_name", "qsort-eval")
    with open(os.path.join(HERE, "jenkins.yaml"), encoding="utf-8") as f:
        casc = (f.read().replace("@@ADMIN_USER@@", admin)
                .replace("@@HTTP_PORT@@", str(p["http_port"]))
                .replace("@@JOB_NAME@@", job)
                .replace("@@CI_TOOLING@@", CI_ROOT))   # Jenkinsfile 据此引用已部署的 limited_run
    with open(p["casc"], "w", encoding="utf-8") as f:
        f.write(casc)
    print("[init] 写 JCasC:", p["casc"])
    print("[init] JENKINS_HOME 就绪:", p["home"])


def _write_env_file(cfg):
    """把密钥从 config.local.ini 写入 systemd EnvironmentFile（0600，不入仓 C-1）。缺即停（C-10）。"""
    secret = ci_config.secret("WEBHOOK_SECRET", cfg, "secrets", "webhook_secret")
    admin_pw = ci_config.secret("JENKINS_ADMIN_PASSWORD", cfg, "secrets", "jenkins_admin_password")
    missing = [n for n, v in (("webhook_secret", secret),
                              ("jenkins_admin_password", admin_pw)) if not v]
    if missing:
        raise SystemExit("config.local.ini [secrets] 缺 %s：填好再部署（C-10，C-1）。"
                         % "、".join(missing))
    fd = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("WEBHOOK_SECRET=%s\nJENKINS_ADMIN_PASSWORD=%s\n" % (secret, admin_pw))
    print("[service] 写密钥环境文件:", ENV_FILE, "(0600)")


def step_service():
    cfg = ci_config.load()
    p = _paths(cfg)
    _write_env_file(cfg)
    repl = {
        "@@ENV_FILE@@": ENV_FILE, "@@CI_ROOT@@": CI_ROOT, "@@JENKINS_HOME@@": p["home"],
        "@@CASC@@": p["casc"], "@@JAVA@@": p["java"], "@@WAR@@": p["war"],
        "@@HTTP_PORT@@": str(p["http_port"]),
    }
    src = os.path.join(HERE, "systemd")
    for unit in ("ci-jenkins.service", "ci-webhook.service"):
        with open(os.path.join(src, unit), encoding="utf-8") as f:
            content = f.read()
        for k, v in repl.items():
            content = content.replace(k, v)
        dst = "/etc/systemd/system/" + unit
        with open(dst, "w", encoding="utf-8") as f:
            f.write(content)
        print("[service] 写入", dst)
    ci_config.run(["systemctl", "daemon-reload"])
    for unit in ("ci-jenkins", "ci-webhook"):
        ci_config.run(["systemctl", "enable", "--now", unit])
    ci_config.run(["systemctl", "--no-pager", "status", "ci-jenkins", "ci-webhook"],
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
    cfg = ci_config.load()
    port = _port(cfg, "jenkins", "http_port", "8080")
    print("\n完成。验证：systemctl status ci-jenkins ci-webhook；"
          "浏览器开 http://<host>:%s/（admin + config.local 里的密码登录）。" % port)


if __name__ == "__main__":
    main()
