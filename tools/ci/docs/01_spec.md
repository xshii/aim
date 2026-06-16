# AI 验证代码仓库 — CI 系统需求说明与技术选型

> 文档目的：为 AI 代码生成 Benchmark 评测仓库的持续集成（CI）系统提供需求规格与技术选型依据，作为后续设计与实施的基线。
> 文档层级：**Spec（规格）** — 受 `00_constitution.md` 约束。是需求的累积式事实源（source of truth）。
> 上游：`00_constitution.md`（不可协商原则）。下游：`02_plan.md`、`tasks/`。
> 状态：v1.1。需求采用累积编号 + 状态（Draft/Accepted/Implemented/Deprecated）。
> 决策记录见第 8 节。

---

## 1. 背景与目标

本仓库用于维护 AI 代码生成的 Benchmark，并对接 AI Harness 评测框架，自动化地运行评测、统计代码生成率等指标。CI 系统是支撑这一流程的自动化中枢，负责触发评测、调度执行、收集结果、产出报告并设置质量门禁。

本系统与普通软件 CI 的关键差异在于三点，这三点贯穿全部需求与选型：

1. **执行 AI 生成的不可信代码**——必须按恶意代码进行隔离防护。
2. **依赖受限的商业仿真软件**——License 单实例、不支持并行使用，构成串行瓶颈。
3. **强信息安全要求**——代码与数据不得外泄至第三方 SaaS，须完全自托管。

### 1.1 设计目标

- 自动化触发与执行 Benchmark 评测，覆盖代码生成、编译/解析、测试、仿真、打分全链路。
- 在仿真软件不支持并行的约束下，最大化整体吞吐。
- 严格隔离不可信代码，保护参考答案、凭证、License 与内网资源。
- 全程自托管，数据不出内网。
- 产出可复现、可审计、可追溯趋势的评测结果与报告。
- 以核心指标（代码生成率、通过率）作为质量门禁。

---

## 2. 关键决策（已确认 / 待确认）

以下为影响设计的关键决策项。标记「已确认」的为本期实施的固定前提；「待确认」的暂不阻塞本期，按默认值推进，后续可细化。

| 编号 | 决策项 | 状态 | 取值 / 影响 |
|------|-------|------|-----------|
| O-1 | 执行机操作系统 | ✅ 已确认 | Linux |
| O-2 | Benchmark 题量级与模型数 | ⏳ 待确认 | 暂按中小规模、单模型推进；规模上升再评估编排 |
| O-3 | 仿真并发限制 | ✅ 已确认 | **严格串行，License = 1**（resource_group + concurrent=1） |
| O-4 | 仓库是否接受外部贡献 | ✅ 已确认 | **仅内部私有**（runner 安全策略可适度简化） |
| O-5 | 评测任务形态 | ✅ 已确认 | 验证预生成代码，多种验证（D-005） |
| O-6 | 合规细则（外发限制、审计留存） | ⏳ 待确认 | 默认全程内网不外泄；具体留存策略后续细化 |

---

## 3. 需求说明

### 3.1 功能性需求

**FR-1 触发机制（分层）**

CI 需支持多种触发方式，按反馈速度与成本分层：

- Pull Request / Merge Request 触发：运行小样本 smoke 评测，秒级反馈，验证框架完整性。
- 合并至主干触发：运行受影响的 Benchmark 子集。
- 定时触发（nightly）：运行全量 Benchmark 回归。
- 手动 / 发布触发：全量评测，含多模型对比，产出发布报告。

**FR-2 评测执行编排**

CI 负责编排完整评测链路，但执行下沉到独立执行层：调用模型生成代码 → 静态检查/编译 → 测试 → 仿真 → 打分 → 统计。其中前序步骤可并行，仿真步骤受串行约束（见 NFR-2）。

**FR-3 仿真任务串行调度**

