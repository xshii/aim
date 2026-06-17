# AI 验证代码仓库 — CI 系统需求说明与技术选型

> 文档目的：为 AI 代码生成 Benchmark 评测仓库的持续集成（CI）系统提供需求规格与技术选型依据，作为后续设计与实施的基线。
> 文档层级：**Spec（规格）** — 受 `00_constitution.md` 约束。是需求的累积式事实源（source of truth）。
> 上游：`00_constitution.md`（不可协商原则）。下游：`05_jenkins_design.md`（Jenkins 设计）→ 代码。
> 状态：v1.3。需求采用累积编号 + 状态（Draft/Accepted/Implemented）。
> 决策记录见第 8 节。
> **CI 框架=Jenkins（离线部署）；代码托管用内网现有仓库。详细设计见 `docs/05_jenkins_design.md`。**

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
| O-3 | 仿真并发限制 | ✅ 已确认 | **每仿真器按 license 限并发（同仿真器串行）、不同仿真器可并行**（throttle 类别 + numExecutors） |
| O-4 | 仓库是否接受外部贡献 | ✅ 已确认 | **仅内部私有**（不可信代码隔离策略可适度简化） |
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

针对仿真软件的并发约束，CI 须保证同一仿真器的并发不超过其 License 数（默认每仿真器 1，即同仿真器串行），其余排队等待，不得因抢占导致 License 冲突或工具状态污染；**不同仿真器相互独立，可并行**。**实现（D-016 Jenkins）：每个仿真器一个 throttle-concurrents 类别（`maxConcurrentTotal` = 该仿真器 license 数），仿真 job 用 `throttle(['<类别>'])` 引用 → 同仿真器串行/限并发、不同仿真器并行；`numExecutors` = 总并行能力（可配 `[jenkins] executors`）。** 见 `server/deploy/jenkins.yaml`（JCasC）。

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

CI 平台须可在内网首次离线搭建。Jenkins 离线部署（.deb + apt）：有网机 `fetch_offline.py` 下 jenkins/java 的 `.deb` + plugin-cli jar 到 `tools/ci/local/offline/`；内网 `deploy.py` 用 apt 装 `.deb`、用 plugin-cli 从内源 UC 装插件、渲染 JCasC、配 systemd（deb 自带 `jenkins.service` + `ci-webhook` 适配器）。Jenkins admin 密码经 `config.local.ini [secrets]` → systemd EnvironmentFile(0600) 注入，不入仓不落命令行（C-1）。见 `server/deploy/`、`docs/05_jenkins_design.md`、`docs/OFFLINE_DEPENDENCIES.md`。

**FR-10 Jenkins 插件清单**

须固化 Jenkins 所需插件清单（`server/deploy/plugins.txt`），`deploy.py` 用 plugin-cli 从**内源 Update Center**
（`[jenkins] update_center_url`）按清单装，依赖自动解析。必装：`git`/`workflow-aggregator`(pipeline)/
`configuration-as-code`(JCasC)/`job-dsl`(建 job)/`throttle-concurrents`(仿真串行类别 sim-license，D-003)；
可选：`mcp-server`(MCP)。Jenkins `-Djenkins.install.runSetupWizard=false`，不对外联网上报/遥测（C-1）。

**FR-11 离线 / 单端口 / 一键部署**

CI 系统须适配受限内网：(a) 全部脚本为 python3 3.8 标准库实现，零第三方依赖；(b) 依赖离线传入（不 git clone），见 `OFFLINE_DEPENDENCIES.md`；(c) 部署两段式——首次经执行机 SSH/SCP 远端 bootstrap（FR-16），代码到位后在服务器上一键跑 `server/deploy/deploy.py`；日常触发走 HTTP，不依赖常驻隧道；(d) 所有可变参数归一到 `config.ini`，敏感项归一到 `config.local.ini`（不入仓）。决策依据见 D-004、D-008、D-009、D-010。

**FR-12 开发端 CI 操作 MCP**

须提供 MCP 作为开发端查询 CI 的接口：查构建状态、拉错误日志。**实现（D-016）：用 Jenkins 官方 `mcp-server` 插件（装上即暴露 job/build 为 MCP 工具），不再自写 MCP。** 凭证（admin + API token）经环境变量/客户端配置，不入仓（C-1）。触发构建用 webhook，不在此。MCP 与被测代码无关。决策依据见 D-006。

