# 自研极简 CI 调度器设计（替代 GitLab CE）

> 状态：设计已批准，待实现。本文件是本次重构的 spec。
> 决策：完全推倒 GitLab 路线，不做前向兼容（见 D-013）。

## 1. 背景与动机

原方案用 GitLab CE 作为「代码托管 + CI」一体平台（D-002）。但实际约束变化：

- **内网已有代码托管平台**（Bitbucket / SVN / 自研），且**不允许新建托管仓库**——装 GitLab 等于新建一个托管仓库，被禁止。
- 真正需要的只是一个**纯评测 CI 引擎**：接收触发 → 串行跑评测 → 出报告 → 可查状态。
- GitLab（omnibus 重、4GB+ 内存）与 Jenkins（JVM + 内网离线插件地狱、不托管代码）对这个窄场景都是杀鸡用牛刀。

**结论**：自研一个极简调度器，纯 python3 标准库、零依赖，复用已有的 webhook 接收器与评测 harness。

## 2. 目标与非目标

**目标**
- webhook 触发评测（对接任意托管平台：Bitbucket/SVN/自研）
- 仿真任务严格串行（License 数 = 并发数）
- 复用现有 `server/harness/` 评测逻辑，零改动核心
- 任务状态/历史持久化，可经 MCP 查询（接 opencode）
- 纯 python3 标准库、零第三方依赖、内网离线、完全自托管（沿用宪法 C-1/C-4/D-004）

**非目标**
- 不托管代码（用内网现有仓库）
- 不做 Web UI（状态靠 MCP + 日志文件 + CLI）
- 不做通用 CI（只服务「串行评测」这一窄场景）
- 不做分布式/多机调度（单机单 worker 起步）

## 3. 架构总览

```
内网仓库 push/commit
      │ webhook(HTTP, X-Auth 共享密钥)
      ▼
┌─────────────────────┐
│ receiver.py          │  校验 X-Auth → 解析 repo+ref → 入队
└─────────┬───────────┘
          │ enqueue
          ▼
   ┌──────────────┐   claim(原子)   ┌──────────────────────────────┐
   │ sqlite: tasks │ ◀────────────── │ worker.py（单进程，串行）      │
   └──────────────┘ ──update────▶   │  1. checkout repo@ref          │
          ▲                          │  2. harness: check.py(run/sim/ │
          │ 查询                     │     compare/quality)           │
          │                          │  3. report.py + 质量门禁        │
┌─────────┴───────────┐             │  4. 更新 sqlite + 写日志文件     │
│ ci_control_server.py │             └──────────────────────────────┘
│ (MCP stdio, 查 sqlite)│
└─────────▲───────────┘
          │ stdio (MCP)
   开发端 opencode / AI 助手
```

## 4. 组件设计

### 4.1 任务队列 `server/scheduler/db.py`（新增）

sqlite（标准库 `sqlite3`，零依赖）。schema：

```sql
CREATE TABLE IF NOT EXISTS tasks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  repo        TEXT    NOT NULL,
  ref         TEXT    NOT NULL,
  state       TEXT    NOT NULL DEFAULT 'queued',  -- queued/running/passed/failed/error
  created_at  TEXT    NOT NULL,
  started_at  TEXT,
  finished_at TEXT,
  exit_code   INTEGER,
  log_path    TEXT
);
CREATE INDEX IF NOT EXISTS idx_state ON tasks(state);
```

函数：
- `init(db_path)`：建表（幂等）
- `enqueue(repo, ref) -> id`：插入 queued
- `claim() -> row|None`：`BEGIN IMMEDIATE` 事务内 `SELECT ... WHERE state='queued' ORDER BY id LIMIT 1` 后置 running（原子，支持未来多 worker）
- `finish(id, state, exit_code, log_path)`：置终态
- `reset_stale()`：worker 启动时把残留 `running`（上次崩溃）标 `error`，避免悬挂
- `get(id)` / `list(limit)` / `tail_log(id)`：供 MCP 查询

状态机：`queued → running → {passed|failed|error}`。`passed/failed` = 评测结果（门禁过/不过）；`error` = 系统错（checkout 失败、超时、崩溃）。

### 4.2 worker `server/scheduler/worker.py`（新增）

单进程守护循环：

```
reset_stale()
loop:
  row = claim()
  if not row: sleep(poll_interval); continue
  log = open(log_dir/<id>.log)
  try:
    checkout(row.repo, row.ref, workspace)      # 4.4
    rc = run_harness(workspace, log)            # 调 check.py 各阶段 + report.py
    finish(id, 'passed' if rc==0 else 'failed', rc, log_path)
  except Exception:
    finish(id, 'error', None, log_path)
```