针对仿真软件不支持并行的约束，CI 须保证仿真步骤独占执行：同一时刻仅一个仿真任务运行（或不超过 License 实例数），其余任务排队等待，不得因抢占导致 License 冲突或工具状态污染。**Runner 注册采用 GitLab 16+ 新流程（authentication token）：服务器本地以 gitlab-rails 创建 / 复用项目并签发项目级 token 完成全自动注册（无需网页 / PAT），runner 端 `concurrent=1` 保证上述串行。** 见 `server/runner/setup_runner.py`。

**FR-4 模型响应缓存**

对 `(prompt 哈希, 模型, 参数)` 组合的模型响应进行缓存；对 `(代码哈希, 仿真配置)` 的仿真结果进行缓存。框架改动但输入未变时复用缓存，避免重复的 API 计费与重复占用稀缺的串行仿真时间。须支持强制重跑开关。

**FR-5 结果产出与持久化**

每次运行产出结构化结果（JSON）与全链路 trace（含每步 prompt、响应、工具调用），持久化至对象存储与数据库，可追溯、可回放、可审计。

**FR-6 指标统计与报告**

自动计算并聚合代码生成率相关指标，按模型、语言、难度、Benchmark 维度切片，产出报告（JSON + 可视化看板），并推送趋势对比。

代码生成率指标分层定义：

| 指标 | 含义 |
|------|------|
| Generation Rate | 模型产出有效代码块的比例（非空 / 可解析） |
| Compile/Parse Rate | 生成代码编译 / 解析通过的比例 |
| Pass@k | k 次采样中至少一次通过测试的比例 |
| Functional Correctness | 通过全部测试用例的比例 |

**FR-7 质量门禁**

将核心指标（生成率、通过率）设为合并/发布卡点；相较基线下降超过阈值则阻断，防止框架退化。阈值可配置。

**FR-8 任务发现**

CI 须能自动发现 `code/` 目录下新增的 Benchmark 任务（通过任务元数据 `meta.yaml`），无需改动框架代码即可纳入评测。

**FR-9 CI 平台自托管搭建**

CI 平台须可在内网首次搭建：提供 GitLab CE 的安装、配置、特性开启的可复现方法（脚本 + 文档），作为整个 CI 系统的前置基础设施（P0 阶段）。决策依据见 D-002。**GitLab root 初始密码于部署时交互手输（getpass 不回显，回车用 config 可配默认值），经环境变量注入安装（首次 reconfigure 生效）、不入仓不落命令行（C-1）；远端 bootstrap 经 `ssh -tt` 把输入传至远端。**

**FR-10 GitLab CE 特性开启清单**

须明确并固化 GitLab CE 为支撑本系统所需开启 / 关闭的特性（见 `server/deploy/features.md`），每项特性须有启用理由，且不得违反宪法 C-1（不外泄）。所需特性至少包括：私有项目、Runner 注册、流水线（CI/CD）、Webhook（触发）、备份。须明确**禁用**任何对外联网上报 / 遥测类特性。

**FR-11 离线 / 单端口 / 一键部署**

CI 系统须适配受限内网：(a) 全部脚本为 python3 3.8 标准库实现，零第三方依赖；(b) 依赖离线传入（不 git clone），见 `OFFLINE_DEPENDENCIES.md`；(c) 部署两段式——首次经执行机 SSH/SCP 远端 bootstrap（FR-16），代码到位后在服务器上一键跑 `server/deploy/deploy.py`；日常触发走 HTTP，不依赖常驻隧道；(d) 所有可变参数归一到 `config.ini`，敏感项归一到 `config.local.ini`（不入仓）。决策依据见 D-004、D-008、D-009、D-010。

**FR-12 开发端 CI 操作 MCP**

须提供 MCP（stdio 模式，python3 标准库）作为开发端查询 CI 的接口：查流水线状态、拉错误日志。经 GitLab API（HTTP 直连）访问，凭证用环境变量传入（不写入仓库，C-1）。触发构建用 webhook，不在此。MCP 与被测代码无关。决策依据见 D-006。