**FR-13 验证预生成代码（多种验证）**

CI 不在内部生成代码；输入为预生成的成品代码。CI 须支持多种验证并收集其 output 与状态：运行型（经超时+资源限制执行）、仿真型（喂仿真软件，按仿真器 throttle 限并发）、比对型（与答案比对）、质量检查型（静态）。结果聚合后用于指标与质量门禁。决策依据见 D-008。

**FR-14 webhook / token 触发构建**

须支持网页/外部经 webhook（HTTP）触发构建。**实现（D-016/D-017）：内源代码托管站的入站 webhook 经 `server/webhook/receiver.py` 适配器接入（X-Devcloud-Token 校验，FR-19）→ 调 Jenkins `buildWithParameters`（GIT_URL/GIT_SHA/BRANCH）触发 job。** Jenkins HTTP 同机直达，无需 ssh/隧道。说明见 `server/webhook/`。

**FR-15 端口固定与白名单**

Jenkins 与 webhook 适配器端口由 `config.ini [jenkins] http_port` / `[webhook] listen` 固定，须经
白名单（80-90/443/8080-8090）校验（`deploy.py check`），且两端口不同（同机两服务）。

**FR-16 远端首次部署（SSH/SCP bootstrap）**

首次在内网新机搭建时，允许从一台「代码执行机」经 SSH/SCP 把全量代码与离线依赖推送到目标
服务器的部署目录，再经 SSH 远程执行 `deploy.py`。此为 D-008「服务器本地部署」的**首次
bootstrap 补充**，非取代：日常触发仍用 HTTP（FR-14），不依赖常驻 ssh 隧道。连接参数来自
`config.ini [remote]`；ssh 私钥留本地 `~/.ssh`，严禁入仓（C-1, D-009）。决策见 D-010。

**FR-17 离线依赖获取（手动 / 自动）**

Jenkins 离线件（jenkins/java 的 `.deb` + plugin-cli jar）在**有网机**经 `local/admin/fetch_offline.py` 下载到
`tools/ci/local/offline/`，随 FR-16 推送到远端 `[offline] deps_dir`。下载经环境变量 `HTTPS_PROXY`（**含明文密码，
严禁入仓**，仅置环境变量，C-1）。版本/URL 在 `config.ini [fetch]`、清单见 `OFFLINE_DEPENDENCIES.md`。决策见 D-010。

**FR-18 部署前连通性测试**

提供轻量连通性自测（python3 标准库）：目标服务器 SSH 可达且远端有 python3、远端管理员权限、
（可选）webhook 目标可达。失败即明确报告缺失项并停止（C-10），不在缺信息时
继续。**当 SSH 端口可达但密钥认证失败，且运行在交互式终端（TTY）下，经用户确认后运行
`ssh-copy-id` 安装本地公钥（交互输入一次密码），装毕重测；非 TTY 或本地无公钥则按原逻辑报告
失败、不自动改远端状态（C-10）。** **SSH 鉴权通过后，校验远端登录用户具备管理员权限（root，或在 sudo/wheel/admin
组——含需密码 sudo，部署时整个 deploy.py 经 sudo 提权运行、交互输一次 sudo 密码）——一键部署需
dpkg/systemctl 等特权操作；权限不足即明确报告并停止（C-10），避免部署中途因权限失败。** 见 `local/admin/connectivity.py`。

**FR-19 内源托管 webhook 接入（X-Auth）**

提供轻量 webhook 适配器（python3 标准库 `http.server`），接受内部代码托管站的入站 webhook：
以可配置请求头（`X-Devcloud-Token`）做**共享密钥常量时间校验**，解析 push payload 后**调 Jenkins
`buildWithParameters`（Basic Auth + CSRF crumb）触发评测 job**（D-016/D-017）。共享密钥与 Jenkins
admin 密码**不入仓**（环境变量 / `config.local.ini`，C-1）。见 `server/webhook/receiver.py`。决策见 D-011、D-017。

**FR-20 MCP 标准化与 opencode 接入**

开发端 MCP 须可由 opencode CLI 等标准 MCP 客户端接入。**实现（D-016）：Jenkins `mcp-server` 插件
暴露 HTTP MCP 端点，opencode 经 `opencode.json` 的 mcp(remote) 接入（见 `local/mcp/opencode.json.example`）；
不再自写 stdio MCP。** 凭证经客户端配置注入（C-1）。决策见 D-012、D-016。

