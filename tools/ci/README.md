# tools/ci — CI 系统（Spec-Driven，精简版）

AI 代码生成 Benchmark 评测仓库的 CI 系统。**CI 验证预生成的成品代码**（不在内部生成代码），
做多种验证（运行/仿真/比对/质量检查）并收集 output 与状态。纯 python3（3.8 标准库、零依赖）、
依赖离线传入。

## 执行角色（目录即角色）

代码按**谁、在哪台机、何时执行**组织成两个顶层角色 + 共享层：

```
tools/ci/
├── ci_config.py  config.ini  config.local.ini.example   ← 共享层（角色中立）
├── checks/consistency.py  gen_quick_deploy.py  docs/  README.md
├── server/                 ← 在 CI 服务器上执行
│   ├── deploy/   deploy.py / probe_port.py / install_gitlab.py / features.md / gitlab.rb.example
│   ├── runner/   setup_runner.py
│   ├── harness/  limited_run.py / check.py
│   ├── metrics/  report.py
│   ├── webhook/  receiver.py / README.md
│   ├── pipeline/ .gitlab-ci.yml
│   └── demo/qsort/
└── local/                  ← 在客户端 / 执行机上执行
    ├── admin/    deploy_remote.py / connectivity.py   （首次 SSH/SCP bootstrap）
    └── mcp/      ci_control_server.py / opencode.json.example   （开发端查询，接 opencode）
```

| 角色 | 谁/何时 | 入口 |
|------|---------|------|
| **local/admin** | 客户端·首次，从执行机远端 bootstrap | `python3 local/admin/deploy_remote.py all` |
| **server/deploy·runner** | 服务器·部署时手动安装 | `python3 server/deploy/deploy.py all` → `... runner` |
| **server**·运行时 | GitLab/Runner 自动执行 | `.gitlab-ci.yml`（smoke→run→sim→compare→quality→report） |
| **local/mcp** | 开发端·后续查询 | opencode 接入 `local/mcp/ci_control_server.py` |

## 部署两段式

详见 `docs/quick_deploy.md`（由 config.ini 自动生成，命令以它为准）。

**A. 首次远端 bootstrap（在执行机上，新机首搭用）**
```bash
# 填 config.ini [remote]（目标机 host/user/dest）与 config.local.ini [proxy]（如需代理下载）
python3 local/admin/deploy_remote.py all   # 连通性自检 → 取依赖 → SSH/SCP 推送 → 远程跑 deploy.py
```

**B. 服务器本地部署（代码到位后在服务器上）**
```bash
cd /opt/ci
# deploy.py 需 root：非 root 用户命令前加 sudo（脚本会自检拦截）；root 用户直接运行。
sudo python3 server/deploy/deploy.py all   # 自检 → 锁 host/端口 → 装 GitLab(手输root密码) → 全自动注册 Runner
# all 已含 Runner 全自动注册（gitlab-rails 建项目+签 token，GitLab 16+ 新流程）；
# 单独重注册：sudo python3 server/deploy/deploy.py runner（可加 --token glrt- 手动 fallback）
```

## 离线依赖（手动 / 自动）

- **manual**：按 `docs/OFFLINE_DEPENDENCIES.md` 手动下载 .deb 放入 `deps_dir`。
- **auto**：`config.ini [fetch] mode=auto` + 各包 URL，执行机经 `config.local.ini [proxy]` 代理
  下载后随 bootstrap 推送到远端。**代理含明文密码，仅在 config.local.ini，不入仓**。

## 触发构建

- `git push` 自动触发；或 webhook / trigger token（HTTP 直连）→ 见 `server/webhook/README.md`。
- **内源代码托管站**：经 `server/webhook/receiver.py`（校验 `X-Auth-Token` 共享密钥）→ 触发流水线。
  密钥与 trigger token 经环境变量 / `config.local.ini [secrets]`，不入仓。

## 查状态 / 拉日志（MCP，接 opencode）

开发端用标准 MCP（stdio）`local/mcp/ci_control_server.py` 直连 GitLab API：
`get_pipeline_status` / `list_pipelines` / `get_job_log`。opencode 接入见
`local/mcp/opencode.json.example`；凭证用环境变量（`GITLAB_API/TOKEN/PROJECT`），不入仓。

## qsort 冒烟 demo（端到端验证 CI 可用）
```bash
python3 server/demo/qsort/smoke_qsort.py   # 编译 → 限制运行 → 比对，期望 5/5 通过
```
CI 流水线的 `smoke` 阶段会自动跑它。

## SDD 文档层级

| 层 | 文件 | 回答 |
|----|------|------|
| 宪法 | `docs/00_constitution.md` | 不可违反的原则（C-1~C-10） |
| 规格 | `docs/01_spec.md` | 是什么/为什么 + 需求(FR/NFR) + 决策记录(D-001~D-012) |
| 计划 | `docs/02_plan.md` | 用什么方案/分阶段（P0~P5） |
| 任务 | `docs/tasks/*.md` | 第几步敲什么 |

一致性由 `checks/consistency.py` 校验（spec 需求编号 ↔ 代码 `implements:` 双向对齐），接入 CI 闸门。

## 关键设计

- **部署两段式**（D-008/D-010）：首次执行机 SSH/SCP bootstrap，之后服务器本地直跑；日常 HTTP 触发。
- **CI 验证预生成代码**（D-005）：多种验证（合一为 `check.py <kind>`）；运行型仅超时+资源限制。
- **仿真严格串行**（D-003）：resource_group + concurrent=1。
- **凭证不入仓**（C-1/D-009）：私钥留 ~/.ssh；密钥/token/代理密码经 env 或 `config.local.ini`。
- **纯 python3 标准库**：无第三方依赖；依赖离线传入（手动或经代理自动获取）。
