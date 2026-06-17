#!/usr/bin/env python3
# implements: FR-11
"""生成 docs/quick_deploy.md 并打印 CLI 友好版（角色中立共享工具，Python 3.8 标准库）。改 config 后重跑。
  python3 gen_quick_deploy.py            # 生成文件 + 终端打印（TTY 下自动着色）
  python3 gen_quick_deploy.py --quiet    # 只生成文件，不打印
文件为无颜色纯文本；终端输出仅在 TTY 着色，重定向/管道时自动去色。
"""
import argparse
import os
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ci_config  # noqa: E402

OUT = os.path.join(HERE, "docs", "quick_deploy.md")
WIDTH = 60


def _c(s, code, color):
    """着色（color=True 时包 ANSI），否则原样返回——同一份内容渲染文件/终端两态。"""
    return "\033[%sm%s\033[0m" % (code, s) if color else s


def _dw(s):
    """显示宽度：CJK 全角字符计 2，用于按终端列宽对齐。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _pad(s, width):
    return s + " " * max(0, width - _dw(s))


def render(blocks, color):
    out = []
    for kind, payload in blocks:
        if kind == "h1":
            bar = "═" * WIDTH
            out += [_c(bar, "36", color), _c(" " + payload, "1;36", color),
                    _c(bar, "36", color), ""]
        elif kind == "h2":
            out += ["", _c("▶ " + payload, "1;33", color), _c("─" * WIDTH, "33", color)]
        elif kind == "para":
            out += [payload, ""]
        elif kind == "note":
            out += [_c("  › " + payload, "2", color), ""]
        elif kind == "ol":
            for i, it in enumerate(payload, 1):
                out.append("  %s %s" % (_c("%d." % i, "36", color), it))
            out.append("")
        elif kind == "ul":
            for it in payload:
                out.append("  %s %s" % (_c("•", "36", color), it))
            out.append("")
        elif kind == "steps":
            for label, desc, cmd, extra in payload:
                out.append("  %s  %s" % (_c("%-2s" % label, "1;36", color), desc))
                if cmd:
                    out.append("      " + _c(cmd, "32", color))
                if extra:
                    out.append("      " + _c("↳ " + extra, "33", color))
            out.append("")
        elif kind == "code":
            for ln in payload:
                out.append("    " + _c(ln, "32", color))
            out.append("")
        elif kind == "table":
            w = max(_dw(left) for left, _ in payload)
            for left, right in payload:
                out.append("  %s  %s" % (_pad(left, w), _c(right, "32", color)))
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def build_blocks(cfg):
    g = lambda s, k, d="": ci_config.get(cfg, s, k, d)  # noqa: E731
    listen = g("webhook", "listen", "0.0.0.0:8080")
    port = listen.rsplit(":", 1)[-1]
    conc = g("scheduler", "concurrency", "1")
    git_auth = g("scheduler", "git_auth", "ssh")
    wall = g("limits", "wall_sec", "120")
    mcp_on = g("mcp", "enabled", "false").lower() == "true"
    rhost = g("remote", "host", "").strip() or "(未配置)"
    dest = g("remote", "dest", "/opt/ci").strip() or "/opt/ci"

    blocks = [
        ("h1", "Quick Deploy · 自研 CI 调度器"),
        ("note", "自动生成（gen_quick_deploy.py 依据 config.ini），改配置后重跑。"),
        ("note", "纯 python3 标准库调度器，替代 GitLab（D-013）："
                 "webhook 入队 → 单 worker 串行 checkout+评测 → sqlite → MCP/网页查。"),

        ("h2", "准备"),
        ("ol", [
            "config.ini：[scheduler]（db/工作区/concurrency/git_auth）、[webhook] listen、[remote]（远端 bootstrap）。",
            "config.local.ini（不入仓）：[secrets] webhook_secret；[scheduler] ssh_key 或 http_token（git checkout 用）。",
            "代码托管用内网现有仓库（不新建）；仓库后台配 WebHook 指向本服务（见 C 段）。",
        ]),

        ("h2", "本期要点"),
        ("ul", [
            "组件：webhook 接收器(+只读 UI) + 单 worker 串行调度 + sqlite 任务库 + MCP（接 opencode）。",
            "仿真串行：concurrency=%s（单 worker 天然串行 = License 数）。" % conc,
            "webhook 端口仅限 80-90 / 443 / 8080-8090；认证头 X-Devcloud-Token（平台固定，见 constants.py）。",
            "纯标准库零依赖、内网离线；凭证不入仓（ssh_key/token/密钥经 config.local.ini）。git_auth=%s。" % git_auth,
        ]),

        ("h2", "A. 首次远端 bootstrap（在执行机上，可选）"),
        ("note", "当前 [remote] host = %s。host 为空 = 不用远端，直接在服务器跑 B 段。" % rhost),
        ("steps", [
            ("A1", "admin 连通性自检（SSH / 远端 python3 / 管理员权限）",
             "python3 local/admin/deploy_remote.py check", None),
            ("A2", "SSH/SCP 推代码到远端 %s（纯 python，无 .deb）" % dest,
             "python3 local/admin/deploy_remote.py push", None),
            ("A3", "一条龙：check → push → 远程跑 deploy.py all",
             "python3 local/admin/deploy_remote.py all",
             "非 root 用户经 ssh -tt 交互输 sudo 密码"),
        ]),

        ("h2", "B. 服务器本地部署（需 root）"),
        ("steps", [
            ("1", "环境自检（python3 / git / systemctl / root / webhook 端口范围）",
             "sudo python3 server/deploy/deploy.py check", None),
            ("2", "初始化 sqlite + 工作区/日志目录",
             "sudo python3 server/deploy/deploy.py init", None),
            ("3", "安装并启用 systemd 服务（ci-webhook + ci-worker）",
             "sudo python3 server/deploy/deploy.py service", None),
        ]),
        ("note", "步骤 1-3 一条龙：sudo python3 server/deploy/deploy.py all。"),

        ("h2", "C. 接入内网代码仓 WebHook"),
        ("ol", [
            "仓库后台 → WebHook → URL 填 http://<服务器IP>:%s/" % port,
            "Token 填共享密钥（= config.local.ini [secrets] webhook_secret），平台据此发 X-Devcloud-Token 头。",
            "订阅事件：Push Hook。push 即触发评测。",
        ]),

        ("h2", "触发与查看结果"),
        ("para", "push 代码 → 平台 POST webhook → 入队 → worker 串行 checkout+评测 → 存 sqlite。查看："),
        ("code", [
            "浏览器:   http://<服务器IP>:%s/            # 任务列表/详情/日志（只读）" % port,
            "命令行:   curl http://<服务器IP>:%s/tasks/<id>/log" % port,
            "服务日志: journalctl -u ci-webhook -u ci-worker -f",
        ]),
    ]

    if mcp_on:
        blocks += [
            ("h2", "开发端 MCP（接 opencode）查任务状态/日志"),
            ("code", ["CI_DB_PATH=%s/var/ci.db python3 local/mcp/ci_control_server.py" % dest]),
            ("note", "工具：get_task_status / list_tasks / get_task_log。"
                     "opencode 接入见 local/mcp/opencode.json.example。"),
        ]

    blocks += [
        ("h2", "端到端 demo（验证链路）"),
        ("code", ["python3 server/scheduler/smoke_scheduler.py   "
                  "# 建临时仓 → 入队 → checkout → 编译 qsort+比对 → passed"]),

        ("h2", "命令速查"),
        ("table", [
            ("远端 bootstrap", "python3 local/admin/deploy_remote.py all"),
            ("服务器一键部署", "sudo python3 server/deploy/deploy.py all"),
            ("环境自检", "sudo python3 server/deploy/deploy.py check"),
            ("看服务状态", "systemctl status ci-webhook ci-worker"),
            ("看任务(网页)", "http://<host>:%s/" % port),
            ("端到端 demo", "python3 server/scheduler/smoke_scheduler.py"),
            ("一致性检查", "python3 checks/consistency.py"),
            ("重新生成本文件", "python3 gen_quick_deploy.py"),
        ]),
        ("note", "仿真并发：%s（单 worker 串行）。运行超时：%ss。webhook 端口白名单：80-90/443/8080-8090。"
                 % (conc, wall)),

        ("h2", "卸载 / 重置（停服务 + 清数据）"),
        ("code", [
            "sudo systemctl disable --now ci-webhook ci-worker",
            "sudo rm -f /etc/systemd/system/ci-webhook.service /etc/systemd/system/ci-worker.service",
            "sudo systemctl daemon-reload",
            "rm -rf %s/var      # 删 sqlite/工作区/日志（谨慎，不可恢复）" % dest,
        ]),
    ]
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="只生成文件，不在终端打印")
    args = ap.parse_args()

    blocks = build_blocks(ci_config.load())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(render(blocks, color=False))           # 文件：纯文本无色
    print("已生成：%s\n" % OUT)
    if not args.quiet:
        sys.stdout.write(render(blocks, color=sys.stdout.isatty()))  # 终端：TTY 着色


if __name__ == "__main__":
    main()