**FR-21 任务队列与调度**

webhook 触发的评测构建由 Jenkins 自带队列与执行器调度：`numExecutors`=总并行（可配），单仿真器由 throttle 类别限其 license，同分支
auto-cancel（`disableConcurrentBuilds(abortPrevious)`）；构建列表、状态、控制台日志由 Jenkins Web UI 提供。

### 3.1.1 功能性需求状态总表

| 编号 | 名称 | 状态 |
|------|------|------|
| FR-1 | 触发机制（分层） | Accepted |
| FR-2 | 评测执行编排 | Accepted（Jenkins pipeline 编排，D-016） |
| FR-3 | 仿真任务串行调度 | Accepted（本期实现） |
| FR-4 | 模型响应缓存 | Accepted（后续迭代） |
| FR-5 | 结果产出与持久化 | Accepted（后续迭代） |
| FR-6 | 指标统计与报告 | Accepted（eval.py 产出 qsort_eval.json；聚合看板后续迭代） |
| FR-7 | 质量门禁 | Accepted（eval.py 退出码 + Jenkins 构建状态） |
| FR-8 | 任务发现 | Accepted（后续迭代） |
| FR-9 | CI 平台自托管搭建（Jenkins 离线部署） | Accepted（本期实现） |
| FR-10 | Jenkins 插件清单 | Accepted（本期实现） |
| FR-11 | 离线/服务器本地一键部署 | Accepted（本期实现） |
| FR-12 | 开发端 MCP 查询（Jenkins mcp-server 插件） | Accepted（D-016，无自写代码） |
| FR-13 | 验证预生成代码（多种验证） | Accepted（本期实现） |
| FR-14 | webhook 触发构建（→Jenkins buildWithParameters） | Accepted（本期实现） |
| FR-15 | 端口固定与白名单校验 | Accepted（本期实现） |
| FR-16 | 远端首次部署（SSH/SCP bootstrap） | Accepted（本期实现） |
| FR-17 | 离线依赖获取（Jenkins 离线包） | Accepted（本期实现） |
| FR-18 | 部署前连通性测试 | Accepted（本期实现） |
| FR-19 | 内源托管 webhook 接入（X-Devcloud-Token） | Accepted（本期实现） |
| FR-20 | MCP 标准化与 opencode 接入（Jenkins 插件） | Accepted（D-016，无自写代码） |
| FR-21 | 任务队列与调度（Jenkins 自带） | Accepted（本期实现） |

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
| server·部署 | 服务器本地离线装 Jenkins（手动跑，需 root） | `server/deploy/`（deploy.py / plugins.txt / jenkins.yaml / systemd/） |
| server·运行时 | Jenkins 自动执行的验证链路（D-016） | `server/deploy/jenkins.yaml`(JCasC pipeline)、`server/harness/limited_run.py`(NFR-3)、`server/webhook/`、`server/demo/qsort/eval.py` |
| local·首次 | 客户端：下离线件 + 远端 bootstrap（SSH/SCP） | `local/admin/`（fetch_offline.py / deploy_remote.py / connectivity.py）、`local/offline/`（离线件暂存） |
| local·查询 | 开发端日常查 CI（接 Jenkins mcp-server 插件） | `local/mcp/opencode.json.example`（指向 Jenkins MCP，无自写代码，D-016） |

### 4.3 MCP 定位说明

MCP 是给**开发端**（人 / AI 助手）查 CI 的接口：查构建状态、拉错误日志。经 Jenkins 官方
`mcp-server` 插件的 MCP 端点（D-016，无自写代码）。触发构建用 webhook。与被测代码无关。见第 8 节 D-006。

## 5. 技术选型

### 5.1 选型原则

1. 满足 NFR-1（不外泄）：必须可完全自托管。
2. 满足 NFR-6（商业友好）：OSI 宽松许可，排除 SaaS-first 方案与 BSL/SSPL 许可工具。
3. 满足 NFR-4（无容器）：执行不依赖 Docker。
4. 满足 NFR-2（仿真串行）：具备资源独占/串行调度能力。

> 注：CI 工具的许可证与定价条款可能随时间变动，正式采用前须以各项目官网当前条款为准。

### 5.2 CI 框架：Jenkins

**本系统采用 Jenkins（离线部署）。** 标准特性开箱：pipeline-as-code、auto-cancel、Web UI、官方 MCP 插件。
代码托管用**内网现有仓库**（不新建），Jenkins 只做 CI。详见 `05_jenkins_design.md`。

