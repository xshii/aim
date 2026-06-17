# tools/ci — CI 系统（Spec-Driven，精简版）

AI 代码生成 Benchmark 评测仓库的 CI 系统。**CI 验证预生成的成品代码**（不在内部生成代码），
做多种验证（功能/性能/比对/质量检查）并收集 output 与状态。**CI 框架=Jenkins（D-016，离线部署）**；
代码托管用内网现有仓库（不新建）。脚本纯 python3（3.8 标准库、零依赖），依赖离线传入。

## 执行角色（目录即角色）

```
tools/ci/
├── ci_config.py  config.ini  config.local.ini.example   ← 共享层（角色中立）
├── checks/consistency.py  gen_quick_deploy.py  constants.py  docs/  README.md
├── server/                 ← 在 CI 服务器上执行
│   ├── deploy/   deploy.py / fetch_offline.py / plugins.txt / jenkins.yaml(JCasC) / systemd/
│   ├── webhook/  receiver.py（→Jenkins 适配器） / test_receiver.py / README.md
│   ├── harness/  limited_run.py（NFR-3：Jenkins eval stage 经它套超时+资源限制）
│   └── demo/qsort/   qsort.c / cases.txt / eval.py（功能+性能，退出码即门禁）
└── local/                  ← 在客户端 / 执行机上执行
    ├── admin/    deploy_remote.py / connectivity.py   （首次 SSH/SCP bootstrap）
    └── mcp/      opencode.json.example   （指向 Jenkins 官方 mcp-server 插件）
```

| 角色 | 谁/何时 | 入口 |
|------|---------|------|
| **有网机·一次性** | 产出离线件（jenkins .deb + 插件 + java .deb） | `python3 server/deploy/fetch_offline.py` |
| **local/admin** | 客户端·首次，从执行机远端 bootstrap | `python3 local/admin/deploy_remote.py all` |
| **server/deploy** | 服务器·部署时（需 root） | `sudo python3 server/deploy/deploy.py all` |
| **server·运行时** | Jenkins 自动执行评测 | JCasC 预配的 pipeline job（checkout → `python3 eval.py .`） |
| **local/mcp** | 开发端·查询 | opencode 接 Jenkins `mcp-server` 插件 |

## 部署三段式

详见 `docs/quick_deploy.md`（由 config.ini 自动生成，命令以它为准）。

**0. 离线件（有网机，一次性）**
```bash
# 改 config.ini [fetch] 版本/URL 为内网可下版本（见 docs/OFFLINE_DEPENDENCIES.md）
python3 server/deploy/fetch_offline.py     # 下 jenkins .deb + 插件 到 tools/ci/offline/
# Java：把 JDK/JRE 21 的 .deb 也放进 tools/ci/offline/
```

**A. 首次远端 bootstrap（在执行机上，新机首搭用）**
```bash
# 填 config.ini [remote]（目标机 host/user/dest）
python3 local/admin/deploy_remote.py all   # 连通性自检 → SSH/SCP 推代码+offline/ → 远程跑 deploy.py
```

**B. 服务器本地部署（代码+offline/ 到位后在服务器上，需 root）**
```bash
cd /opt/ci
sudo python3 server/deploy/deploy.py all   # 自检 → apt 装 .deb + 放插件 + JCasC → systemd(jenkins+ci-webhook)
```

## 离线依赖

见 `docs/OFFLINE_DEPENDENCIES.md`：有网机 `fetch_offline.py` 下 jenkins `.deb` + 插件到 `tools/ci/offline/`；
Java 21 的 `.deb` 一并放入。插件清单在 `server/deploy/plugins.txt`，版本/URL 在 `config.ini [fetch]`。

## 触发构建

- **内源代码托管站**：push → `server/webhook/receiver.py` 适配器（校验 `X-Devcloud-Token` 共享密钥）
  → 调 Jenkins `buildWithParameters` 触发 job（GIT_URL/GIT_SHA/BRANCH）。见 `server/webhook/README.md`。
- 密钥 / Jenkins admin 密码经 env / `config.local.ini [secrets]`，不入仓（C-1）。

## 查状态 / 拉日志（MCP，接 opencode）

Jenkins 装官方 `mcp-server` 插件后自带 MCP 端点（job/build 工具），无需自写。opencode 接入见
`local/mcp/opencode.json.example`。构建列表/控制台日志也可直接看 Jenkins UI。

## qsort 评测 demo（本机可验，无需 Jenkins）
```bash
python3 server/demo/qsort/eval.py server/demo/qsort   # 编译 → 功能用例比对 + 性能耗时，期望全过
python3 server/webhook/test_receiver.py               # 适配器单测（mock Jenkins）
```
Jenkins pipeline 的评测 stage 即 `python3 eval.py .`（被测仓库根含 eval.py）。

## SDD 文档层级

| 层 | 文件 | 回答 |
|----|------|------|
| 宪法 | `docs/00_constitution.md` | 不可违反的原则（C-1~C-10） |
| 规格 | `docs/01_spec.md` | 是什么/为什么 + 需求(FR/NFR) + 决策记录(D-001~D-018) |
| 设计 | `docs/05_jenkins_design.md` | Jenkins 路线设计与实现阶段 |

一致性由 `checks/consistency.py` 校验（spec 需求编号 ↔ 代码 `implements:` 双向对齐），接入 CI 闸门。

## 关键设计

- **CI 框架 Jenkins**（D-016）：标准特性开箱（pipeline-as-code、auto-cancel、Web UI、官方 MCP 插件）；
  .deb + apt 离线安装（jenkins/java 的 .deb + 插件，JCasC 配置即代码 D-018）。
- **webhook 适配器**（D-017）：内源 X-Devcloud-Token 头 + 复杂 payload，复用已验证校验/解析，解耦 Jenkins。
- **仿真严格串行**（D-003）：Jenkins `numExecutors=1`（单节点同一时刻仅 1 个构建 = License 数）。
- **凭证不入仓**（C-1/D-009）：私钥留 ~/.ssh；webhook 密钥/Jenkins admin 密码经 env 或 `config.local.ini`。
- **纯 python3 标准库**：适配器/部署/取包脚本无第三方依赖；Jenkins 本体离线传入。
