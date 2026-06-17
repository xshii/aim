#!/usr/bin/env python3
"""把整套 tools/ci（代码 + local/offline 离线件）送到目标机：打成 tar.gz，或不打包直接传目录（python3 标准库）。
取代手动 tar/scp/rsync。传输仅在【能直连目标机】时用；不能直连就只打包、人肉搬介质。

目标默认读 config.ini [ship]（host/user/port/dest/ssh_opts）；host 留空 = 只打包不传。CLI 参数临时覆盖配置。

  python3 packship.py                  # 据 [ship]：host 空=只打包；host 有值=打包+scp tar.gz
  python3 packship.py --dir            # 据 [ship] 直接传目录（不打包，rsync 优先，否则 scp -r）
  python3 packship.py --out /tmp/ci.tar.gz                  # 只打包到指定路径
  python3 packship.py --scp root@10.0.0.5:/opt/            # 覆盖 [ship]，打包 + scp 到 /opt/（服务器解包得 /opt/ci）
  python3 packship.py --scp host:/opt/ -p 2222 --ssh-opts "-i ~/.ssh/id_ed25519"   # 临时覆盖端口/选项

内容：整个 tools/ci/（顶层目录名 ci/，含 local/offline 的 .deb + plugins/*.hpi）。
排除：__pycache__、*.pyc、config.local.ini（含密钥不外带，C-1）、.git、已有 *.tar.gz/*.tgz。
服务器上：解包/收到后 → cd .../ci → sudo python3 server/deploy/deploy.py all。
"""
import argparse
import os
import shutil
import sys
import tarfile

_HERE = os.path.dirname(os.path.abspath(__file__))
CI_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))     # local/admin → tools/ci
sys.path.insert(0, CI_ROOT)
import ci_config  # noqa: E402
OUT_DEFAULT = os.path.join(CI_ROOT, "local", "offline", "ci-bundle.tar.gz")
ARC_TOP = "ci"                                                  # 顶层目录名（配合 deps_dir 默认 /opt/ci/...）
EXCLUDE_NAMES = {"__pycache__", ".git", "config.local.ini"}
EXCLUDE_SUFFIX = (".pyc", ".pyo", ".tar.gz", ".tgz")


def _excluded(name):
    return name in EXCLUDE_NAMES or name.endswith(EXCLUDE_SUFFIX)


def warn_if_incomplete():
    """离线件不全只告警不拦（允许只传代码）；要可部署须有 jenkins .deb + 插件。"""
    offline = os.path.join(CI_ROOT, "local", "offline")
    debs = [f for f in os.listdir(offline) if f.endswith(".deb")] if os.path.isdir(offline) else []
    pdir = os.path.join(offline, "plugins")
    hpis = [f for f in os.listdir(pdir) if f.endswith((".hpi", ".jpi"))] if os.path.isdir(pdir) else []
    if not any("jenkins" in d for d in debs):
        print("[警告] local/offline/ 无 jenkins .deb——服务器上无法 apt 装（手动下放进去再传）。")
    if not hpis:
        print("[警告] local/offline/plugins/ 无 .hpi——先跑 fetch_plugins.py（部署会缺插件）。")
    print("  内含：%d 个 .deb、%d 个插件" % (len(debs), len(hpis)))