| 维度 | Jenkins（现采用） |
|------|------|
| 许可证 | MIT（免费商用，NFR-6） |
| 自托管不外泄 | 支持；离线部署（jenkins/java 的 .deb apt 安装；插件从内源 UC，NFR-1/FR-9） |
| 仿真并发控制 | 每仿真器一个 throttle 类别（限其 license 数）→ 同仿真器串行、不同仿真器并行；`numExecutors`=总并行（可配） |
| 无 Docker 执行 | 内置节点直接执行 shell（NFR-4） |
| 配置方式 | Pipeline(Groovy) + JCasC 配置即代码（D-018，随配置版本化，NFR-5/NFR-7） |
| 插件安全 | 最小化插件清单 `plugins.txt`，跟踪 CVE |

> Jenkins 用 LTS `.deb` + 官方插件（MIT/宽松许可，NFR-6）；不启用任何对外联网上报/遥测（C-1）。

### 5.3 运行型验证的限制（超时 + 资源）

CI 验证的是预生成成品代码，环境为封闭内网 + 内部私有，故不做 namespace 级强隔离。
运行型验证经 `limited_run.py` 加超时与资源限制（RLIMIT_AS/CPU/NOFILE + 墙钟），
仅防资源耗尽与卡死。决策见第 8 节 D-005。

### 5.4 CI Executor 与串行控制

- **Executor**：Jenkins 内置节点直接执行 shell（不依赖 Docker，NFR-4）；不可信代码经 `limited_run.py` 加超时+资源限制（NFR-3）。
- **并发控制**：每个仿真器一个 throttle-concurrents 类别（`maxConcurrentTotal`=该仿真器 license 数）→ 同仿真器串行/限并发、不同仿真器并行（D-003）；`numExecutors`=总并行能力（可配 `[jenkins] executors`）。同分支 auto-cancel 由 job 的 `disableConcurrentBuilds(abortPrevious)` 保证。

### 5.5 配套组件

| 用途 | 选型方向 | 许可考量 |
|------|---------|---------|
| 任务队列（如需更强调度） | Redis / 轻量队列 | 开源宽松许可 |
| 结果存储 | 对象存储 + PostgreSQL | 开源宽松许可 |
| 凭证管理 | Jenkins Credentials / systemd EnvironmentFile（0600，不入仓 C-1） | 宽松许可 |
| MCP（开发端查询 CI） | Jenkins 官方 mcp-server 插件 | 查 job/build 状态、拉日志 |

---

## 6. 部署拓扑

```
有网机（一次性）                               CI 服务器（内网，无外网）
└── fetch_offline.py 下 .deb + plugin-cli jar     ┌──────────────────────────────────────┐
                                                 │ Jenkins（.deb apt 装 + JCasC，HTTP 直连）│
执行机（admin）                                  │   └ qsort-eval pipeline job（参数化）   │
├── connectivity.py（连通性自检）                │   numExecutors=N 并行 + throttle 限仿真  │
└── deploy_remote.py ─SSH/SCP 推码+offline/─────▶ │ 评测：limited_run 限制 + eval.py 功能+性能│
                      └─SSH 远程触发 deploy.py──▶ │   → 退出码即门禁 + 归档 qsort_eval.json  │
内源代码托管站 ─webhook(X-Devcloud-Token)─▶ server/webhook/receiver.py ─buildWithParameters─▶│
开发端 opencode ──MCP（mcp-server 插件）查 job/build──────────────────────▶ └──────────────┘
```

说明：离线包先在有网机 `fetch_offline.py` 产出；首次经 SSH/SCP 远端 bootstrap（D-010），之后代码+离线包
已在服务器、本地直跑 `deploy.py`（D-008）。日常触发走 HTTP（webhook→适配器→Jenkins），不依赖常驻隧道。
适配器与 Jenkins 同机（适配器经 `127.0.0.1` 调 Jenkins）。

## 7. 安全要点小结

| 风险 | 控制措施 |
|------|---------|
| 验证代码资源耗尽/卡死 | limited_run 超时+资源限制（内存/CPU/文件数/墙钟） |
| 参考答案/凭证泄露 | 沙箱不挂载答案目录；凭证经 secret 管理注入，不落日志 |
| License/仿真工具被破坏或窃取 | 仿真机网络隔离，沙箱不可触及 License 服务器与工具二进制 |
| 不可信代码执行 | 仅内部私有仓库（O-4）；评测经 limited_run 限制；Jenkins 离线、不对外联网 |
| Jenkins 插件供应链风险 | 内源 Update Center、最小化插件清单 `plugins.txt`、跟踪 CVE |

