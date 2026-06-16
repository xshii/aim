#!/usr/bin/env python3
# implements: FR-11
"""自动生成 docs/quick_deploy.md（角色中立的共享工具，Python 3.8 标准库）。改 config 后重跑。
  python3 gen_quick_deploy.py          # 生成
  python3 gen_quick_deploy.py --show   # 生成并把内容打印到 stdout（便于直接查看）
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ci_config  # noqa: E402

OUT = os.path.join(HERE, "docs", "quick_deploy.md")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="生成后把内容打印到 stdout")
    args = ap.parse_args()
    cfg = ci_config.load()
    g = lambda s, k, d="": ci_config.get(cfg, s, k, d)  # noqa
    host = g("server", "host", "").strip() or "<本机IP，部署时自动锁定>"
    deps = g("offline", "deps_dir", "").strip() or "<部署目录>/offline（deps_dir 留空时）"
    mcp_on = g("mcp", "enabled", "false").lower() == "true"
    concurrent = g("runner", "concurrent", "1")
    wall = g("limits", "wall_sec", "120")
    cand = g("gitlab", "candidate_ports", "8929,9080,...")
    remote_host = g("remote", "host", "").strip()
    dest = g("remote", "dest", "/opt/ci").strip() or "/opt/ci"   # 部署目录，按 config 联动
    fetch_mode = g("fetch", "mode", "manual")
    wh_on = g("webhook", "enabled", "false").lower() == "true"
    wh_hdr = g("webhook", "auth_header", "X-Auth-Token")

    mcp_block = ""
    if mcp_on:
        mcp_block = (
            "\n## 开发端查 CI 状态 / 拉日志（MCP，接 opencode）\n\n"
            "标准 MCP（stdio）`local/mcp/ci_control_server.py` 直连 GitLab API，凭证用环境变量：\n"
            "```bash\n"
            "GITLAB_API=http://%s:<port>/api/v4 GITLAB_TOKEN=<token> GITLAB_PROJECT=<id> \\\n"
            "  python3 local/mcp/ci_control_server.py\n"
            "```\n工具：get_pipeline_status / list_pipelines / get_job_log。"
            "opencode 接入见 `local/mcp/opencode.json.example`。\n" % host)

    wh_block = ""
    if wh_on:
        wh_block = (
            "\n## 内源托管 webhook 接入（X-Auth，FR-19）\n\n"
            "```bash\n"
            "export WEBHOOK_SECRET=<共享密钥>  GITLAB_TRIGGER_TOKEN=<trigger token>\n"
            "python3 server/webhook/receiver.py   # 校验 %s 头 → 触发 GitLab\n"
            "```\n内源站把 webhook 指向 `http://%s:<listen端口>/`，请求头带 `%s: <共享密钥>`。\n"
            % (wh_hdr, host, wh_hdr))

    c = """# Quick Deploy（自动生成，请勿手改）

> 由 `gen_quick_deploy.py` 依据 `config.ini` 生成。改配置后重新生成。
> 部署两段式：**首次执行机 SSH/SCP bootstrap（admin）→ 服务器本地跑 `deploy.py`（server）**。

## 准备

1. 非敏感配置填 `config.ini`：`[server] host`、`[offline] deps_dir`、（远端）`[remote]`、（webhook）`[webhook]`。
2. 敏感项填 `config.local.ini`（复制 `config.local.ini.example`，**不入仓**）：`[proxy]` 代理、`[secrets]` 密钥。
3. 离线依赖放到 `{deps}`（见 `OFFLINE_DEPENDENCIES.md`）；或 `[fetch] mode=auto` 经代理自动下载。

## 本期要点

- **部署两段式**：首次 SSH/SCP 远端 bootstrap（D-010），之后服务器本地直跑（D-008），日常 HTTP 触发。
- **GitLab 端口探测**：从候选 `{cand}` 探测空闲端口锁定，避开被占用端口。
- **CI 验证预生成代码**：多种验证（合一 `check.py`）+ 收集 output/状态；运行型仅超时({wall}s)+资源限制。
- **凭证不入仓**：私钥留 ~/.ssh；密钥/token/代理密码经 env 或 `config.local.ini`。