**FR-13 验证预生成代码（多种验证）**

CI 不在内部生成代码；输入为预生成的成品代码。CI 须支持多种验证并收集其 output 与状态：运行型（经超时+资源限制执行）、仿真型（喂仿真软件，严格串行）、比对型（与答案比对）、质量检查型（静态）。结果聚合后用于指标与质量门禁。决策依据见 D-008。

**FR-14 webhook / token 触发构建**

须支持网页/外部经 webhook 或 GitLab trigger token（HTTP）触发流水线。GitLab HTTP 直接可达，无需 ssh/隧道。内源代码托管站的入站 webhook 经 `server/webhook/receiver.py` 接入（X-Auth 校验，FR-19）。说明见 `server/webhook/`。

**FR-15 端口探测与锁定**

服务器部分端口被其他 CI 服务占用。须自动从候选端口探测一个空闲端口、锁定到配置，供 GitLab 监听与访问统一使用（`server/deploy/probe_port.py`）。决策见 D-008。

**FR-16 远端首次部署（SSH/SCP bootstrap）**

首次在内网新机搭建时，允许从一台「代码执行机」经 SSH/SCP 把全量代码与离线依赖推送到目标
服务器的部署目录，再经 SSH 远程执行 `deploy.py`。此为 D-008「服务器本地部署」的**首次
bootstrap 补充**，非取代：日常触发仍用 HTTP（FR-14），不依赖常驻 ssh 隧道。连接参数来自
`config.ini [remote]`；ssh 私钥留本地 `~/.ssh`，严禁入仓（C-1, D-009）。决策见 D-010。

**FR-17 离线依赖获取（手动 / 自动）**

离线依赖支持两种获取：(a) manual——手动下载放入 deps_dir（FR-9 现状）；(b) auto——在**有网
的执行机**经 HTTP(S) 代理下载到本地，再随 FR-16 推送到远端 deps_dir。下载清单（URL/文件名）见
`config.ini [fetch]` 与 `OFFLINE_DEPENDENCIES.md`。**代理地址含明文密码，严禁入仓**，仅置于
`config.local.ini`（gitignore）或环境变量 `HTTP(S)_PROXY`。决策见 D-010。

**FR-18 部署前连通性测试**

提供轻量连通性自测（python3 标准库）：目标服务器 SSH 可达且远端有 python3、GitLab HTTP/API
可达且 Token 有效、（可选）webhook 目标可达。失败即明确报告缺失项并停止（C-10），不在缺信息时
继续。**当 SSH 端口可达但密钥认证失败，且运行在交互式终端（TTY）下，经用户确认后运行
`ssh-copy-id` 安装本地公钥（交互输入一次密码），装毕重测；非 TTY 或本地无公钥则按原逻辑报告
失败、不自动改远端状态（C-10）。** **SSH 鉴权通过后，校验远端登录用户具备管理员权限（root 或
免密 sudo）——一键部署需 dpkg/gitlab-ctl 等特权操作；权限不足即明确报告并停止（C-10），避免部署
中途因权限失败。** 见 `local/admin/connectivity.py`。

**FR-19 内源托管 webhook 接入（X-Auth）**

提供轻量 webhook 接收器（python3 标准库 `http.server`），接受内部代码托管站的入站 webhook：
以可配置请求头（默认 `X-Auth-Token`）做**共享密钥常量时间校验**，通过后经 GitLab trigger
token 触发对应流水线。共享密钥与 trigger token **不入仓**（环境变量 / `config.local.ini`，
C-1）。见 `server/webhook/receiver.py`。决策见 D-011。

**FR-20 MCP 标准化与 opencode 接入**

