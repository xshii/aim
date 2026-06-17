#!/usr/bin/env python3
# implements: FR-9, FR-11, FR-17
"""在【有网机器】上一次性产出 Jenkins 离线安装件（python3 标准库，零依赖）。
版本/URL 全部来自 config.ini [fetch]（单一事实源 C-7）；产出到 tools/ci/offline/（大文件已 .gitignore）。
产出：jenkins_<ver>_all.deb + plugins/*.jpi（+ 可选 java .deb）。服务器 deploy.py 用 apt 安装这些 .deb。

  python3 fetch_offline.py [输出目录，默认 tools/ci/offline/]

需本机有 java（跑 plugin-manager 解插件依赖）。走代理：export HTTPS_PROXY=http://user:pass@proxy:8080
（urllib 自动用；明文密码不入仓 C-1）。产出经 local/admin/deploy_remote.py push 随代码推到服务器。
"""
import os
import shutil
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CI_ROOT = os.path.dirname(os.path.dirname(HERE))     # server/deploy → tools/ci
sys.path.insert(0, CI_ROOT)
import ci_config  # noqa: E402


def download(url, dest):
    """下载并校验非空（失败即停 C-10）。urllib 自动用 HTTP(S)_PROXY 环境变量。"""
    print("+ 下载 %s" % url)
    with urllib.request.urlopen(url) as r, open(dest, "wb") as f:  # noqa: S310
        shutil.copyfileobj(r, f)
    if os.path.getsize(dest) == 0:
        raise SystemExit("[ERROR] 下载为空: %s" % url)


def main():
    cfg = ci_config.load()
    f = lambda k, d="": ci_config.get(cfg, "fetch", k, d)  # noqa: E731
    jenkins_deb = f("jenkins_deb")
    jenkins_deb_url = f("jenkins_deb_url")
    jenkins_version = f("jenkins_version")
    pm_url = f("plugin_manager_url")
    java_deb = f("java_deb", "")
    java_deb_url = f("java_deb_url", "")

    java = shutil.which("java")
    if not java:
        raise SystemExit("本机无 java：plugin-manager 需 java 跑（先装 JDK/JRE，或在有 java 的机器上跑）。")

    out = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(CI_ROOT, "offline")
    plugins = os.path.join(out, "plugins")
    os.makedirs(plugins, exist_ok=True)

    print("=== 1/3 下载 Jenkins .deb (%s) ===" % jenkins_version)
    download(jenkins_deb_url, os.path.join(out, jenkins_deb))

    print("=== 2/3 下载插件（plugin-manager 按 jenkins 版本解依赖）===")
    pm_jar = os.path.join(out, "jenkins-plugin-manager.jar")
    download(pm_url, pm_jar)
    subprocess.run([java, "-jar", pm_jar,
                    "--jenkins-version", jenkins_version,
                    "--plugin-file", os.path.join(HERE, "plugins.txt"),
                    "--plugin-download-directory", plugins], check=True)

    print("=== 3/3 Java 21 的 .deb ===")
    if java_deb_url:
        download(java_deb_url, os.path.join(out, java_deb))
    else:
        print("  [跳过] config.ini [fetch] java_deb_url 为空。")
        print("  请手动把 JDK/JRE 21 的 .deb（如 %s）放进 %s（apt 与 Jenkins 一起装）。"
              % (java_deb or "openjdk-21-jre-headless_*.deb", out))

    print("\n完成：%s" % out)
    print("  内含 %s + plugins/（+ Java 21 的 .deb）" % jenkins_deb)
    print("  下一步：经 local/admin/deploy_remote.py push 随代码推到服务器，或手动放到 [offline] deps_dir。")


if __name__ == "__main__":
    main()
