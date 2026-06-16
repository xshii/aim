# Tasks — 最小骨架（Active）

> 文档层级：**Tasks** — 受 `00_constitution.md` 约束，落地 `02_plan.md`（P0–P5）。
> 供执行者（含弱 AI）逐步照做。只讲「做什么、敲什么、怎么验证」，不解释「为什么」（见 Plan/ADR）。
> 适配内网：纯 python3、离线依赖、角色化目录（server/ 服务器，local/ 客户端）。命令以 `docs/quick_deploy.md` 为准。
>
> **执行总规则（宪法 C-10）：** 1. 严格按编号顺序，不跳步。2. 每步执行后验证，通过才继续。
> 3. 验证失败 → 立即停止报告，不猜测、不绕过、不改配置值。4. 缺信息（凭证/地址）→ 停下来问用户。

## 固定取值（不要更改）

| 项 | 值 |
|----|----|
| 操作系统 | Linux |
| 脚本 | python3（3.8 标准库，不装新库） |
| CI 平台 | 自托管 GitLab CE（离线包安装） |
| 部署 | 首次执行机 SSH/SCP bootstrap → 服务器本地直跑 deploy.py |
| 运行限制 | 超时+资源限制（无强隔离，D-005） |
| 仿真并发 | 1（串行） |
| 凭证 | 私钥/密钥/代理密码不入仓（env / config.local.ini，D-009） |

---

## 阶段 P0 — 首次远端 bootstrap（在执行机上，新机首搭；已在服务器则跳到 P1）

> role=local/admin。私钥留 ~/.ssh，勿入仓（C-1, D-009）。

### T0.1 填配置
- `config.ini`：`[remote] host/user/dest`、`[offline]` 文件名、（auto 下载时）`[fetch] mode=auto` + 各 URL。
- `config.local.ini`（复制 `config.local.ini.example`，**不入仓**）：`[proxy]` 代理（如需）。

### T0.2 连通性自检（admin check）
```bash
python3 local/admin/deploy_remote.py check
```
检查 SSH 可达、远端有 python3。失败则停（C-10）。

### T0.3 取依赖 + 推送 + 远程部署
```bash
python3 local/admin/deploy_remote.py all   # check→fetch→push→远程跑 server/deploy/deploy.py all
```
> ✅ P0 完成判据：远端代码与依赖就位，远端已开始本地部署。

---

## 阶段 P1 — 平台搭建（服务器本地，role=server/deploy）

> 以下命令在【服务器上】执行。若经 P0 远程触发已自动跑过 `deploy.py all`，核对结果即可。

### T1.1 填配置 + 环境自检（server check）
```bash
python3 ci_config.py                          # 打印配置摘要确认
cd /opt/ci && python3 server/deploy/deploy.py check   # 自检 python3/dpkg/离线依赖
```

### T1.2 探测端口 + 装 GitLab
```bash
python3 server/deploy/deploy.py all           # = check + host + port + gitlab
python3 server/deploy/probe_port.py --show    # 查看锁定端口
```
按 `server/deploy/features.md` 编辑 `/etc/gitlab/gitlab.rb`（禁遥测 C-1），`gitlab-ctl reconfigure`。

### T1.3 建项目、拿 Token
浏览器开 `http://<host>:<锁定端口>` → 建 Private 项目 → Settings→CI/CD→Runners 拿 URL+Token。
> ✅ P1 完成判据：GitLab 可访问、私有项目已建、拿到 URL 与 Token。

---

## 阶段 P2 — 运行限制验证（role=server/harness）

```bash
python3 server/harness/limited_run.py /tmp/lr /bin/echo "LIMITED_OK"   # 含 mem/cpu/wall 限制行
python3 server/harness/limited_run.py /tmp/lr sleep 999 ; echo "rc=$?" # 超时后 rc=124
```
> ✅ P2 完成判据：限制运行器可用、超时生效。

---

## 阶段 P3 — Runner 注册（role=server/runner）

> 前置：GitLab 已装好（deploy.py gitlab/all）。GitLab 16+ 新流程无需手动拿 token。

```bash
python3 server/deploy/deploy.py runner   # gitlab-rails 建项目+签 token，全自动；--token glrt- 手动 fallback
```
shell executor、tag=sim-license、concurrent=1（注册 token 自动脱敏，不落日志）。
验证：`gitlab-runner list` 显示 sim-runner；`grep '^concurrent' /etc/gitlab-runner/config.toml` 为 1。
> ✅ P3 完成判据：Runner 注册成功、tag 正确、concurrent=1。

---

## 阶段 P4 — 流水线 + qsort 冒烟（role=server/pipeline+demo）

```bash
cp tools/ci/server/pipeline/.gitlab-ci.yml ./.gitlab-ci.yml   # resource_group 串行不可删（C-3）
python3 tools/ci/server/demo/qsort/smoke_qsort.py             # 期望 5/5 通过，status=ok
```
推送后在 Pipelines 看到 smoke→run→sim→compare→quality→report 全绿。
> ✅ P4 完成判据：qsort 冒烟 5/5；CI 各阶段绿；simulate 串行不并发。

---

## 阶段 P5 — 接入（role=server/webhook + local/mcp）

### T5.1 内源 webhook（X-Auth，如需）
配 `config.ini [webhook] enabled=true`、`config.local.ini [secrets]` 密钥，启 `server/webhook/receiver.py`。
内源站把 webhook 指向接收器、请求头带 `X-Auth-Token`。详见 `server/webhook/README.md`。

### T5.2 MCP 查询（opencode）
开发端按 `local/mcp/opencode.json.example` 配 opencode，凭证用环境变量。验证 `get_pipeline_status` 可用。

### T5.3 一致性检查
```bash
python3 tools/ci/checks/consistency.py        # 期望退出码 0、无 ERROR
```

---

## 禁止事项（宪法，任何时候都不要做）

1. 不删/改 `resource_group: sim-license-lock`，不把 concurrent 改成大于 1（C-3）。
2. 运行型验证须保留超时+资源限制（防卡死/资源耗尽）。
3. 不开启 GitLab 对外遥测/上报（C-1）。
4. 不把私钥/密钥/trigger token/代理明文密码写入仓库（C-1, D-009）。
5. 不编造 GitLab 地址、Token、依赖包、URL——缺什么停下来问（C-10）。
6. 任何验证失败，停下来报告，不猜测、不绕过（C-10）。