- `concurrency`（config，默认 1）：单 worker = 仿真串行（FR-3）。N License → systemd 起 N 个 worker 实例；`claim()` 的 `BEGIN IMMEDIATE` 保证不重复取。
- 经 systemd 守护，崩溃自动重启；重启时 `reset_stale()` 清悬挂。

### 4.3 webhook 接收器 `server/webhook/receiver.py`（改造）

- 保留：请求头 **`X-Auth-Token`** 共享密钥常量时间校验（`hmac.compare_digest`）。认证头名**固定为 `X-Auth-Token`**（内网托管平台约定），共享密钥放 `config.local.ini`（不入仓，C-1）。
- 改：校验通过后，从 payload 解析 `repo` 与 `ref` → `db.enqueue()` → 返回 202。
- 删：原「转发 GitLab trigger token」逻辑。
- payload 解析按托管平台格式（Bitbucket/SVN/自研）适配；字段映射经 config 配置键名，避免硬编码。

### 4.4 checkout `server/scheduler/checkout.py`（新增）

- **仅 git**（无 svn）：拉 `repo@ref` 到 `workspace_dir`，`git clone --depth 1` + `git checkout <ref>`（或按 ref fetch）。
- 认证两种，`[scheduler] git_auth = ssh|http`：
  - `ssh`：`config.local.ini` 的 `ssh_key` 路径，经 `GIT_SSH_COMMAND="ssh -i <key> -o StrictHostKeyChecking=accept-new"`（不入仓，C-1）。
  - `http`：`config.local.ini` 的 `http_token`，经 git credential helper / env 注入，**不落命令行回显**（C-1，避免 `ps` 泄露）。
- 工作区每任务隔离子目录，跑完保留日志、可选清理。

### 4.5 评测执行（复用 `server/harness/` + `server/metrics/report.py`）

worker 在 workspace 内顺序调用现有脚本（**零改动**）：
`check.py run` → `check.py sim` → `check.py compare` → `check.py quality` → `report.py`（聚合 + 门禁）。`limited_run.py` 仍负责运行型验证的超时+资源限制。

### 4.6 MCP server `local/mcp/ci_control_server.py`（改造）

- 保留：标准 MCP stdio 握手（initialize/tools/list/tools/call）。
- 改：数据源从 GitLab API → 本地 sqlite（`db.py` 只读查询）。
- 工具改名：`get_task_status(id)` / `list_tasks(limit)` / `get_task_log(id)`（替代 pipeline/job 三件套）。
- 凭证：不再需要 GITLAB_TOKEN；只需 db_path（env 或默认）。

### 4.7 部署 `server/deploy/deploy.py`（改造）

不再装 GitLab/Runner。新流程：
- `check`：环境自检（python3、git/svn、root/sudo——沿用现有权限校验）
- `init`：初始化 sqlite + 建 workspace/log 目录
- `service`：安装并启用两个 systemd 服务——`ci-webhook`（receiver）、`ci-worker`（worker）
- `all` = check → init → service

复用 `local/admin/deploy_remote.py`（SSH/SCP bootstrap）与 `connectivity.py`（SSH/权限校验）。部署不再需要 omnibus/JVM/端口探测。

## 5. 串行控制（FR-3）

`[scheduler] concurrency=1` → 单 worker 顺序处理队列 = 天然串行 = License 数。比 GitLab `resource_group` / Jenkins `Lockable Resources` 更直接。多 License：起 N 个 worker，`claim()` 原子取任务防重复。

## 6. 配置

`config.ini` 新增 `[scheduler]`：
```ini
[scheduler]
db_path = var/ci.db          ; 留空=部署目录/var/ci.db
workspace_dir = var/ws
log_dir = var/log
concurrency = 1              ; 仿真串行=License 数
git_auth = ssh              ; ssh|http（git checkout 认证方式）
poll_interval = 2           ; worker 轮询秒
```
敏感项 `config.local.ini` `[scheduler]`：`ssh_key`（git_auth=ssh 时）/ `http_token`（git_auth=http 时）（不入仓，C-1）。

**目标环境**：Ubuntu + python3.8（标准库）+ systemd；仓库协议 git（ssh 或 http）。
`[webhook]` 复用（listen/auth_header）；删除 GitLab 相关项（trigger token / project_id）。

