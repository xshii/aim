# Jenkins CI 路线设计

> 状态：已实现（阶段 1-6 完成）。本文件是本次重构的 spec。
> 决策：弃自研调度器，改用 Jenkins（D-016）。从头重写，不沿用自研调度器代码。
> 自研版留底：git tag `scheduler-v1`（`git checkout scheduler-v1` 可恢复）。

## 1. 背景与动机

自研调度器（D-013）已完整可用，但 CI 需求持续向"通用 CI 平台"生长（pipeline 配置、多任务、auto-cancel…），每个特性都要自己实现 = 重造 Jenkins。决定改用 Jenkins：标准特性开箱（pipeline-as-code、auto-cancel、Web UI、官方 MCP 插件），不再自己造。

代码托管仍用**内网现有仓库**（不新建）；Jenkins 只做 CI。Jenkins 离线部署可行（jenkins/Java21 的 `.deb` apt 安装；插件经 plugin-cli 从内源 Update Center 装）。

## 2. 目标与非目标

**目标**
- Jenkins 离线部署（内网无外网，jenkins/java 的 .deb apt 安装；插件从内源 UC；JCasC 可复现配置）
- 接内部开源 webhook（X-Devcloud-Token + push payload）触发评测
- 评测 qsort 功能 + 性能（复用 `eval.py`）
- 仿真串行（并发=License 数）
- auto-cancel（同分支新提交取消旧构建）
- MCP 查 job/build（接 opencode）

**非目标**
- 不托管代码（用内网现有仓库）
- 不自研调度/队列/UI（用 Jenkins 自带）
- 不做多 master/分布式（单 Jenkins 起步）

## 3. 架构

```
内部开源仓库 push
   │ webhook(POST, X-Devcloud-Token 头, push payload)
   ▼
┌──────────────────────────────┐
│ webhook 适配器 receiver.py     │ 校验 X-Devcloud-Token + 解析 payload
│ (复用已验证逻辑，后端改 Jenkins)│ → 调 Jenkins REST buildWithParameters
└─────────────┬────────────────┘   (GIT_URL, GIT_SHA, BRANCH)
              ▼
┌──────────────────────────────┐
│ Jenkins job (Jenkinsfile)     │ git checkout <sha>
│  options: disableConcurrent-  │ → sh: python3 eval.py .  (功能+性能)
│    Builds(abortPrevious)       │ → archiveArtifacts qsort_eval.json
│  throttle/lock: 串行           │ → 结果(成功/失败)
└─────────────┬────────────────┘
              ▼
   Jenkins Web UI(自带) / MCP 插件(接 opencode)
```

**为何保留 webhook 适配器**（而非纯 Generic Webhook Trigger 插件）：内部开源用 `X-Devcloud-Token` **请求头**认证 + 复杂 push payload；适配器复用已验证的校验/解析逻辑，且解耦（内部开源不需知道 Jenkins job/token 细节）。Generic Webhook Trigger 配 header token + JSONPath 繁琐且多一个插件依赖。

## 4. 组件设计

### 4.1 离线部署 `server/deploy/`
- **离线件获取**（有网机器，一次性）：`fetch_offline.py`（读 `config.ini [fetch]` 版本/URL）—— 下 jenkins `.deb` + plugin-cli 工具 jar，产出到 `tools/ci/local/offline/`；Java21 的 `.deb` 一并放入。**插件不离线传**，由服务器从内源 UC 装。
- **插件清单** `plugins.txt`：`git`、`workflow-aggregator`(pipeline)、`configuration-as-code`(JCasC)、`throttle-concurrents`(串行)、`mcp-server`(MCP) 及其依赖（工具自动解）。
- **部署** `deploy.py`（在内网服务器，需 root）：`apt-get install ./offline/*.deb`（jenkins+java 一起，apt 解依赖）、用 plugin-cli 从内源 UC（`[jenkins] update_center_url`）按 `plugins.txt` 装插件到 `/var/lib/jenkins/plugins`、渲染 JCasC `jenkins.yaml`、写 systemd drop-in 覆盖 deb 自带的 `jenkins.service`（端口/JCasC/admin 密码）、启用。webhook 适配器同机起 `ci-webhook.service`。
- 端口：Jenkins 与 webhook 适配器端口仍受白名单约束（80-90/443/8080-8090），`deploy.py check` 校验。

### 4.2 JCasC 配置 `server/deploy/jenkins.yaml`
Configuration-as-Code 声明式预配（离线可复现，免手动点 UI）：admin 用户、跳过 setup wizard、qsort job(pipeline from SCM 或内联 Jenkinsfile)、throttle 串行类别、API token（供适配器调用）。

