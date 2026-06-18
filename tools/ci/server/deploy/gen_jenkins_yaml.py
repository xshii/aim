#!/usr/bin/env python3
# implements: FR-3, FR-9
"""渲染 JCasC（jenkins.yaml）：把 config.ini 的值填进模板占位 → 产出 server/deploy/jenkins.rendered.yaml。
其余安装步骤全手动（见 README）：install.sh 装离线 .deb；手动拷插件；本 yaml 经 UI「Configuration as Code →
Apply」或拷到 /var/lib/jenkins/jenkins.yaml 加载。
  python3 gen_jenkins_yaml.py
必填项（缺失/留空即停，C-10）：
  [jenkins] http_port / job_name / executors / admin_user；[secrets] jenkins_admin_password（或 env）。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_R = HERE
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
sys.path.insert(0, _R)
import ci_config  # noqa: E402

# Jenkins 对外端口白名单（内网防火墙：80-90 / 443 / 8080-8090）
ALLOWED_PORTS = frozenset(range(80, 91)) | {443} | frozenset(range(8080, 8091))
TEMPLATE = os.path.join(HERE, "jenkins.yaml")
OUTPUT = os.path.join(HERE, "jenkins.rendered.yaml")


def _req(cfg, section, key):
    """必填：缺 [section] key 或留空即停（C-10）。"""
    v = (cfg.get(section, key) if cfg.has_option(section, key) else "").strip()
    if not v:
        raise SystemExit("配置缺 [%s] %s（必填，不能留空）：在 config.ini 填好再渲染。" % (section, key))
    return v


def main():
    cfg = ci_config.load()
    admin = _req(cfg, "jenkins", "admin_user")
    job = _req(cfg, "jenkins", "job_name")
    execs = _req(cfg, "jenkins", "executors")
    try:
        port = int(_req(cfg, "jenkins", "http_port").rsplit(":", 1)[-1])
    except ValueError:
        raise SystemExit("[jenkins] http_port 非法，须为端口号。")
    if port not in ALLOWED_PORTS:
        raise SystemExit("[jenkins] http_port=%d 超白名单（仅 80-90 / 443 / 8080-8090）。" % port)
    # admin 密码必填——运行时经 ${JENKINS_ADMIN_PASSWORD} 注入；此处只校验存在，不写进 yaml（C-1）。
    if not ci_config.secret("JENKINS_ADMIN_PASSWORD", cfg, "secrets", "jenkins_admin_password"):
        raise SystemExit("缺 admin 密码（必填）：config.local.ini [secrets] jenkins_admin_password 或 env JENKINS_ADMIN_PASSWORD。")

    with open(TEMPLATE, encoding="utf-8") as f:
        casc = (f.read().replace("@@ADMIN_USER@@", admin)
                .replace("@@HTTP_PORT@@", str(port))
                .replace("@@JOB_NAME@@", job)
                .replace("@@EXECUTORS@@", execs))
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(casc)
    print("渲染完成 →", OUTPUT)
    print("下一步：拷到服务器 /var/lib/jenkins/jenkins.yaml，或在 UI「Manage Jenkins → Configuration as Code")
    print("→ Apply new configuration」填该路径加载（admin 密码那段处理见 README）。")


if __name__ == "__main__":
    main()
