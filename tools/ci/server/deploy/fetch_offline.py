#!/usr/bin/env python3
# implements: FR-9, FR-11, FR-17
"""在【有网机器】上一次性产出 Jenkins 离线包（python3 标准库，零依赖）。
产出 jenkins-offline.tar.gz（内含 jenkins.war + plugins/ + jdk/，自包含 JDK21）。
目标平台固定 Linux x86_64(amd64) + JDK 21（Jenkins 2.555.x 要求 Java 21+，已不支持 Java 17）。

  python3 fetch_offline.py [输出目录，默认 ./offline-build]

走代理：export HTTPS_PROXY=http://user:pass@proxy:8080（urllib 自动用；明文密码不入仓，C-1）。
产出放到内网 config.ini [offline] deps_dir，或经 local/admin/deploy_remote.py push 随代码推送。
"""
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request

# ============================================================
# ↓↓↓ 版本号：下包前到官网核对当前 LTS / 当前发行版，改这里（装错版本是硬故障，勿臆造）↓↓↓
# 注意：Jenkins 2.555.x 要求 Java 21+，已不支持 Java 17——JDK 必须 21。
JENKINS_VERSION = "2.555.1"        # 内网可下载的 LTS 版本；2.555.x 要求 Java 21+（已不支持 Java 17）
JDK_TAG = "jdk-21.0.7+6"           # 确认: https://github.com/adoptium/temurin21-binaries/releases （tag）
JDK_FILE = "21.0.7_6"              # 同上 release 里 OpenJDK21U-jdk_x64_linux_hotspot_<这里>.tar.gz
PM_VERSION = "2.13.2"              # 确认: https://github.com/jenkinsci/plugin-installation-manager-tool/releases
# ↑↑↑ 改完上面四个再跑 ↑↑↑
# ============================================================

HERE = os.path.dirname(os.path.abspath(__file__))

JENKINS_URL = "https://get.jenkins.io/war-stable/%s/jenkins.war" % JENKINS_VERSION
JDK_URL = ("https://github.com/adoptium/temurin21-binaries/releases/download/"
           "%s/OpenJDK21U-jdk_x64_linux_hotspot_%s.tar.gz" % (JDK_TAG, JDK_FILE))
PM_URL = ("https://github.com/jenkinsci/plugin-installation-manager-tool/releases/download/"
          "%s/jenkins-plugin-manager-%s.jar" % (PM_VERSION, PM_VERSION))


def download(url, dest):
    """下载并校验非空（失败即停，C-10）。urllib 自动用 HTTP(S)_PROXY 环境变量。"""
    print("+ 下载 %s" % url)
    with urllib.request.urlopen(url) as r, open(dest, "wb") as f:  # noqa: S310
        shutil.copyfileobj(r, f)
    if os.path.getsize(dest) == 0:
        raise SystemExit("[ERROR] 下载为空: %s" % url)


def main():
    out = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(os.getcwd(), "offline-build")
    stage = os.path.join(out, "jenkins-offline")     # 打包根：内含 jenkins.war / plugins/ / jdk/
    plugins = os.path.join(stage, "plugins")
    os.makedirs(plugins, exist_ok=True)

    print("=== 1/4 下载 jenkins.war (%s) ===" % JENKINS_VERSION)
    download(JENKINS_URL, os.path.join(stage, "jenkins.war"))

    print("=== 2/4 下载并解压 JDK21 (%s, linux x64) ===" % JDK_TAG)
    jdk_tar = os.path.join(out, "jdk.tar.gz")
    download(JDK_URL, jdk_tar)
    jdk_dir = os.path.join(stage, "jdk")
    shutil.rmtree(jdk_dir, ignore_errors=True)
    os.makedirs(jdk_dir)
    with tarfile.open(jdk_tar) as t:
        # 去掉顶层目录（--strip-components=1）：成员路径剥第一段后解到 jdk/
        members = []
        for m in t.getmembers():
            parts = m.name.split("/", 1)
            if len(parts) == 2 and parts[1]:
                m.name = parts[1]
                members.append(m)
        t.extractall(jdk_dir, members)            # noqa: S202  离线官方包，可信
    java = os.path.join(jdk_dir, "bin", "java")
    if not os.path.isfile(java):
        raise SystemExit("[ERROR] JDK 解压异常，缺 %s" % java)

    print("=== 3/4 下载插件（用上面 JDK 跑 plugin-manager，自动解依赖）===")
    pm_jar = os.path.join(out, "jenkins-plugin-manager.jar")
    download(PM_URL, pm_jar)
    subprocess.run([java, "-jar", pm_jar,
                    "--war", os.path.join(stage, "jenkins.war"),
                    "--plugin-file", os.path.join(HERE, "plugins.txt"),
                    "--plugin-download-directory", plugins], check=True)

    print("=== 4/4 打包 jenkins-offline.tar.gz ===")
    shutil.copy(os.path.join(HERE, "plugins.txt"), os.path.join(stage, "plugins.txt"))
    pkg = os.path.join(out, "jenkins-offline.tar.gz")
    with tarfile.open(pkg, "w:gz") as t:
        t.add(stage, arcname="jenkins-offline")

    print("\n完成：%s" % pkg)
    print("  内含 jenkins.war + plugins/ + jdk/（自包含 JDK21）")
    print("  下一步：放到内网服务器 config.ini [offline] deps_dir（默认 /opt/ci/offline），跑 deploy.py。")
    print("  或经 local/admin/deploy_remote.py push 随代码 SCP 推送。")


if __name__ == "__main__":
    main()
