#!/usr/bin/env python3
"""下 Jenkins 插件 + 全部依赖到一个目录，打成 tar.gz（有网机用）。
机制：用公网 update-center.actual.json（永远最新、依赖准）在【纯 Python】里解整棵依赖树 → 用 curl
并发下 .hpi → sha256 校验 → 读各 .hpi 的 MANIFEST 静态自检「依赖闭包是否完整」→ 打 tar.gz。
不依赖 java / plugin-cli / urllib：解依赖纯标准库，下载走 curl。
代理读 config.ini [proxy]（含密码的放 config.local.ini，不入仓 C-1）；全空=直连。curl 不读系统代理/PAC，须显式配。

  python3 fetch_plugins.py [插件名...] [--plugin-file F] [--out DIR]
      [--uc-url URL | --uc-file PATH] [--with-optional] [--dry-run]
      [--tar PATH | --no-tar] [--no-verify]

例：
  python3 fetch_plugins.py                       # plugins.txt 全部 + 依赖 → ../offline/plugins，打 tar.gz
  python3 fetch_plugins.py mcp-server git        # 只下指定的几个 + 依赖
  python3 fetch_plugins.py --dry-run             # 只解依赖、打印闭包(name version url)，不下载
  python3 fetch_plugins.py --uc-file uc.json     # 用本地已下好的 update-center.actual.json（离线解依赖）

产出 plugins/*.hpi 与 jenkins-plugins.tar.gz（已含 sha256 校验 + 依赖闭包自检）。
"""
import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..")))  # tools/ci 上的 ci_config
import ci_config  # noqa: E402
# 默认：插件清单取仓库 server/deploy/plugins.txt，产出到 local/offline/plugins（脚本在 local/admin/ 下）。
PLUGINS_FILE_DEFAULT = os.path.normpath(os.path.join(_HERE, "..", "..", "server", "deploy", "plugins.txt"))
OUT_DEFAULT = os.path.normpath(os.path.join(_HERE, "..", "offline", "plugins"))
TAR_DEFAULT = os.path.normpath(os.path.join(_HERE, "..", "offline", "jenkins-plugins.tar.gz"))
# 公网 Update Center 元数据：纯 JSON（无 JSONP 包裹），含每插件最新 version/dependencies/url/sha256。
UC_URL_DEFAULT = "https://updates.jenkins.io/update-center.actual.json"


def apply_proxy():
    """读 config.ini [proxy]（+ config.local.ini 覆盖，放含密码的代理）注入环境，curl 据此走代理；全空=直连。"""
    cfg = ci_config.load()
    set_keys = []
    for k in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        v = ci_config.get(cfg, "proxy", k, "").strip()
        if v:
            os.environ[k] = os.environ[k.upper()] = v  # curl 认小写；大写一并给，兼容其它工具
            set_keys.append(k)
    if set_keys:
        print("+ 用 config.ini [proxy] 代理：%s（值不回显，C-1）" % ", ".join(set_keys))


def read_plugin_ids(path):
    """从 plugins.txt 读插件短名：跳过空行/注释，剥行内 `# 注释`，取首列（兼容 id 或 id:version）。"""
    ids = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                ids.append(line.split()[0].split(":")[0])  # 只取短名；版本以 UC 最新为准
    return ids


def load_uc(uc_url, uc_file):
    """拿 update-center.actual.json：优先本地 --uc-file，否则 curl 下公网（一个小文件，慢点无妨）。"""
    if uc_file:
        with open(uc_file, encoding="utf-8") as f:
            data = json.load(f)
    else:
        print("+ curl 取 Update Center 元数据 %s" % uc_url)
        raw = subprocess.run(["curl", "-fsSL", uc_url], check=True, stdout=subprocess.PIPE).stdout
        data = json.loads(raw)
    plugins = data.get("plugins", {})
    if not plugins:
        sys.exit("update-center 里没有 plugins 段，URL/文件不对？")
    return plugins


def resolve_closure(roots, plugins, with_optional):
    """从 roots 出发 BFS 整棵依赖树，返回 {name: meta}。默认跳过 optional 依赖（Jenkins 不强求）。"""
    closure, queue, missing = {}, list(roots), []
    while queue:
        name = queue.pop()
        if name in closure:
            continue
        meta = plugins.get(name)
        if not meta:
            missing.append(name)
            continue
        closure[name] = meta
        for dep in meta.get("dependencies", []):
            if dep.get("optional") and not with_optional:
                continue
            queue.append(dep["name"])
    if missing:
        print("[警告] 这些插件在 Update Center 里查无此名（拼写错/已改名/已下架）：%s" % ", ".join(sorted(set(missing))))
    return closure


def sha256_ok(path, b64digest):
    """update-center 里的 sha256 是 base64 编码的原始摘要，解出来和本地算的比。无该字段则跳过。"""
    if not b64digest:
        return True
    want = base64.b64decode(b64digest).hex()
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest() == want


def curl_download(items, out):
    """用 curl --parallel 并发下：拼一个 -K 配置文件（url/output 成对），一次起 curl 全下。"""
    cfg_lines = []
    for name, meta in items:
        out_path = os.path.join(out, name + ".hpi").replace(os.sep, "/")  # Windows 也用正斜杠，避开 curl 配置转义
        cfg_lines.append('url = "%s"' % meta["url"])
        cfg_lines.append('output = "%s"' % out_path)
    cfg_path = os.path.join(out, "_curl.cfg")
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write("\n".join(cfg_lines))
    # -f 出错即失败 / -L 跟重定向(UC 会跳镜像) / --retry 重试 / 并发 16；curl 自动用 HTTPS_PROXY env。
    cmd = ["curl", "-fL", "--retry", "3", "--retry-delay", "2",
           "--parallel", "--parallel-max", "16", "--create-dirs", "-K", cfg_path]
    print("=== curl 并发下 %d 个 .hpi → %s ===" % (len(items), out))
    subprocess.run(cmd, check=True)
    os.remove(cfg_path)