---

## A. 首次远端 bootstrap（在执行机上，新机首搭）

> 当前 `[remote] host` = `{rhost}`，`[fetch] mode` = `{fetch}`。host 为空表示不启用远端、直接看 B 段。

| 步 | 命令 | 说明 |
|----|------|------|
| A1 | `python3 local/admin/deploy_remote.py check` | admin 连通性自检（SSH/远端 python3/GitLab） |
| A2 | `python3 local/admin/deploy_remote.py fetch` | fetch=auto 时经代理下载依赖到本地 deps_dir |
| A3 | `python3 local/admin/deploy_remote.py push`  | SSH/SCP 推代码 + 依赖到远端 dest |
| A4 | `python3 local/admin/deploy_remote.py all`   | 一条龙：check→fetch→push→远程跑 deploy.py all |

## B. 服务器本地部署（代码到位后在服务器上执行）

| 步 | 命令 | 说明 |
|----|------|------|
| 1 | `cd {dest} && python3 server/deploy/deploy.py check` | 环境自检（python3 / dpkg / 依赖） |
| 2 | `python3 server/deploy/deploy.py port` | 探测并锁定 GitLab 端口（写回 config） |
| 3 | `python3 server/deploy/deploy.py gitlab` | 离线装 GitLab（external_url=host:锁定端口） |
| 4 | 浏览器开 `http://{host}:<锁定端口>` | 建 Private 项目，拿 Runner Token |
| 5 | `python3 server/deploy/deploy.py runner --url U --token T` | 注册 Runner，concurrent={conc}（串行；token 脱敏） |
| 6 | 推送含 `.gitlab-ci.yml` 的仓库 | 触发流水线，含 qsort 冒烟阶段 |

> 步骤 1-3 可一条龙：`python3 server/deploy/deploy.py all`（= check + host + port + gitlab）。

---

## 触发构建（webhook / token，HTTP 直连）

详见 `server/webhook/README.md`。git push 自动触发；或 curl + trigger token：
```bash
curl -X POST -F token=<TRIGGER_TOKEN> -F ref=main \\
  http://{host}:<port>/api/v4/projects/<id>/trigger/pipeline
```
{wh}{mcp}---

## qsort 冒烟（验证 CI 真实可用）

```bash
python3 server/demo/qsort/smoke_qsort.py     # 编译→限制运行→比对，期望 5/5 通过
```

## 命令速查

| 目的 | 命令 |
|------|------|
| 远端连通性自检 | `python3 local/admin/deploy_remote.py check` |
| 远端一键 bootstrap | `python3 local/admin/deploy_remote.py all` |
| 服务器自检 | `python3 server/deploy/deploy.py check` |
| 探测端口 | `python3 server/deploy/deploy.py port`（或 `server/deploy/probe_port.py`） |
| 看锁定端口 | `python3 server/deploy/probe_port.py --show` |
| 服务器一键(check+host+port+gitlab) | `python3 server/deploy/deploy.py all` |
| 注册 Runner | `python3 server/deploy/deploy.py runner --url U --token T` |
| 一致性检查 | `python3 checks/consistency.py` |
| 重新生成本文件 | `python3 gen_quick_deploy.py` |

> 仿真并发：`{conc}`（串行）。运行超时：`{wall}s`。GitLab 候选端口：`{cand}`。
""".format(deps=deps, cand=cand, wall=wall, host=host, conc=concurrent, dest=dest,
           rhost=remote_host or "(未配置)", fetch=fetch_mode, wh=wh_block, mcp=mcp_block)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(c)
    print("已生成：%s" % OUT)
    if args.show:
        print()
        sys.stdout.write(c)


if __name__ == "__main__":
    main()