### 4.3 webhook 适配器 `server/webhook/receiver.py`（重写）
- 保留：`X-Devcloud-Token`（`hmac.compare_digest`）+ `_parse()`（`project.git_ssh_url`/`checkout_sha`/分支）。
- 改：校验解析后 → `urllib` POST Jenkins `/job/<name>/buildWithParameters?GIT_URL=..&GIT_SHA=..&BRANCH=..`（带 Jenkins API token/crumb）。
- 幂等/auto-cancel 交给 Jenkins（job 的 `disableConcurrentBuilds(abortPrevious)`）。
- 同样的端口白名单 + token 不入仓（config.local.ini）。

### 4.4 Jenkinsfile（仓库根 或 JCasC 内联）
```groovy
pipeline {
  agent any
  options { disableConcurrentBuilds(abortPrevious: true) }   // auto-cancel
  parameters { string(name:'GIT_URL'); string(name:'GIT_SHA'); string(name:'BRANCH') }
  stages {
    stage('checkout') { steps { git url: params.GIT_URL; sh "git checkout ${params.GIT_SHA}" } }
    stage('功能+性能评测') { steps { sh 'python3 eval.py .' } }   // eval.py 内含功能+性能两项
  }
  post { always { archiveArtifacts artifacts: 'qsort_eval.json', allowEmptyArchive: true } }
}
```
串行：throttle-concurrents 全局/类别限 1（=License 数），或 `lockable-resources` 锁 `sim-license`。

### 4.5 MCP
官方 `mcp-server-plugin`（装上自动暴露 job/build 为 MCP tools）。opencode 经 MCP 客户端连 Jenkins MCP 端点。无需自写。

### 4.6 评测（复用）
`server/demo/qsort/eval.py`（功能+性能）平台无关，Jenkinsfile 直接 `python3 eval.py .` 跑。qsort demo（qsort.c/cases.txt/eval.py）作为被测仓库样例。

## 5. 删 / 改 / 留

- **删**：`server/scheduler/`（db/worker/checkout/测试/smoke/e2e）、`server/deploy/systemd/ci-webhook|ci-worker`（自研版）、自研 `01_spec` 中调度器专属内容、`03_scheduler_design.md`/`04_scheduler_plan.md`（自研 spec/plan，归档或删）
- **改**：`server/webhook/receiver.py`（→Jenkins 适配器）、`server/deploy/deploy.py`（→Jenkins 离线部署）、`config.ini`（Jenkins 配置）、`constants.py`（保留 webhook/payload 常量，去掉任务状态）、`gen_quick_deploy.py`（→Jenkins 流程）、`local/mcp/`（删自写 MCP，改文档指向 Jenkins MCP 插件）
- **留**：`server/demo/qsort/`（qsort.c/cases.txt/eval.py）、`local/admin/connectivity.py`（bootstrap 连通性/权限校验）、`local/admin/deploy_remote.py`（SSH/SCP bootstrap，调整推送内容）、`checks/consistency.py`、`docs/00_constitution.md`

## 6. 验证（含局限，诚实标注）

- **本机可验**：Jenkinsfile 语法（`jenkins-cli` 或 lint）、`eval.py`（功能+性能，已验证）、webhook 适配器单测（token 校验+payload 解析+构造 Jenkins 调用 URL，mock Jenkins）。
- **需真机**：完整链路（webhook→适配器→Jenkins→job→eval）需起 Jenkins(.deb + Java21)；本机无 Jenkins 时无法 e2e。
- **离线件获取**：需一台有网机器下 jenkins/java 的 `.deb` + plugin-cli jar（一次性）；插件从内源 UC。

## 7. 实现阶段

1. webhook 适配器 `receiver.py` 重写（token+payload→Jenkins buildWithParameters）+ 单测（mock Jenkins）
2. Jenkinsfile + JCasC `jenkins.yaml`（job/串行/auto-cancel/token）
3. 离线部署：`plugins.txt` + `fetch_offline.py`(有网下 .deb+plugin-cli) + `deploy.py`(内网 apt 装 + 内源 UC 装插件 + systemd) + 端口校验
4. 删自研调度器 + config/constants/spec/一致性闸门同步
5. `gen_quick_deploy` 改 Jenkins 流程 + 文档（MCP 指向官方插件、卸载）
6. 一致性闸门通过 + 本机可验项（适配器单测、eval、Jenkinsfile lint）通过

## 8. 决策记录

- **D-016 弃自研调度器，改用 Jenkins**：CI 需求向通用平台生长，自研每特性都要自造=重造 Jenkins；Jenkins 标准特性开箱（pipeline/auto-cancel/UI/官方 MCP 插件）。代价：本机无法完整 e2e（需 Jenkins 环境）、离线部署需获取 jenkins/java 的 .deb + plugin-cli。自研版 git tag `scheduler-v1` 留底。
- **D-017 保留 webhook 适配器**：内部开源用 X-Devcloud-Token 头 + 复杂 payload，适配器复用已验证校验/解析、解耦内部开源与 Jenkins，优于 Generic Webhook Trigger 插件的繁琐配置。
- **D-018 JCasC 配置即代码**：离线可复现 Jenkins 配置（admin/job/串行/token），免手动点 UI。