def pack(out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    print("=== 打包 %s → %s ===" % (CI_ROOT, out))
    warn_if_incomplete()
    with tarfile.open(out, "w:gz") as t:
        # 顶层目录 ci/；filter 排除密钥/缓存/已有 tar.gz（含自身，避免把包打进包）
        t.add(CI_ROOT, arcname=ARC_TOP, filter=lambda ti: None if _excluded(os.path.basename(ti.name)) else ti)
    print("[tar] 完成（%.1f MB）" % (os.path.getsize(out) / 1e6))
    return out


def _parse_target(target):
    """USER@HOST:BASE → (hostpart, base, destdir=base/ci)。"""
    if ":" not in target:
        sys.exit("--scp 需 USER@HOST:PATH 形式（如 root@10.0.0.5:/opt/）。")
    hostpart, base = target.split(":", 1)
    base = base.rstrip("/") or "."
    return hostpart, base, base + "/" + ARC_TOP


def scp_tar(out, target, port, ssh_opts):
    opts = ssh_opts.split() if ssh_opts.strip() else []
    ci_config.run(["scp", "-P", str(port)] + opts + [out, target])
    print("[scp] tar.gz 已送达 %s" % target)
    print("  服务器上：tar xzf %s -C <父目录> → cd .../%s → sudo python3 server/deploy/deploy.py all"
          % (os.path.basename(out), ARC_TOP))


def ship_dir(target, port, ssh_opts):
    """不打包，直接把 tools/ci 传成目标机的 <base>/ci。优先 rsync（带排除），否则 scp -r 逐顶层项。"""
    hostpart, base, destdir = _parse_target(target)
    warn_if_incomplete()
    if shutil.which("rsync"):
        excl = []
        for n in EXCLUDE_NAMES:
            excl += ["--exclude", n]
        for s in ("*.pyc", "*.pyo", "*.tar.gz", "*.tgz"):
            excl += ["--exclude", s]
        rsh = "ssh -p %s %s" % (port, ssh_opts.strip())
        # CI_ROOT 末无斜杠 → 在 base/ 下建出 ci/（与 ARC_TOP 一致）
        ci_config.run(["rsync", "-az"] + excl + ["-e", rsh.strip(), CI_ROOT, "%s:%s/" % (hostpart, base)])
        print("[rsync] 目录已同步到 %s:%s" % (hostpart, destdir))
    else:
        print("[info] 无 rsync，退回 scp -r 逐顶层项（仍排除 config.local.ini 等）。")
        opts = ssh_opts.split() if ssh_opts.strip() else []
        entries = [os.path.join(CI_ROOT, e) for e in sorted(os.listdir(CI_ROOT)) if not _excluded(e)]
        ci_config.run(["ssh", "-p", str(port)] + opts + [hostpart, "mkdir", "-p", destdir])
        ci_config.run(["scp", "-r", "-P", str(port)] + opts + entries + ["%s:%s/" % (hostpart, destdir)])
        print("[scp] 目录已送达 %s:%s" % (hostpart, destdir))
    print("  服务器上：cd %s → sudo python3 server/deploy/deploy.py all" % destdir)


def ship_default():
    """从 config.ini [ship] 拼默认 scp 目标 USER@HOST:DEST；host 空则返回 ('', port, opts)。"""
    cfg = ci_config.load()
    g = lambda k, d="": ci_config.get(cfg, "ship", k, d)  # noqa: E731
    host = g("host").strip()
    port = g("port", "22").strip() or "22"
    opts = g("ssh_opts").strip()
    if not host:
        return "", port, opts
    user, dest = g("user", "root").strip(), g("dest", "/opt").strip() or "/opt"
    return ("%s@%s:%s" % (user, host, dest)) if user else ("%s:%s" % (host, dest)), port, opts


def main():
    d_scp, d_port, d_opts = ship_default()                 # config.ini [ship] 作默认，CLI 覆盖
    ap = argparse.ArgumentParser(description="把 tools/ci 送到目标机：打包 tar.gz 或直接传目录（目标默认读 [ship]）")
    ap.add_argument("--out", default=OUT_DEFAULT, help="tar.gz 输出路径（默认 local/offline/ci-bundle.tar.gz）")
    ap.add_argument("--scp", default=d_scp, metavar="USER@HOST:PATH", help="传到目标（默认 [ship]；空=只打包）")
    ap.add_argument("--dir", action="store_true", help="不打包，直接传目录（rsync 优先，否则 scp -r）")
    ap.add_argument("-p", "--port", default=d_port, help="ssh/scp 端口（默认 [ship].port 或 22）")
    ap.add_argument("--ssh-opts", default=d_opts, help="额外 ssh/scp 选项，如 -i ~/.ssh/id_ed25519")
    args = ap.parse_args()

    if args.dir:
        if not args.scp:
            sys.exit("--dir 需传输目标：填 config.ini [ship] host，或给 --scp USER@HOST:PATH。")
        if not shutil.which("scp") and not shutil.which("rsync"):
            sys.exit("本机无 scp/rsync。")
        ship_dir(args.scp, args.port, args.ssh_opts)
        return

    out = os.path.abspath(args.out)
    pack(out)
    if args.scp:
        if not shutil.which("scp"):
            sys.exit("本机无 scp。")
        scp_tar(out, args.scp, args.port, args.ssh_opts)
    else:
        print("\n只打包（未传输）。搬到服务器后：tar xzf %s -C /opt → cd /opt/%s → "
              "sudo python3 server/deploy/deploy.py all" % (os.path.basename(out), ARC_TOP))


if __name__ == "__main__":
    main()
