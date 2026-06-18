# tools/ci — CI 系统（Spec-Driven，精简版）

AI 代码生成 Benchmark 评测仓库的 CI 系统。**CI 验证预生成的成品代码**（不在内部生成代码），
做多种验证（功能/性能/比对/质量检查）并收集 output 与状态。**CI 框架=Jenkins（D-016，离线部署）**；
代码托管用内网现有仓库（不新建）。脚本纯 python3（3.8 标准库、零依赖），依赖离线传入。

## 执行角色（目录即角色）

```
tools/ci/
├── ci_config.py  config.ini  config.local.ini.example   ← 共享层（角色中立）
├── docs/  README.md
├── server/                 ← 在 CI 服务器上执行
│   ├── deploy/   deploy.py / plugins.txt / jenkins.yaml(JCasC,组织文件夹) / systemd/
│   ├── harness/  limited_run.py（NFR-3：eval/仿真经它套超时+资源限制）
│   └── demo/qsort/   qsort.c / cases.txt / eval.py（功能+性能，退出码即门禁）
└── local/                  ← 在有网机上执行
    ├── admin/    fetch_plugins.py（curl 下插件+依赖、sha256 校验、闭包自检、打 tar.gz）
    ├── offline/  离线件暂存（jenkins/java .deb + plugins/*.hpi + tar.gz；大文件 .gitignore，仅占位入仓）
    └── mcp/      opencode.json.example   （指向 Jenkins 官方 mcp-server 插件）
```

| 角色 | 谁/何时 | 入口 |
|------|---------|------|
| **有网机·一次性** | 下插件+依赖打 tar.gz；手动下 jenkins/java 的 .deb | `python3 local/admin/fetch_plugins.py` |
| **server/deploy** | 服务器·部署时（需 root，离线件手动拷到位后） | `sudo python3 server/deploy/deploy.py all` |
| **server·运行时** | git push → 分支源插件发现/触发 | 各项目仓 `Jenkinsfile`（编译/仿真，throttle 限 license） |
| **local/mcp** | 开发端·查询 | opencode 接 Jenkins `mcp-server` 插件 |

## 部署（详见 `docs/quick_deploy.md`）

交付模型：**有网机下载 → 介质/手动拷贝 → 服务器本地部署**（无 SSH、无联网下载）。三步：

1. **有网机**：`python3 local/admin/fetch_plugins.py`（curl 下插件+依赖打 tar.gz）+ 手动下 jenkins/java 的 `.deb` → `local/offline/`；走代理填 `config.ini [proxy]`。
2. **送进服务器**（手动）：`tar czf ci-bundle.tar.gz --exclude='*.local.ini' --exclude='__pycache__' ci` → 介质拷到服务器 → `tar xzf ci-bundle.tar.gz -C /opt`（得 `/opt/ci`）。
3. **服务器**（root）：`sudo python3 server/deploy/deploy.py all`（apt 装 .deb + 拷插件 + JCasC + systemd）。

离线件清单、插件机制、放置后验证、平台注意，全在 `docs/quick_deploy.md`。

## 触发构建（自研分支源插件 + 组织文件夹，D-020）

- 内源 git push → **自研分支源插件**发现/触发 → Jenkins 跑该仓 `Jenkinsfile`。
- **加项目** = 仓里放 `Jenkinsfile`（模板 `docs/Jenkinsfile.example`）→ 插件自动发现建 job，**零重启**。
- 流水线（编译 A/B/C + 仿真按 throttle 限 license）写在各仓 Jenkinsfile；license 池在中央 `jenkins.yaml` 定义。
- 插件 id 填进 `plugins.txt`、组织文件夹的 navigator 配在 `jenkins.yaml`（见占位注释）。

## 查状态 / 拉日志（MCP，接 opencode）

Jenkins 装官方 `mcp-server` 插件后自带 MCP 端点（job/build 工具），无需自写。**服务端搭建 + API token 生成 +
opencode 接入见 `local/mcp/README.md`**（端点 `/mcp-server/mcp`，Basic 认证）。构建列表/日志也可直接看 Jenkins UI。

## qsort 评测 demo（本机可验，无需 Jenkins）
```bash
python3 server/demo/qsort/eval.py server/demo/qsort   # 编译 → 功能用例比对 + 性能耗时，期望全过
```
被测仓的 `Jenkinsfile` 评测 stage 即 `python3 .../limited_run.py . python3 eval.py .`（模板见 `docs/Jenkinsfile.example`）。

## SDD 文档层级

| 层 | 文件 | 回答 |
|----|------|------|
| 宪法 | `docs/00_constitution.md` | 不可违反的原则（C-1~C-10） |
| 规格 | `docs/01_spec.md` | 是什么/为什么 + 需求(FR/NFR) + 决策记录(D-001~D-020) |
| 设计 | `docs/05_jenkins_design.md` | Jenkins 路线设计与实现阶段 |

## 关键设计

- **CI 框架 Jenkins**（D-016）：标准特性开箱（pipeline-as-code、auto-cancel、Web UI、官方 MCP 插件）；
  .deb + apt 离线安装（jenkins/java 的 .deb；插件全离线 .hpi 拷入默认路径；JCasC 配置即代码 D-018）。
- **触发=自研分支源插件 + 组织文件夹**（D-020）：插件扫内源 git 自动发现带 Jenkinsfile 的仓→建 job/触发；加项目零重启（不自建 webhook 适配器）。
- **仿真按 license 限并发**（D-003）：每仿真器一个 throttle 类别（限其 license 数）→ 同仿真器串行、不同仿真器并行；`numExecutors`=总并行（可配 `[jenkins] executors`）。
- **凭证不入仓**（C-1）：Jenkins admin 密码 / 下载代理密码经 env 或 `config.local.ini`。
- **纯 python3 标准库**：部署/取包/打包脚本无第三方依赖（下载靠系统 curl）；Jenkins 本体离线传入。