FR-12 的开发端 MCP 须遵循标准 MCP stdio 握手（`initialize` / `tools/list` / `tools/call`，
含 `protocolVersion`、`capabilities`、工具 `inputSchema`），可由 opencode CLI 等标准 MCP
客户端经 `opencode.json` 的 mcp(local/stdio) 直接接入。凭证仍用环境变量注入（C-1）。决策见 D-012。

### 3.1.1 功能性需求状态总表

| 编号 | 名称 | 状态 |
|------|------|------|
| FR-1 | 触发机制（分层） | Accepted |
| FR-2 | 评测执行编排 | Accepted |
| FR-3 | 仿真任务串行调度 | Accepted（本期实现） |
| FR-4 | 模型响应缓存 | Accepted（后续迭代） |
| FR-5 | 结果产出与持久化 | Accepted（后续迭代） |
| FR-6 | 指标统计与报告 | Accepted（本期占位） |
| FR-7 | 质量门禁 | Accepted（本期占位） |
| FR-8 | 任务发现 | Accepted（后续迭代） |
| FR-9 | CI 平台自托管搭建 | Accepted（本期实现，P0） |
| FR-10 | GitLab CE 特性开启清单 | Accepted（本期实现，P0） |
| FR-11 | 离线/服务器本地一键部署 | Accepted（本期实现） |
| FR-12 | 开发端 MCP 查询 | Accepted（本期实现） |
| FR-13 | 验证预生成代码（多种验证） | Accepted（本期实现） |
| FR-14 | webhook 触发构建 | Accepted（本期实现） |
| FR-15 | 端口探测与锁定 | Accepted（本期实现） |
| FR-16 | 远端首次部署（SSH/SCP bootstrap） | Accepted（本期实现） |
| FR-17 | 离线依赖获取（手动/自动经代理） | Accepted（本期实现） |
| FR-18 | 部署前连通性测试 | Accepted（本期实现） |
| FR-19 | 内源托管 webhook 接入（X-Auth） | Accepted（本期实现） |
| FR-20 | MCP 标准化与 opencode 接入 | Accepted（本期实现） |

### 3.2 非功能性需求

**NFR-1 信息安全 — 不外泄**

代码托管、CI 调度、任务执行、结果存储全部在内网完成，不依赖任何第三方 SaaS。禁用将代码或数据外传的服务。

**NFR-2 仿真资源约束**

仿真软件不支持并行使用（License 单实例 / 工具单例 / 整机独占，具体见 O-3）。系统须以并发度 = License 实例数（默认为 1）的方式调度仿真，且该并发度须为可配置项，便于未来扩容时无需改动架构。

**NFR-3 运行型验证的资源约束**

CI 运行预生成代码做验证时，须加超时与资源限制（内存/CPU/文件数/墙钟），防止资源耗尽或卡死。鉴于代码为预生成成品、环境为封闭内网与内部私有（O-4），不要求 namespace 级强隔离（D-005）。

**NFR-4 无容器依赖**

执行环境不依赖 Docker / 容器镜像构建（见技术选型）。隔离与执行须基于无需容器 daemon 的方案实现。

**NFR-5 可复现性**

固定随机种子、记录模型版本与参数、记录 prompt 哈希与工具版本，确保评测结果可复现。

**NFR-6 商业友好许可**

所有 CI 相关核心组件须采用 OSI 认证的宽松许可（MIT / Apache 2.0 / GPL 等），允许商业使用与自托管，无 BSL/SSPL 等 source-available 许可带来的商用限制。

**NFR-7 可观测性与审计**

任务排队、执行、失败、重试全程可观测；所有工具调用与执行记入 trace，满足审计需求（具体留存策略见 O-6）。

**NFR-8 长任务容忍**

仿真与多步 Agent 任务可能耗时较长，CI 编排层须采用异步模式，不因默认超时误杀任务，超时与资源上限可配。

---

## 4. 系统架构

### 4.1 分层架构

CI 系统遵循「编排层轻、执行层重」原则，将受限的仿真执行与可并行的前序步骤解耦。

