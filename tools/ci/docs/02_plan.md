# 02 — CI 系统实施计划（Plan）

> 受 `00_constitution.md` 约束，落地 `01_spec.md`。读者：人 / 强 AI。讲方案与阶段，不含逐条命令。

## 目标

搭建可运行的最小 CI：执行机首次远端 bootstrap（SSH/SCP）→ 服务器本地部署 GitLab CE → 注册串行
Runner → 流水线对预生成代码做多种验证（含 qsort 冒烟）；内源 webhook 接入、开发端 MCP（opencode）
查询。真实评测逻辑以占位脚本预留。

## 角色结构（执行边界）

| 角色 | 目录 | 职责 |
|------|------|------|
| 共享 | `ci_config.py` `config.ini` `config.local.ini`(不入仓) `checks/` `docs/` | 配置/公共库/闸门/文档 |
| server·部署 | `server/deploy/` `server/runner/` | 服务器本地装 GitLab/Runner、探测锁端口 |
| server·运行时 | `server/{pipeline,harness,metrics,webhook,demo}/` | 流水线验证、聚合门禁、webhook 接收 |
| local·首次 | `local/admin/` | 执行机连通性自检 + SSH/SCP bootstrap + 依赖经代理获取 |
| local·查询 | `local/mcp/` | 开发端查状态/拉日志，接 opencode |

## 固定技术决策（来自 spec 决策记录）

| 决策 | 取值 | 依据 |
|------|------|------|
| CI 平台 | 自托管 GitLab CE | D-002 |
| 部署 | 首次执行机 SSH/SCP bootstrap → 服务器本地直跑 deploy.py，HTTP 直连，端口探测锁定 | D-008, D-010 |
| 脚本 | python3 3.8 标准库，离线依赖（手动或经代理自动获取） | D-004, D-010 |
| 串行 | resource_group + concurrent=1 | D-003 |
| 验证 | 预生成代码，多种验证（check.py 合一）；运行型仅超时+资源限制 | D-005 |
| 触发 | git push / webhook / token（HTTP）；内源站经 X-Auth 接收器 | D-007, D-011 |
| 查询 | MCP 标准 stdio，接 opencode | D-006, D-012 |
| 凭证 | 私钥/密钥/代理密码不入仓（env / config.local.ini） | D-009 |

## 阶段划分

```
P0 远端 bootstrap   P1 平台搭建      P2 验证能力      P3 Runner       P4 流水线        P5 接入
（admin 连通性→      （探测端口→       （limited_run    （注册串行       （.gitlab-ci     （webhook X-Auth
 fetch→SSH/SCP）     装 GitLab）       超时+资源）      Runner）         多种验证）       + MCP/opencode）
```

**P0 远端 bootstrap（local/admin）**：填 `config.ini [remote]` 与 `config.local.ini`（代理）→
`deploy_remote.py check`（连通性自检）→ `fetch`（manual 放好 / auto 经代理下载）→ `push`（SSH/SCP
推码+依赖）→ 远程触发 `deploy.py`。完成判据：远端代码与依赖就位。新机首搭用；已在服务器可跳过。

**P1 平台搭建（server/deploy）**：填 config（host/deps_dir）→ 自检 → `probe_port` 锁端口 →
离线装 GitLab（external_url=host+端口）→ 开特性禁遥测。完成判据：GitLab 可访问、建私有项目、拿 Token。

**P2 验证能力（server/harness）**：`limited_run.py` 加超时+资源限制运行预生成代码。完成判据：限制运行可用、超时生效。

**P3 Runner（server/runner）**：离线装 gitlab-runner，shell executor 注册，tag=sim-license，
concurrent=1（注册 token 脱敏不落日志）。完成判据：Runner 注册、串行锁定。

**P4 流水线（server/pipeline+harness+metrics）**：`.gitlab-ci.yml` 多阶段
（smoke→run→sim→compare→quality→report），四类验证合一为 `check.py <kind>`，sim 阶段加
resource_group 串行，report 聚合+门禁（0 产物 fail-closed）。含 qsort demo 端到端 5/5。

**P5 接入（server/webhook + local/mcp）**：内源站经 `receiver.py`（X-Auth 共享密钥）触发流水线；
开发端 `ci_control_server.py` 标准 MCP stdio 接 opencode 查状态/拉日志。

## 需求追溯

| 阶段 | 落地需求 |
|------|---------|
| P0 | FR-16/17/18, D-009/010, NFR-1 |
| P1 | FR-9/10/15, NFR-1 |
| P2 | NFR-3 |
| P3 | NFR-2, FR-3 |
| P4 | FR-1/2/3/6/7/13, NFR-2 验证 |
| P5 | FR-14/19/12/20 |

## 本期范围边界

- 不实现真实评测逻辑（`check.py` 占位脚本预留，按 kind 后续填充）。
- 触发：git push / webhook / token / 内源 X-Auth；查询：MCP（opencode）。
- 后续迭代：缓存、结果持久化、任务自动发现、审计（见 spec 后续步骤）。