**⚠️ webhook 对外端口硬约束**：受内网防火墙限制，对外监听端口**仅允许 `80-90`、`443`、`8080-8090`**。
原默认 `9100` 超范围，必须改为 `listen = 0.0.0.0:8080`（默认）。`deploy.py check` 须校验 `[webhook] listen`
的端口落在允许集合内，否则报错停止（C-10），避免部署后外部触发不通。

## 7. 错误处理与幂等

- checkout/harness 异常 → 任务 `error`，日志留存，worker 继续下一个（不崩溃）。
- worker 崩溃 → systemd 重启；`reset_stale()` 把残留 `running` 标 `error`。
- webhook 重复触发 → 默认各自入队（评测幂等由 harness 缓存负责，本期不去重；如需去重可加 `(repo,ref)` 唯一约束，列为后续）。
- 门禁不过 → `failed`（正常结果，非错误）。

## 8. 删除 / 保留 / 新增清单

**🗑️ 删除（GitLab 专属）**
`server/deploy/install_gitlab.py`、`server/deploy/probe_port.py`、`server/deploy/features.md`、`server/deploy/gitlab.rb.example`、`server/runner/setup_runner.py`、`server/pipeline/.gitlab-ci.yml`（及空目录 `server/runner/`、`server/pipeline/`）

**🔧 改造**
`server/webhook/receiver.py`、`local/mcp/ci_control_server.py`、`server/deploy/deploy.py`、`local/admin/deploy_remote.py`、`config.ini`、`local/mcp/opencode.json.example`

**♻️ 复用（不改）**
`server/harness/check.py`、`server/harness/limited_run.py`、`server/metrics/report.py`、`server/demo/qsort/`、`ci_config.py`、`checks/consistency.py`、`local/admin/connectivity.py`

**🆕 新增**
`server/scheduler/db.py`、`server/scheduler/worker.py`、`server/scheduler/checkout.py`、两个 systemd unit（`ci-webhook.service`、`ci-worker.service`，由 deploy 生成）

## 9. FR / NFR 映射（一致性闸门）

| 需求 | 实现位置 |
|------|---------|
| FR-1 触发机制 | `webhook/receiver.py`（入队） |
| FR-2 评测执行编排 | `scheduler/worker.py` |
| FR-3 仿真串行调度 | `scheduler/worker.py`（concurrency=1） |
| FR-6 指标统计与报告 | `metrics/report.py`（复用） |
| FR-7 质量门禁 | `metrics/report.py`（复用） |
| FR-13 验证预生成代码 | `harness/check.py`（复用） |
| FR-14 webhook 触发构建 | `webhook/receiver.py` |
| FR-12 / FR-20 开发端 MCP | `local/mcp/ci_control_server.py`（查 sqlite） |
| NFR-2 串行/资源约束 | worker + `limited_run.py` |
| **FR-21（新）任务队列与持久化** | `scheduler/db.py`（sqlite） |

`01_spec.md` 同步：废弃 FR-9/FR-10/FR-11/FR-15/FR-16 中 GitLab 专属内容；FR-19 的「转发 GitLab trigger」改为「入队」；新增 FR-21、D-013。`consistency.py` 扫描目录加 `server/scheduler/`。

## 10. 实现阶段

1. `scheduler/db.py` + schema + 队列操作（可独立单测）
2. `scheduler/checkout.py`（git/svn 拉取）
3. `scheduler/worker.py`（串起 claim→checkout→harness→report→finish）
4. 改造 `receiver.py`（入队）
5. 改造 `ci_control_server.py`（查 sqlite）
6. 改造 `deploy.py` + systemd unit；删 GitLab 文件
7. 同步 `01_spec.md`（FR-21/D-013，删 GitLab FR 内容）+ `config.ini` + 重生成 `quick_deploy`
8. 一致性闸门通过 + qsort 冒烟经调度器跑通

## 11. 决策记录

- **D-013 弃 GitLab，自研极简调度器**：内网已有代码托管且不可新建仓库 → 不需要托管能力；窄场景（串行评测）下 GitLab/Jenkins 过重；自研纯 python 标准库调度器最契合 D-004（零依赖）、C-1（自托管不外泄）。完全推倒 GitLab 路线，不做前向兼容。
- **D-014 sqlite 作状态存储**：标准库自带、单文件、支持历史查询与 MCP 检索，零依赖。
- **D-015 串行=单 worker**：以进程数表达 License 数，比平台级 resource lock 更直接、可审计。