```
┌─────────────┐   触发（PR / 定时 / 手动）   ┌──────────────────┐
│  代码仓库     │ ──────────────────────────> │  CI 编排层         │
│             │                              │ （触发/编排/收集）  │
└─────────────┘                              └────────┬─────────┘
                                                      │ 入队
                                             ┌────────▼─────────┐
                                             │  任务队列          │
                                             └────────┬─────────┘
                  ┌───────────────────────────────────┼───────────────────────────┐
                  │ 阶段一：可并行（不受仿真约束）         │ 阶段二：串行独占             │
         ┌────────▼─────────┐                ┌─────────▼──────────┐    ┌──────────▼──────────┐
         │ 调模型 → 生成代码   │   ...多并行     │ 静态检查 / 编译 / 测试 │    │ 仿真执行（并发=License）│
         │ （隔离沙箱执行）     │                │ （隔离沙箱执行）       │    │ 绑定仿真机，串行消费     │
         └──────────────────┘                └────────────────────┘    └──────────┬──────────┘
                                                                                   │
                                                                        ┌──────────▼──────────┐
                                                                        │ 结果存储 + 指标统计    │
                                                                        │ + 报告 + 质量门禁      │
                                                                        └─────────────────────┘
```

### 4.2 资产分层（与仓库结构对应）

`tools/ci/` 按**执行角色**组织：`server/`（在 CI 服务器上执行）、`local/`（在客户端/执行机上
执行）、以及角色中立的共享层。同一份代码经 admin push 后在服务器运行（C-7）。

| 角色 | 何时 / 何地执行 | 仓库位置 |
|------|----------------|---------|
| 共享层 | 配置 / 公共库 / 文档 / 闸门（两边都读） | `ci_config.py`、`config.ini`、`config.local.ini`(不入仓)、`checks/`、`docs/`、`gen_quick_deploy.py` |
| server·部署 | 服务器本地安装 GitLab/Runner（手动跑） | `server/deploy/`（deploy.py / probe_port / install_gitlab / features.md）、`server/runner/` |
| server·运行时 | GitLab/Runner 自动执行的验证链路 | `server/pipeline/.gitlab-ci.yml`、`server/harness/`、`server/metrics/`、`server/webhook/`、`server/demo/` |
| local·首次 | 客户端首次远端 bootstrap（SSH/SCP） | `local/admin/`（deploy_remote.py / connectivity.py） |
| local·查询 | 开发端日常查 CI（HTTP 直连，接 opencode） | `local/mcp/`（ci_control_server.py / opencode.json.example） |

### 4.3 MCP 定位说明

MCP 是给**开发端**（人 / AI 助手）操作 CI 的接口：触发构建、查流水线状态、拉错误日志。
stdio 模式，经 HTTP 直连 GitLab API。触发构建用 webhook。与被测代码无关。见第 8 节 D-006。

## 5. 技术选型

### 5.1 选型原则

1. 满足 NFR-1（不外泄）：必须可完全自托管。
2. 满足 NFR-6（商业友好）：OSI 宽松许可，排除 SaaS-first 方案与 BSL/SSPL 许可工具。
3. 满足 NFR-4（无容器）：执行不依赖 Docker。
4. 满足 NFR-2（仿真串行）：具备资源独占/串行调度能力。

> 注：CI 工具的许可证与定价条款可能随时间变动，正式采用前须以各项目官网当前条款为准。

### 5.2 CI 框架：GitLab CE（推荐）

**结论：在无历史包袱的前提下，推荐 GitLab CE；若已有 Jenkins 体系或独立 Git 托管，Jenkins 亦可。**

