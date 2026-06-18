#!/usr/bin/env python3
"""独立脚本：下 Jenkins 插件 + 全部依赖到一个目录（自包含，可单独拷走运行，不依赖本仓库其它代码）。
用 plugin-installation-manager-tool(plugin-cli) 从公网 Update Center 下，自动解析整棵依赖树 → 不漏依赖
（手动下 .jpi 才会缺）。需本机有 java + 可联网（可走 HTTPS_PROXY 代理）。
内网 Update Center 装不了插件时用本脚本：把产出的 .jpi 放进 Jenkins 默认插件路径 /var/lib/jenkins/plugins。

  python3 fetch_plugins.py [插件名...] [--plugin-file F] [--out DIR] [--jenkins-version X] [--dry-run]

例：
  python3 fetch_plugins.py                              # 下 plugins.txt 里全部插件 + 依赖 → ../offline/plugins
  python3 fetch_plugins.py mcp-server git               # 只下指定的几个 + 依赖
  python3 fetch_plugins.py --dry-run                    # 只解析依赖、打印会下载的插件+链接，不下载
  python3 fetch_plugins.py --out ./jpi --jenkins-version 2.555.1
"""
import argparse
import os
import shutil
import subprocess
import sys
import urllib.request

PM_VERSION_DEFAULT = "2.13.2"        # plugin-installation-manager-tool 版本（按需改/用 --pm-version）
JENKINS_VERSION_DEFAULT = "2.555.1"  # 目标 Jenkins 版本（解插件兼容用；须与内网部署的一致）
_HERE = os.path.dirname(os.path.abspath(__file__))
# 默认：插件清单取仓库的 server/deploy/plugins.txt，产出到 local/offline/plugins（脚本在 local/admin/ 下）。
PLUGINS_FILE_DEFAULT = os.path.normpath(os.path.join(_HERE, "..", "..", "server", "deploy", "plugins.txt"))
OUT_DEFAULT = os.path.normpath(os.path.join(_HERE, "..", "offline", "plugins"))
PM_URL = ("https://github.com/jenkinsci/plugin-installation-manager-tool/releases/download/"
          "%s/jenkins-plugin-manager-%s.jar")


def read_plugin_ids(path):
    """从 plugins.txt 读插件短名：跳过空行/注释，剥行内 `# 注释`，取首列（兼容 id 或 id:version）。"""
    ids = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                ids.append(line.split()[0])
    return ids


# 插件官方下载链接：updates.jenkins.io/download/plugins/<name>/<version>/<name>.hpi
DOWNLOAD_BASE = "https://updates.jenkins.io/download/plugins"


def parse_will_download(text):
    """从 plugin-cli --list 输出里取 'Plugins that will be downloaded:' 段的 (name, version)。"""
    items, grab = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Plugins that will be downloaded"):
            grab = True
            continue
        if grab:
            if not s or s.startswith("Resulting plugin list"):
                break
            parts = s.split()
            if len(parts) >= 2:
                items.append((parts[0], parts[1]))
    return items


def main():
    ap = argparse.ArgumentParser(description="下 Jenkins 插件 + 依赖（plugin-cli，自动解依赖）")
    ap.add_argument("plugins", nargs="*", help="插件短名，可多个；省略则读 --plugin-file")
    ap.add_argument("--plugin-file", default=PLUGINS_FILE_DEFAULT, help="插件清单（默认仓库 plugins.txt）")
    ap.add_argument("--out", default=OUT_DEFAULT, help="下载目录（默认 ../offline/plugins）")
    ap.add_argument("--jenkins-version", default=JENKINS_VERSION_DEFAULT, help="目标 Jenkins 版本")
    ap.add_argument("--pm-version", default=PM_VERSION_DEFAULT, help="plugin-cli 工具版本")
    ap.add_argument("--dry-run", action="store_true",
                    help="只解析依赖、打印会下载的插件+链接，不实际下载（默认真实下载）")
    args = ap.parse_args()

    plugins = args.plugins or read_plugin_ids(args.plugin_file)
    if not plugins:
        sys.exit("无插件可下：给出插件名，或填好 %s。" % args.plugin_file)

    java = shutil.which("java")
    if not java:
        sys.exit("本机无 java：plugin-cli 需 java 跑（先装 JDK/JRE）。")

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    pm_jar = os.path.join(out, "jenkins-plugin-manager.jar")
    if not os.path.isfile(pm_jar):
        url = PM_URL % (args.pm_version, args.pm_version)
        print("+ 下载 plugin-cli %s" % url)
        with urllib.request.urlopen(url) as r, open(pm_jar, "wb") as f:  # noqa: S310
            shutil.copyfileobj(r, f)

    base = [java, "-jar", pm_jar, "--plugins"] + plugins
    if args.jenkins_version:
        base += ["--jenkins-version", args.jenkins_version]

    if args.dry_run:
        # --list --no-download：解析整棵依赖树并列出，但不下载 .hpi（plugin-cli 列表走 stderr，一并捕获）
        out_text = subprocess.run(base + ["--list", "--no-download"], check=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
        items = parse_will_download(out_text)
        print("=== DRY RUN：会下载 %d 个插件(含依赖)，链接如下，未实际下载 ===" % len(items))
        for name, ver in items:
            print("%s/%s/%s/%s.hpi" % (DOWNLOAD_BASE, name, ver, name))
        return

    print("=== plugin-cli 从公网 UC 下 %d 个插件 + 全部依赖 → %s ===" % (len(plugins), out))
    print("    " + ", ".join(plugins))
    subprocess.run(base + ["--plugin-download-directory", out], check=True)

    jpis = sorted(f for f in os.listdir(out) if f.endswith((".jpi", ".hpi")))
    print("\n完成：%d 个 .jpi（含依赖）→ %s" % (len(jpis), out))
    print("  放进 Jenkins 默认插件路径 /var/lib/jenkins/plugins（本仓库流程：随 offline/ 推送，deploy.py 自动拷）。")


if __name__ == "__main__":
    main()
