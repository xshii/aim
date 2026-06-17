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
    jport = g("jenkins", "http_port", "8080")
    job = g("jenkins", "job_name", "qsort-eval")
    admin = g("jenkins", "admin_user", "admin")
    wport = g("webhook", "listen", "0.0.0.0:8090").rsplit(":", 1)[-1]
    git_auth = g("webhook", "git_auth", "ssh")
    deps = g("offline", "deps_dir", "/opt/ci/local/offline")
    jdeb = g("fetch", "jenkins_deb", "jenkins_2.555.1_all.deb")
    rhost = g("remote", "host", "").strip() or "(未配置)"
    dest = g("remote", "dest", "/opt/ci").strip() or "/opt/ci"

    blocks = [
        ("h1", "Quick Deploy · Jenkins CI（.deb 离线）"),
        ("note", "自动生成（gen_quick_deploy.py 依据 config.ini），改配置后重跑。"),
        ("note", "CI 框架=Jenkins（.deb apt 安装）：webhook 适配器校验 token → 调 Jenkins buildWithParameters；"
                 "Jenkins(JCasC 预配) 跑 qsort 功能+性能评测；官方 MCP 插件接 opencode。代码托管仍用内网现有仓库。"),

        ("h2", "准备"),
        ("ol", [
            "有网机：跑 local/admin/fetch_offline.py 产出离线件到 tools/ci/local/offline/（%s + plugin-cli jar + Java21 的 .deb）。" % jdeb,
            "config.ini 客户端：[fetch]（版本/URL）、[remote]（远端 bootstrap）。",
            "config.ini 服务端：[jenkins]（端口/job/admin/内源 UC）、[offline] deps_dir、[webhook] listen、[limits]。",
            "config.local.ini（不入仓）：[secrets] webhook_secret + jenkins_admin_password。",
            "代码托管用内网现有仓库（不新建）；仓库后台配 WebHook 指向 webhook 适配器（见 C 段）。",
        ]),

        ("h2", "本期要点"),
        ("ul", [
            "组件：webhook 适配器(触发) + Jenkins(.deb，JCasC 预配 job/串行/auto-cancel) + 官方 MCP 插件。",
            "仿真串行：numExecutors=1（固定，D-003；单节点同一时刻仅 1 个构建 = License 数）。",
            "Jenkins 端口 %s、webhook 端口 %s，均仅限 80-90 / 443 / 8080-8090；认证头 X-Devcloud-Token。" % (jport, wport),
            "离线：jenkins/java 的 .deb apt 安装；插件由服务器从内源 UC 装；JCasC 配置即代码；凭证不入仓。git_auth=%s。" % git_auth,
        ]),

        ("h2", "离线件获取（有网机，一次性）"),
        ("steps", [
            ("F1", "改 config.ini [fetch] 版本/URL 为内网可下版本，下 .deb + plugin-cli jar",
             "python3 local/admin/fetch_offline.py", "走代理：export HTTPS_PROXY=..."),
            ("F2", "Java：把 JDK/JRE 21 的 .deb 放进 tools/ci/local/offline/（[fetch] java_deb_url 为空时手动放）",
             None, None),
            ("F3", "产出在 tools/ci/local/offline/（大文件已 .gitignore），随 bootstrap 推送或手动放到 deps_dir=%s" % deps,
             None, None),
        ]),

        ("h2", "A. 首次远端 bootstrap（在执行机上，可选）"),
        ("note", "当前 [remote] host = %s。host 为空 = 不用远端，直接在服务器跑 B 段。" % rhost),
        ("steps", [
            ("A1", "admin 连通性自检（SSH / 远端 python3 / 管理员权限）",
             "python3 local/admin/deploy_remote.py check", None),
            ("A2", "SSH/SCP 推代码 + offline/ 到远端 %s" % dest,
             "python3 local/admin/deploy_remote.py push", None),
            ("A3", "一条龙：check → push → 远程跑 deploy.py all",
             "python3 local/admin/deploy_remote.py all",
             "非 root 用户经 ssh -tt 交互输 sudo 密码"),
        ]),

        ("h2", "B. 服务器本地部署（需 root）"),
        ("steps", [
            ("1", "环境自检（root / apt-get / dpkg / 端口范围 / 离线 .deb 就位）",
             "sudo python3 server/deploy/deploy.py check", None),
            ("2", "apt 装 jenkins/java 的 .deb + 从内源 UC 装插件 + 渲染 JCasC",
             "sudo python3 server/deploy/deploy.py init", None),
            ("3", "写密钥环境文件 + Jenkins systemd drop-in + 启用 jenkins/ci-webhook",
             "sudo python3 server/deploy/deploy.py service", None),
        ]),
        ("note", "步骤 1-3 一条龙：sudo python3 server/deploy/deploy.py all。"),

        ("h2", "C. 接入内网代码仓 WebHook"),
        ("ol", [
            "仓库后台 → WebHook → URL 填 http://<服务器IP>:%s/（webhook 适配器，非 Jenkins 端口）" % wport,
            "Token 填共享密钥（= config.local.ini [secrets] webhook_secret），平台据此发 X-Devcloud-Token 头。",
            "订阅事件：Push Hook。push 即触发 Jenkins job=%s 评测。" % job,
        ]),

        ("h2", "触发与查看结果"),
        ("para", "push → 适配器校验 token+解析 payload → Jenkins buildWithParameters(GIT_URL/GIT_SHA/BRANCH)。查看："),
        ("code", [
            "Jenkins UI: http://<服务器IP>:%s/            # 构建列表/控制台日志/产物（admin 登录）" % jport,
            "适配器日志: journalctl -u ci-webhook -f",
            "Jenkins 日志: journalctl -u jenkins -f",
        ]),

        ("h2", "开发端 MCP（官方 mcp-server 插件，接 opencode）"),
        ("note", "Jenkins 装 mcp-server 插件后自带 MCP 端点，无需自写。opencode 接入见 local/mcp/opencode.json.example。"),
        ("code", ["MCP 端点: http://<服务器IP>:%s/mcp-server/   # 用 admin + API token 认证" % jport]),

        ("h2", "本机可验项（无需真 Jenkins）"),
        ("code", [
            "python3 server/demo/qsort/eval.py server/demo/qsort   # qsort 功能+性能评测",
            "python3 server/webhook/test_receiver.py               # 适配器单测（mock Jenkins）",
            "python3 checks/consistency.py                          # spec↔代码 一致性闸门",
        ]),

        ("h2", "命令速查"),
        ("table", [
            ("有网机下离线件", "python3 local/admin/fetch_offline.py"),
            ("远端 bootstrap", "python3 local/admin/deploy_remote.py all"),
            ("服务器一键部署", "sudo python3 server/deploy/deploy.py all"),
            ("环境自检", "sudo python3 server/deploy/deploy.py check"),
            ("看服务状态", "systemctl status jenkins ci-webhook"),
            ("Jenkins UI", "http://<host>:%s/" % jport),
            ("一致性检查", "python3 checks/consistency.py"),
            ("重新生成本文件", "python3 gen_quick_deploy.py"),
        ]),
        ("note", "仿真并发：numExecutors=1（串行，D-003）。admin 用户：%s。端口白名单：80-90/443/8080-8090。"
                 % admin),

        ("h2", "卸载 / 重置（停服务 + 清数据）"),
        ("code", [
            "sudo systemctl disable --now jenkins ci-webhook",
            "sudo apt-get remove --purge -y jenkins                    # 卸 Jenkins（含 jenkins.service）",
            "sudo rm -f /etc/systemd/system/ci-webhook.service /etc/ci-jenkins.env",
            "sudo rm -rf /etc/systemd/system/jenkins.service.d         # 删端口/JCasC drop-in",
            "sudo systemctl daemon-reload",
            "sudo rm -rf /var/lib/jenkins                              # 删 JENKINS_HOME（谨慎，不可恢复）",
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