---

## 8. 决策记录

记录当前生效的关键决策（决定 + 理由）。新增决策追加 D-NNN；不保留已废弃方案的历史。

| 编号 | 决策 | 理由 |
|------|------|------|
| D-001 | 自托管、信息不外泄 | 内部 benchmark/答案/License 不得外泄第三方 SaaS |
| D-003 | 仿真按 license 限并发（每仿真器一 throttle 类别） | 同仿真器不支持并行(串行/限其 license)、不同仿真器可并行 |
| D-004 | 纯 python3 标准库 + 离线依赖 | 服务器仅 python3 3.8、不装库、内网无外网 |
| D-005 | CI 只验证预生成代码；运行型仅超时+资源限制 | 代码为成品、封闭内网、内部私有，无需强隔离 |
| D-006 | MCP 给开发端查状态/拉日志 | 开发端（人/AI 助手）经 Jenkins mcp-server 插件查 job/build |
| D-007 | 触发用 webhook/token；ssh 私钥不入仓库 | 触发=HTTP，登录=ssh，二者分离 |
| D-008 | 部署 = 首次远端 bootstrap + 服务器本地一键部署；HTTP 直连 | 首次经 SSH/SCP 推码+离线包，之后服务器本地直跑；Jenkins 同机 HTTP 直连；端口 config 固定+白名单校验 |
| D-009 | 凭证 / 私钥 / 代理明文密码不入仓 | ssh 私钥留 ~/.ssh；密钥/token/代理密码仅置环境变量或 config.local.ini（gitignore），严禁入仓与 git 历史 |
| D-010 | 首次远端 bootstrap（执行机 SSH/SCP）+ 依赖可经代理自动获取 | 新机首搭需从执行机推码+依赖；执行机有外网（经代理），目标机内网无外网，故下载在执行机、明文代理不入仓 |
| D-011 | 内源 webhook 用独立 stdlib 接收器 + X-Auth 共享密钥 | 自定义鉴权头不耦合进平台；常量时间校验后触发；密钥不入仓 |
| D-012 | MCP 走标准协议（opencode 兼容） | 标准 MCP 握手 + inputSchema，便于 opencode 等客户端接入 |
| D-016 | 采用 Jenkins 作 CI 框架（离线部署） | 标准特性开箱（pipeline/auto-cancel/UI/官方 MCP 插件）；代码托管用内网现有仓库，Jenkins 只做 CI |
| D-017 | 保留 webhook 适配器（非 Generic Webhook Trigger 插件） | 内部开源用 X-Devcloud-Token 头 + 复杂 payload，适配器复用已验证校验/解析、解耦内部开源与 Jenkins |
| D-018 | JCasC 配置即代码 | 离线可复现 Jenkins 配置（admin/job/串行/MCP），免手动点 UI |

### 关键决策详述

**D-003 仿真按 license 限并发**：同一仿真器不支持并行（或不超过其 License 数），不同仿真器相互独立可并行。
Jenkins：每个仿真器一个 throttle-concurrents 类别（`maxConcurrentTotal` = 该仿真器 license 数），仿真 job
用 `throttle(['<类别>'])` 引用 → 同仿真器串行/限并发、不同仿真器并行；`numExecutors` = 总并行能力（可配
`[jenkins] executors`），不得虚高于真实并行能力。**"同仿真器不超 license 数"是贯穿全程不可动摇的硬约束（C-3）。**

**D-005 验证预生成代码**：CI 不在内部生成代码，输入是预生成成品；做多种验证（运行/仿真/
比对/质量检查）并收集 output 与状态。运行型验证经 `limited_run.py` 加超时+资源限制
（RLIMIT_AS/CPU/NOFILE + 墙钟），防资源耗尽与卡死，不做 namespace 强隔离。

**D-007 触发与登录权限分离**：日常构建经 webhook → 适配器 → Jenkins `buildWithParameters`（HTTP）
触发，见 `server/webhook/`。触发是 HTTP 行为，不需 ssh；ssh 仅用于首次远端 bootstrap（D-010）。ssh 私钥仅管理员部署/维护用，
留本地 `~/.ssh/`，**严禁入仓库**（含 git 历史；C-1）。token 可吊销轮换、权限仅触发；私钥能登录
操作系统、后果严重，二者分离。