def read_manifest(hpi_path):
    """从 .hpi（zip）读 META-INF/MANIFEST.MF，解析续行折叠，返回 {键: 值}。"""
    with zipfile.ZipFile(hpi_path) as z:
        raw = z.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
    unfolded, attrs = raw.replace("\r\n", "\n").replace("\n ", ""), {}
    for line in unfolded.split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            attrs[k.strip()] = v.strip()
    return attrs


def verify_closure(out):
    """静态自检：读目录里每个 .hpi 的 Plugin-Dependencies，确认非 optional 依赖都在目录里。"""
    present, deps_needed = {}, {}
    for fn in os.listdir(out):
        if not fn.endswith(".hpi"):
            continue
        attrs = read_manifest(os.path.join(out, fn))
        sid = attrs.get("Short-Name") or fn[:-4]
        present[sid] = attrs.get("Plugin-Version", "?")
        for tok in (attrs.get("Plugin-Dependencies", "") or "").split(","):
            tok = tok.strip()
            if not tok:
                continue
            parts = tok.split(";")
            dep = parts[0].split(":")[0]
            # MANIFEST 写法为 "name:ver;resolution:=optional"（注意有等号），故按分号段判 optional
            optional = any("optional" in p for p in parts[1:])
            if not optional:
                deps_needed.setdefault(dep, set()).add(sid)
    missing = {d: who for d, who in deps_needed.items() if d not in present}
    if missing:
        print("[自检失败] 缺这些依赖（被谁需要）：")
        for d, who in sorted(missing.items()):
            print("  - %s  ← %s" % (d, ", ".join(sorted(who))))
        return False
    print("[自检通过] %d 个插件，所有非 optional 依赖闭包完整。" % len(present))
    return True


def main():
    ap = argparse.ArgumentParser(description="下 Jenkins 插件 + 依赖（curl + update-center.json，纯 Python 解依赖）")
    ap.add_argument("plugins", nargs="*", help="插件短名，可多个；省略则读 --plugin-file")
    ap.add_argument("--plugin-file", default=PLUGINS_FILE_DEFAULT, help="插件清单（默认仓库 plugins.txt）")
    ap.add_argument("--out", default=OUT_DEFAULT, help="下载目录（默认 ../offline/plugins）")
    ap.add_argument("--uc-url", default=UC_URL_DEFAULT, help="update-center.actual.json 地址（公网）")
    ap.add_argument("--uc-file", default="", help="本地 update-center.actual.json（离线解依赖，优先于 --uc-url）")
    ap.add_argument("--with-optional", action="store_true", help="连 optional 依赖一起下（默认不下）")
    ap.add_argument("--dry-run", action="store_true", help="只解依赖、打印闭包，不下载")
    ap.add_argument("--tar", default=TAR_DEFAULT, help="打包路径（默认 ../offline/jenkins-plugins.tar.gz）")
    ap.add_argument("--no-tar", action="store_true", help="不打 tar.gz")
    ap.add_argument("--no-verify", action="store_true", help="跳过下载后的依赖闭包静态自检")
    args = ap.parse_args()

    roots = args.plugins or read_plugin_ids(args.plugin_file)
    if not roots:
        sys.exit("无插件可下：给出插件名，或填好 %s。" % args.plugin_file)
    if not shutil.which("curl"):
        sys.exit("本机无 curl。")
    apply_proxy()  # config.ini [proxy] 非空时注入环境；空=直连

    plugins = load_uc(args.uc_url, args.uc_file)
    closure = resolve_closure(roots, plugins, args.with_optional)
    items = sorted(closure.items())
    print("=== 解出闭包：%d 个根 → %d 个插件(含依赖) ===" % (len(roots), len(items)))

    if args.dry_run:
        for name, meta in items:
            print("%-40s %-12s %s" % (name, meta.get("version", "?"), meta["url"]))
        print("--- DRY RUN：共 %d 个，未下载 ---" % len(items))
        return

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    curl_download(items, out)

    bad = [name for name, meta in items if not sha256_ok(os.path.join(out, name + ".hpi"), meta.get("sha256"))]
    if bad:
        sys.exit("[ERROR] sha256 校验不过：%s（重下）" % ", ".join(bad))
    print("[sha256] %d 个全部校验通过。" % len(items))

    if not args.no_verify and not verify_closure(out):
        sys.exit("[ERROR] 依赖闭包不完整，先补齐再打包。")

    if not args.no_tar:
        tar = os.path.abspath(args.tar)
        with tarfile.open(tar, "w:gz") as t:
            t.add(out, arcname="plugins")
        print("[tar] 打包完成 → %s（%.1f MB）" % (tar, os.path.getsize(tar) / 1e6))

    print("\n完成：%d 个 .hpi → %s（依赖闭包自检已通过）" % (len(items), out))
    print("  上线：tar.gz 拷进内网解包到 /var/lib/jenkins/plugins（或随 offline/ 走 deploy.py）。")


if __name__ == "__main__":
    main()