| 维度 | GitLab CE | Jenkins |
|------|-----------|---------|
| 许可证 | MIT（CE，免费商用） | MIT（免费） |
| 自托管不外泄 | 支持，内网部署成熟 | 支持，自托管标准 |
| 仓库 + CI 一体 | 是 | 否（仓库需另配） |
| 仿真串行控制 | `resource_group`（原生、简洁） | lockable-resources / throttle 插件 |
| 无 Docker 执行 | Shell executor | agent 直接执行 shell |
| 配置方式 | YAML（声明式，随仓库版本化） | Groovy Pipeline / 插件 |
| 维护与安全负担 | 较低，开箱即用 | 较高，插件多、CVE 历史需关注 |

**推荐 GitLab CE 的理由：**

- 代码托管与 CI 一体，无需额外维护独立 Git 服务。
- `resource_group` 原生支持仿真串行独占，契合核心约束（NFR-2）。
- `.gitlab-ci.yml` 声明式配置随代码版本化，符合可复现与可审计要求（NFR-5、NFR-7）。
- 开箱即用，维护与安全负担更低。

**选择 Jenkins 的情形：** 已在使用 Jenkins、已有独立 Git 托管、需要 GitLab CI 难以表达的极端定制、或依赖仅 Jenkins 生态存在的特定插件。

> GitLab CE 须使用社区版（CE，MIT）；企业版（EE）为商业许可，部分高级功能仅 EE 提供，须确认所需功能均在 CE 范围内。

### 5.3 运行型验证的限制（超时 + 资源）

CI 验证的是预生成成品代码，环境为封闭内网 + 内部私有，故不做 namespace 级强隔离。
运行型验证经 `limited_run.py` 加超时与资源限制（RLIMIT_AS/CPU/NOFILE + 墙钟），
仅防资源耗尽与卡死。决策见第 8 节 D-005。

### 5.4 CI Executor 与串行控制

- **Executor**：GitLab Shell executor（不依赖 Docker），运行型验证经 limited_run 加超时+资源限制。
- **串行控制**：通过 runner tag 将仿真任务绑定到仿真机；通过 `resource_group` 保证仿真步骤独占串行执行（并发度对应 License 实例数，可配）。

### 5.5 配套组件

| 用途 | 选型方向 | 许可考量 |
|------|---------|---------|
| 任务队列（如需更强调度） | Redis / 轻量队列 | 开源宽松许可 |
| 结果存储 | 对象存储 + PostgreSQL | 开源宽松许可 |
| 凭证管理 | GitLab masked variables / Vault | 注意 Vault 许可变动，按当前条款评估 |
| MCP（开发端查询 CI） | stdio + 标准库 | 查状态/拉日志 |

---

## 6. 部署拓扑

```
执行机（admin，有外网/经代理）                  CI 服务器（内网，无外网）
├── local/admin/connectivity.py（连通性自检）    ┌──────────────────────────────────────┐
├── fetch=auto 经代理下载依赖                     │ GitLab CE（本机 HTTP 直连，端口探测锁定）│
└── deploy_remote.py ──SSH/SCP 推码+依赖──────────▶ │   └ benchmark 私有项目 + .gitlab-ci.yml │
                       └─SSH 远程触发 deploy.py──▶ │ GitLab Runner（shell, tag=sim-license,  │
                                                  │   concurrent=1 串行）                   │
内源代码托管站 ──webhook(X-Auth)──▶ server/webhook │ 验证：limited_run + 仿真(串行) + 比对 +  │
                                    /receiver.py ─▶│   质量检查 → 聚合 + 质量门禁             │
开发端 local/mcp（opencode）──HTTP 查状态/拉日志──▶ └──────────────────────────────────────┘
```

说明：首次经 SSH/SCP 远端 bootstrap（D-010），之后代码已在服务器、本地直跑 `deploy.py`（D-008）。
日常触发走 HTTP（git push / webhook / token），不依赖常驻隧道。GitLab 与 Runner 同机；
若仿真需独立机器，Runner 可单独部署并保持串行约束。

## 7. 安全要点小结

