#!/usr/bin/env python3
# implements: NFR-3
"""
轻量限制运行器（role=server/harness，Python 3.8 标准库，零依赖）。
不做强隔离，只加 超时 + 资源限制（内存/CPU/文件数）。适用前提：CI 在封闭内网、专用机器，
代码为预生成成品（非实时不可信生成），故仅防资源耗尽与卡死（D-005）。
用法: python3 limited_run.py <workdir> <cmd...>   返回被执行命令退出码；超时返回 124。
"""
import os
import resource
import subprocess
import sys

_R = os.path.dirname(os.path.abspath(__file__))
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
sys.path.insert(0, _R)
import ci_config  # noqa: E402


def main():
    if len(sys.argv) < 3:
        print("用法: limited_run.py <workdir> <cmd...>", file=sys.stderr)
        sys.exit(1)
    workdir = sys.argv[1]
    cmd = sys.argv[2:]

    cfg = ci_config.load()
    s = cfg["limits"] if cfg.has_section("limits") else {}
    mem = int(s.get("mem_mb", "2048")) * 1024 * 1024
    cpu = int(s.get("cpu_sec", "60"))
    nofile = int(s.get("nofile", "256"))
    wall = int(s.get("wall_sec", "120"))

    def set_limits():
        # 逐项 best-effort：目标机 Linux 三项全生效；个别平台不支持某项（如 macOS 的
        # RLIMIT_AS）时跳过该项而非让子进程无法启动。
        for what, val in ((resource.RLIMIT_AS, mem),
                          (resource.RLIMIT_CPU, cpu),
                          (resource.RLIMIT_NOFILE, nofile)):
            try:
                resource.setrlimit(what, (val, val))
            except (ValueError, OSError):
                pass

    print("[limited_run] workdir=%s mem=%dMB cpu=%ds wall=%ds"
          % (workdir, mem // 1024 // 1024, cpu, wall), file=sys.stderr)
    try:
        rc = subprocess.call(cmd, cwd=workdir, preexec_fn=set_limits, timeout=wall)
        sys.exit(rc)
    except subprocess.TimeoutExpired:
        print("[limited_run] 超时(%ds)，已终止。" % wall, file=sys.stderr)
        sys.exit(124)


if __name__ == "__main__":
    main()