**D-008 部署两段式：首次远端 bootstrap + 服务器本地部署**：部署分两段，互补而非二选一。
(1) **首次 bootstrap（local/admin）**：新机首搭时，从执行机经 SSH/SCP 把全量 `tools/ci` 代码（含
`offline/` 离线件）推到目标机（`deploy_remote.py push`），再经 SSH 远程触发服务器本地部署；
(2) **服务器本地部署（server/deploy）**：代码+offline/ 到位后在服务器上直接跑 `deploy.py`，apt 装 jenkins/java
的 `.deb`、用 plugin-cli 从内源 UC 装插件、渲染 JCasC、配 systemd（deb 自带 `jenkins.service` + `ci-webhook` 适配器）。日常构建触发走 HTTP
（FR-14），不依赖常驻 ssh/隧道。Jenkins HTTP 同机直达；端口由 `config.ini [jenkins] http_port` 固定并经
白名单（80-90/443/8080-8090）校验（deploy.py check）。

**D-009 凭证 / 私钥 / 代理明文密码不入仓**：ssh 私钥仅留管理员本地 `~/.ssh`；webhook 共享密钥、
Jenkins admin 密码、HTTP(S) 代理的明文密码（`user:pass@proxy`）一律不写入仓库与 git 历史，只经
环境变量或 `config.local.ini` 注入（`.gitignore` 的 `*.local.ini` 已忽略）。`ci_config.load()`
自动叠加 `config.local.ini` 覆盖，`secret()` 优先取环境变量；部署时 deploy.py 把密钥写入 systemd
EnvironmentFile（0600）供服务读取。

**D-010 首次远端 bootstrap + 离线件获取**：内网新机无外网、不能 git clone / 在线装插件。故 Jenkins 离线件
（jenkins/java 的 `.deb` + plugin-cli jar）在**有网机**经 `fetch_offline.py` 下载到 `tools/ci/local/offline/`（走 `HTTPS_PROXY`
环境变量，明文密码不入仓），再随代码经 SSH/SCP 推到远端 `<dest>/offline`。传输用 OpenSSH `ssh`/`scp`。

**D-011/D-017 内源 webhook：独立适配器 + X-Devcloud-Token**：内部代码托管站经入站 webhook 触发评测。用
独立 stdlib HTTP 适配器（`server/webhook/receiver.py`）校验请求头 `X-Devcloud-Token` 的共享密钥
（`hmac.compare_digest` 常量时间比较），解析 push payload 后调 Jenkins `buildWithParameters`（Basic Auth
+ CSRF crumb）触发 job。把自定义鉴权与 Jenkins 解耦；共享密钥与 Jenkins admin 密码经环境变量/`config.local.ini` 注入（C-1）。

**D-012/D-016 MCP（Jenkins 官方插件，opencode 兼容）**：开发端 MCP 由 Jenkins 官方 `mcp-server` 插件提供
（装上即暴露 job/build 为 MCP 工具），不再自写。opencode 等客户端经 `opencode.json` 的 mcp(remote) 接入
Jenkins MCP 端点（见 `local/mcp/opencode.json.example`）；凭证用 admin + API token，经客户端配置注入（C-1）。

### 变更规则（SDD）

文档分层：`00_constitution.md`（宪法）→ `01_spec.md`（需求+决策）→ `05_jenkins_design.md`（Jenkins 设计）
→ 代码（`server/`、`local/`、共享层）。变更单向流动；重要取舍在本章追加 D-NNN。禁止只改代码不回改
spec；同一事实只在一处定义。一致性由 `checks/consistency.py` 校验，接入 CI 闸门。

## 9. 后续步骤

1. 确认第 2 节全部「待确认」事项，定稿本文档。
2. 在内网起 Jenkins，跑通完整链路 e2e（webhook→适配器→Jenkins→limited_run+eval）；重点验 JCasC 加载与 mcp-server 插件端点。
3. 扩展评测：qsort 之外接入更多 Benchmark 题（eval.py 模式），聚合指标看板（FR-6 后续迭代）。
4. 验证仿真串行调度与不可信代码隔离的有效性。
5. 接入指标统计与质量门禁，跑通端到端评测。