| 风险 | 控制措施 |
|------|---------|
| 验证代码资源耗尽/卡死 | limited_run 超时+资源限制（内存/CPU/文件数/墙钟） |
| 参考答案/凭证泄露 | 沙箱不挂载答案目录；凭证经 secret 管理注入，不落日志 |
| License/仿真工具被破坏或窃取 | 仿真机网络隔离，沙箱不可触及 License 服务器与工具二进制 |
| self-hosted runner 被外部 PR 利用 | fork PR 不自动跑 self-hosted runner，须人工批准；runner 用完即焚（取决于 O-4） |
| 插件供应链风险（Jenkins） | 若用 Jenkins，最小化插件、跟踪 CVE |

---

## 8. 决策记录

记录当前生效的关键决策（决定 + 理由）。新增决策追加 D-NNN；不保留已废弃方案的历史。

| 编号 | 决策 | 理由 |
|------|------|------|
| D-001 | 自托管、信息不外泄 | 内部 benchmark/答案/License 不得外泄第三方 SaaS |
| D-002 | CI 平台用 GitLab CE（社区版 MIT） | 可纯内网、许可友好、仓库+CI 一体、原生串行控制 |
| D-003 | 仿真严格串行（concurrent=1 + resource_group） | 仿真 License=1，不支持并行 |
| D-004 | 纯 python3 标准库 + 离线依赖 | 服务器仅 python3 3.8、不装库、内网无外网 |
| D-005 | CI 只验证预生成代码；运行型仅超时+资源限制 | 代码为成品、封闭内网、内部私有，无需强隔离 |
| D-006 | MCP 给开发端查状态/拉日志 | 开发端（人/AI 助手）经 HTTP 直连 GitLab API |
| D-007 | 触发用 webhook/token；ssh 私钥不入仓库 | 触发=HTTP，登录=ssh，二者分离 |
| D-008 | 部署 = 首次远端 bootstrap + 服务器本地一键部署；HTTP 直连 + 端口探测锁定 | 首次经 SSH/SCP 推码，之后服务器本地直跑；GitLab 直连；端口避占用、锁定复用 |
| D-009 | 凭证 / 私钥 / 代理明文密码不入仓 | ssh 私钥留 ~/.ssh；密钥/token/代理密码仅置环境变量或 config.local.ini（gitignore），严禁入仓与 git 历史 |
| D-010 | 首次远端 bootstrap（执行机 SSH/SCP）+ 依赖可经代理自动获取 | 新机首搭需从执行机推码+依赖；执行机有外网（经代理），目标机内网无外网，故下载在执行机、明文代理不入仓 |
| D-011 | 内源 webhook 用独立 stdlib 接收器 + X-Auth 共享密钥 | 自定义鉴权头不耦合进 GitLab；常量时间校验后用 trigger token 触发；密钥不入仓 |
| D-012 | MCP 走标准 stdio（opencode 兼容） | 标准 MCP 握手 + inputSchema，便于 opencode 等客户端接入；零依赖手写最小实现 |

### 关键决策详述

**D-003 仿真严格串行**：仿真软件 License 单实例、不支持并行。GitLab Runner 全局
`concurrent=1` + 流水线 `resource_group: sim-license-lock` 双重保证。并发数可配，受真实
License 数约束。**贯穿全程不可动摇的硬约束。**

**D-005 验证预生成代码**：CI 不在内部生成代码，输入是预生成成品；做多种验证（运行/仿真/
比对/质量检查）并收集 output 与状态。运行型验证经 `limited_run.py` 加超时+资源限制
（RLIMIT_AS/CPU/NOFILE + 墙钟），防资源耗尽与卡死，不做 namespace 强隔离。

**D-007 触发与登录权限分离**：日常构建由 git push 自动触发，或经 webhook / GitLab trigger
token（HTTP）触发，见 `server/webhook/`。触发是 HTTP 行为，不需 ssh；ssh 仅用于首次远端 bootstrap（D-010）。ssh 私钥仅管理员部署/维护用，
留本地 `~/.ssh/`，**严禁入仓库**（含 git 历史；C-1）。token 可吊销轮换、权限仅触发；私钥能登录
操作系统、后果严重，二者分离。

