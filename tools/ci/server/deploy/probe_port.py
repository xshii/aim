#!/usr/bin/env python3
# implements: FR-15
"""
GitLab 监听端口探测 + 锁定（role=server/deploy，Python 3.8 标准库，零依赖）。
服务器部分端口被其他 CI 服务占用，本脚本从候选探测一个空闲端口并锁定到 config.ini
[gitlab] http_port，供后续安装/访问统一使用（单一事实源 C-7）。

锁定语义（避免重复探测换端口）：
  http_port 已有值 → 默认复用；为空+auto_lock=true → 探测并锁定；
  为空+auto_lock=false → 报错要求手动填；--force → 强制重探（会换端口，慎用）。
用法: probe_port.py [--show|--force]
"""
import argparse
import os
import socket
import sys

_R = os.path.dirname(os.path.abspath(__file__))
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
sys.path.insert(0, _R)
import ci_config  # noqa: E402


def is_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def probe(ports):
    for p in ports:
        if is_free(p):
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--force", action="store_true", help="强制重新探测（会换端口）")
    args = ap.parse_args()
    cfg = ci_config.load()

    locked = ci_config.get(cfg, "gitlab", "http_port", "").strip()
    auto_lock = ci_config.get(cfg, "gitlab", "auto_lock", "true").lower() == "true"

    if args.show:
        print("当前锁定 http_port =", locked or "(未锁定)")
        print("auto_lock =", auto_lock)
        return

    if locked and not args.force:
        if not is_free(int(locked)):
            print("[提醒] 已锁定端口 %s 当前被占用。如需更换用 --force（会改 external_url）。"
                  % locked, file=sys.stderr)
        print("已锁定 http_port=%s，复用（未重新探测）。" % locked)
        return

    if not locked and not auto_lock and not args.force:
        print("http_port 为空且 auto_lock=false：请在 config.ini [gitlab] 手动填 http_port。",
              file=sys.stderr)
        sys.exit(1)

    ports = [int(p.strip()) for p in
             ci_config.get(cfg, "gitlab", "candidate_ports",
                           "8929,9080,9443,18080,28080").split(",") if p.strip()]
    chosen = probe(ports)
    if chosen is None:
        print("候选端口都被占用：%s。请在 config.ini 增加 candidate_ports。" % ports, file=sys.stderr)
        sys.exit(1)

    if args.force and locked and str(chosen) != locked:
        print("[警告] 强制重探：端口由 %s 换为 %d。需同步更新 GitLab external_url！"
              % (locked, chosen), file=sys.stderr)

    ci_config.set_value("gitlab", "http_port", str(chosen))
    print("已探测并锁定 GitLab 端口：%d（写入 config.ini）" % chosen)


if __name__ == "__main__":
    main()
