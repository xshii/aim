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
    g = lambda s, k, d="": ci_config.get(cfg, s, k, d)  # noqa
    host = g("server", "host", "").strip() or "<本机IP，部署时自动锁定>"
    deps = g("offline", "deps_dir", "").strip() or "<部署目录>/offline（deps_dir 留空时）"
    mcp_on = g("mcp", "enabled", "false").lower() == "true"
    conc = g("runner", "concurrent", "1")
    wall = g("limits", "wall_sec", "120")
    cand = g("gitlab", "candidate_ports", "8929,9080,...")
    rhost = g("remote", "host", "").strip() or "(未配置)"
    dest = g("remote", "dest", "/opt/ci").strip() or "/opt/ci"
    fetch = g("fetch", "mode", "manual")
    wh_on = g("webhook", "enabled", "false").lower() == "true"
    wh_hdr = g("webhook", "auth_header", "X-Auth-Token")
    rootpw = g("gitlab", "root_password_default", "88888888")

    blocks = [
        ("h1", "Quick Deploy · CI 部署速查"),
        ("note", "自动生成（gen_quick_deploy.py 依据 config.ini），改配置后重跑。"),
        ("note", "部署两段式：首次执行机 SSH/SCP bootstrap（admin）→ 服务器本地跑 deploy.py（server）。"),

        ("h2", "准备"),
        ("ol", [
            "非敏感配置填 config.ini：[server] host、[offline] deps_dir、(远端) [remote]、(webhook) [webhook]。",
            "敏感项填 config.local.ini（复制 config.local.ini.example，不入仓）：[proxy] 代理、[secrets] 密钥。",
            "离线依赖放到 %s（见 OFFLINE_DEPENDENCIES.md）；或 [fetch] mode=auto 经代理自动下载。" % deps,
        ]),

        ("h2", "本期要点"),
        ("ul", [
            "部署两段式：首次 SSH/SCP 远端 bootstrap（D-010），之后服务器本地直跑（D-008），日常 HTTP 触发。",
            "GitLab 端口探测：从候选 %s 探测空闲端口锁定，避开被占用端口。" % cand,
            "CI 验证预生成代码：多种验证（合一 check.py）+ 收集 output/状态；运行型仅超时(%ss)+资源限制。" % wall,
            "凭证不入仓：私钥留 ~/.ssh；密钥/token/代理密码经 env 或 config.local.ini。",
        ]),

        ("h2", "A. 首次远端 bootstrap（在执行机上，新机首搭）"),
        ("note", "当前 [remote] host = %s，[fetch] mode = %s。host 为空表示不启用远端、直接看 B 段。"
                 % (rhost, fetch)),
        ("steps", [
            ("A1", "admin 连通性自检（SSH / 远端 python3 / GitLab）",
             "python3 local/admin/deploy_remote.py check", None),
            ("A2", "fetch=auto 时经代理下载依赖到本地 deps_dir",
             "python3 local/admin/deploy_remote.py fetch", None),
            ("A3", "SSH/SCP 推代码 + 依赖到远端 dest",
             "python3 local/admin/deploy_remote.py push", None),
            ("A4", "一条龙：check → fetch → push → 远程跑 deploy.py all（含装 GitLab + 全自动 Runner）",
             "python3 local/admin/deploy_remote.py all",
             "经 ssh -tt 远程执行；非 root 用户先输 sudo 密码，再手输 GitLab root 密码（回车默认 %s）" % rootpw),
        ]),

        ("h2", "B. 服务器本地部署（代码到位后在服务器上执行）"),
        ("steps", [
            ("1", "环境自检（python3 / dpkg / 依赖）",
             "cd %s && python3 server/deploy/deploy.py check" % dest, None),
            ("2", "探测并锁定 GitLab 端口（写回 config）",
             "python3 server/deploy/deploy.py port", None),
            ("3", "离线装 GitLab，过程中交互手输 root 初始密码（回车默认 %s，≥8 位）" % rootpw,
             "python3 server/deploy/deploy.py gitlab", None),
            ("4", "全自动注册 Runner，concurrent=%s（gitlab-rails 建项目+签 token，GitLab 16+ 新流程）" % conc,
             "python3 server/deploy/deploy.py runner", "手动 fallback：deploy.py runner --token <glrt->"),
            ("5", "浏览器打开 http://%s:<锁定端口>，用 root + 手输的密码登录（首登后尽快改密）" % host,
             None, None),
            ("6", "推送含 .gitlab-ci.yml 的仓库，触发流水线（含 qsort 冒烟）", None, None),
        ]),
        ("note", "步骤 1-4 可一条龙：python3 server/deploy/deploy.py all（= check + host + port + gitlab + runner）。"),
        ("note", "deploy.py 需 root：非 root 用户命令前加 sudo（sudo python3 …，脚本会自检拦截）；root 直接运行。"),

        ("h2", "触发构建（webhook / token，HTTP 直连）"),
        ("para", "详见 server/webhook/README.md。git push 自动触发；或 curl + trigger token："),
        ("code", [
            "curl -X POST -F token=<TRIGGER_TOKEN> -F ref=main \\",
            "  http://%s:<port>/api/v4/projects/<id>/trigger/pipeline" % host,
        ]),
    ]

    if wh_on:
        blocks += [
            ("h2", "内源托管 webhook 接入（X-Auth）"),
            ("code", [
                "export WEBHOOK_SECRET=<共享密钥>  GITLAB_TRIGGER_TOKEN=<trigger token>",
                "python3 server/webhook/receiver.py   # 校验 %s 头 → 触发 GitLab" % wh_hdr,
            ]),
            ("note", "内源站把 webhook 指向 http://%s:<listen端口>/，请求头带 %s: <共享密钥>。"
                     % (host, wh_hdr)),
        ]

    if mcp_on:
        blocks += [
            ("h2", "开发端查 CI 状态 / 拉日志（MCP，接 opencode）"),
            ("para", "标准 MCP（stdio）local/mcp/ci_control_server.py 直连 GitLab API，凭证用环境变量："),
            ("code", [
                "GITLAB_API=http://%s:<port>/api/v4 GITLAB_TOKEN=<token> GITLAB_PROJECT=<id> \\" % host,
                "  python3 local/mcp/ci_control_server.py",
            ]),
            ("note", "工具：get_pipeline_status / list_pipelines / get_job_log。"
                     "opencode 接入见 local/mcp/opencode.json.example。"),
        ]

    blocks += [
        ("h2", "qsort 冒烟（验证 CI 真实可用）"),
        ("code", ["python3 server/demo/qsort/smoke_qsort.py     # 编译→限制运行→比对，期望 5/5 通过"]),

        ("h2", "命令速查"),
        ("table", [
            ("远端连通性自检", "python3 local/admin/deploy_remote.py check"),
            ("远端一键 bootstrap", "python3 local/admin/deploy_remote.py all"),
            ("服务器自检", "python3 server/deploy/deploy.py check"),
            ("探测端口", "python3 server/deploy/deploy.py port"),
            ("看锁定端口", "python3 server/deploy/probe_port.py --show"),
            ("服务器一键", "python3 server/deploy/deploy.py all  # check+host+port+gitlab+runner"),
            ("注册 Runner", "python3 server/deploy/deploy.py runner   # 全自动；--token glrt- 手动"),
            ("一致性检查", "python3 checks/consistency.py"),
            ("重新生成本文件", "python3 gen_quick_deploy.py"),
        ]),
        ("note", "仿真并发：%s（串行）。运行超时：%ss。GitLab 候选端口：%s。" % (conc, wall, cand)),

        ("h2", "卸载 / 重置 GitLab（危险：删除全部数据，不可恢复）"),
        ("code", [
            "sudo gitlab-ctl uninstall                    # 停止并禁用所有服务（保留数据）",
            "sudo gitlab-runner unregister --all-runners  # 注销 Runner（可选）",
            "sudo apt-get remove --purge -y gitlab-ce gitlab-runner   # 卸载软件包",
            "sudo rm -rf /etc/gitlab /var/opt/gitlab /var/log/gitlab /opt/gitlab /etc/gitlab-runner",
        ]),
        ("note", "删净后可重新 deploy.py all 全新部署；换端口先清空 config.ini [gitlab] http_port。"),
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