**D-008 部署两段式：首次远端 bootstrap + 服务器本地部署**：部署分两段，互补而非二选一。
(1) **首次 bootstrap（local/admin）**：新机首搭时，从执行机经 SSH/SCP 把全量 `tools/ci` 代码与
离线依赖推到目标机（`deploy_remote.py push`），再经 SSH 远程触发服务器本地部署；
(2) **服务器本地部署（server/deploy）**：代码到位后在服务器上直接跑 `deploy.py`，安装 GitLab/Runner。
日常构建触发走 HTTP（FR-14），不依赖常驻 ssh/隧道。GitLab 装在本机、HTTP 直接可达；因服务器部分端口
被其他 CI 服务占用，GitLab 端口由 `probe_port.py` 从候选探测一个空闲端口并锁定到 config，一经锁定即
复用避免漂移（`auto_lock=false` 手动指定，`--force` 强制重探）。`external_url` = host + 锁定端口。

**D-009 凭证 / 私钥 / 代理明文密码不入仓**：ssh 私钥仅留管理员本地 `~/.ssh`；webhook 共享密钥、
GitLab trigger token、HTTP(S) 代理的明文密码（`user:pass@proxy`）一律不写入仓库与 git 历史，只经
环境变量或 `config.local.ini` 注入（`.gitignore` 的 `*.local.ini` 已忽略）。`ci_config.load()`
自动叠加 `config.local.ini` 覆盖，`secret()`/`proxies()` 优先取环境变量。

**D-010 首次远端 bootstrap + 依赖自动获取**：内网新机无外网、不能 git clone；执行机（admin 侧）有
外网但需经企业代理。故依赖在执行机经代理下载（`fetch=auto`，URL 在 `config.ini [fetch]`、代理在
`config.local.ini [proxy]`），或手动放好（`fetch=manual`），再随代码 SCP 到远端 `deps_dir`。
传输用 OpenSSH `ssh`/`scp`。

**D-011 内源 webhook：独立接收器 + X-Auth 共享密钥**：内部代码托管站经入站 webhook 触发评测。用
独立 stdlib HTTP 接收器（`server/webhook/receiver.py`）校验可配置请求头（默认 `X-Auth-Token`）的
共享密钥（`hmac.compare_digest` 常量时间比较），通过后用 GitLab trigger token 触发流水线。把自定义
鉴权与 GitLab 解耦；共享密钥与 trigger token 经环境变量/`config.local.ini` 注入（C-1）。

**D-012 MCP 标准 stdio（opencode 兼容）**：开发端 MCP（`local/mcp/ci_control_server.py`）遵循标准
MCP 握手（`initialize` 返回 protocolVersion/capabilities/serverInfo，`tools/list` 含 inputSchema，
通知不回应），可由 opencode 等客户端经 `opencode.json` 的 mcp(local/stdio) 直接接入；仍零依赖手写。

### 变更规则（SDD）

文档分层：`00_constitution.md`（宪法）→ `01_spec.md`（需求+决策）→ `02_plan.md`（计划）→
`tasks/`（任务）→ 代码（`server/`、`local/`、共享层）。变更单向流动；重要取舍在本章追加 D-NNN。禁止只改代码不回改
spec；同一事实只在一处定义。一致性由 `checks/consistency.py` 校验，接入 CI 闸门。

## 9. 后续步骤

1. 确认第 2 节全部「待确认」事项，定稿本文档。
2. 填充各验证阶段的真实逻辑（运行/仿真/比对/质量），替换占位脚本。
3. 搭建 GitLab CE 与 Runner 的最小可用部署（POC）。
4. 验证仿真串行调度与不可信代码隔离的有效性。
5. 接入指标统计与质量门禁，跑通端到端评测。
