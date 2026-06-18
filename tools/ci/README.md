# tools/ci — CI 系统（Spec-Driven，精简版）

AI 代码生成 Benchmark 评测仓库的 CI 系统。**CI 验证预生成的成品代码**（不在内部生成代码），
做多种验证（功能/性能/比对/质量检查）并收集 output 与状态。**CI 框架=Jenkins（D-016，离线部署）**；
代码托管用内网现有仓库（不新建）。脚本纯 python3（3.8 标准库、零依赖），依赖离线传入。

> 链路：仓库 push → 自研分支源插件发现/触发 → Jenkins 跑该仓 `Jenkinsfile`（编译/仿真，throttle 限 license）。
> 交付：**有网机下载 → 介质手动拷贝 → 服务器本地装**（不可 SSH，全程手动；装 .deb + 拷插件 + 渲染 JCasC 各一步）。

## 执行角色（目录即角色）

```
tools/ci/
├── ci_config.py  config.ini  config.local.ini.example   ← 共享层（角色中立）
├── docs/  README.md
├── server/                 ← 在 CI 服务器上执行
│   ├── deploy/   install.sh(装deb) / gen_jenkins_yaml.py(渲染JCasC) / restart_jenkins.sh / showlog.sh / plugins.txt / jenkins.yaml(JCasC模板)
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
| **server/deploy** | 服务器·部署时（需 root，离线件手动拷到位后） | `install.sh` 装 .deb + 手动拷插件 + `gen_jenkins_yaml.py` 渲染 yaml |
| **server·运行时** | git push → 分支源插件发现/触发 | 各项目仓 `Jenkinsfile`（编译/仿真，throttle 限 license） |
| **local/mcp** | 开发端·查询 | opencode 接 Jenkins `mcp-server` 插件 |

---

# 部署（三步：有网机下载 → 介质拷贝 → 服务器本地装）

## ① 有网机：下离线件（一次性，纯外网；走代理填 `config.ini [proxy]`）

```bash
# 插件 + 全部依赖（curl 下，自动 sha256 校验 + 闭包自检）→ 产出 local/offline/plugins/*.hpi
python3 local/admin/fetch_plugins.py            # 加 --dry-run 只列依赖闭包不下载
# Jenkins + Java 21 的 .deb 手动下，放进 local/offline/（版本见下「离线件清单」，装错版本是硬故障）
curl -fLO https://pkg.jenkins.io/debian-stable/binary/jenkins_2.555.1_all.deb
```

## ② 送进服务器（手动打包 + 介质拷贝）

```bash
# 有网机（在 tools/ 下）：打包整个 ci/，排除密钥与缓存
tar czf ci-bundle.tar.gz --exclude='*.local.ini' --exclude='__pycache__' ci
# 服务器：解包到 /opt（得 /opt/ci）
tar xzf ci-bundle.tar.gz -C /opt
```

> 密钥不上服务器（C-1）：`config.local.ini` 已被 `--exclude` 排除，到服务器后本地新建再填密码。

## ③ 服务器：装（手动，需 root；先填配置见下「填什么」）

```bash
# 1) 装 Jenkins/Java 的离线 .deb（apt 本地装、自动解依赖）
sudo bash server/deploy/install.sh

# 2) 手动拷离线插件进 Jenkins 默认插件路径（内网 Update Center 装不了，故全离线）
sudo cp /opt/ci/local/offline/plugins/*.hpi /var/lib/jenkins/plugins/
sudo chown -R jenkins:jenkins /var/lib/jenkins/plugins

# 3) 渲染 JCasC：填好 config.ini 占位 → server/deploy/jenkins.rendered.yaml（必填项缺即停）
python3 server/deploy/gen_jenkins_yaml.py

# 4) 加载 JCasC + 起服务，二选一：
#    a) 落到默认路径 + 重启（重启也自动加载）
sudo cp server/deploy/jenkins.rendered.yaml /var/lib/jenkins/jenkins.yaml
sudo chown jenkins:jenkins /var/lib/jenkins/jenkins.yaml
# 给 jenkins.service 设 Environment=CASC_JENKINS_CONFIG=/var/lib/jenkins/jenkins.yaml（drop-in），再：
sudo bash server/deploy/restart_jenkins.sh reload
#    b) 不重启：UI 热加载（见下「改配置不重启」）
```

## 填什么（配置一览）

`gen_jenkins_yaml.py` 渲染时**必填**（缺失/留空即停）：`[jenkins]` 的 4 项 + `[secrets]` 密码；另加分支源插件 id 与
navigator。有默认值的接受默认即可，但**不能留空**。

| 配置项 | 文件 · 位置 | 默认 | 必填 | 说明 |
|---|---|---|:--:|---|
| `http_port` | `config.ini [jenkins]` | `8080` | **是** | 端口；仅限 80-90 / 443 / 8080-8090（gen 校验白名单） |
| `job_name` | `config.ini [jenkins]` | `benchmark-ci` | **是** | 组织文件夹顶层名 |
| `executors` | `config.ini [jenkins]` | `4` | **是** | 总并行构建数 |
| `admin_user` | `config.ini [jenkins]` | `admin` | **是** | 管理员用户名 |
| `jenkins_admin_password` | `config.local.ini [secrets]`（**不入仓**） | `change-me` | **是** | admin 密码；等效 env `JENKINS_ADMIN_PASSWORD`（gen 只校验存在） |
| 分支源插件短名 | `server/deploy/plugins.txt` 末行 | 占位 | **是** | 换成你自研分支源插件短名（D-020） |
| 组织文件夹 navigator | `server/deploy/jenkins.yaml` 的 `organizations{}` | 空占位 | **是** | 你插件的 SCMNavigator DSL（仓库组/owner + 凭证 id） |
| `deps_dir` | `config.ini [offline]` | `/opt/ci/local/offline` | 否 | 离线件落地目录（install/拷插件用） |
| `mem_mb`/`cpu_sec`/`wall_sec`/`nofile` | `config.ini [limits]` | `2048`/`60`/`120`/`256` | 否 | 评测沙箱资源上限 |
| `http_proxy`/`https_proxy` | `config.local.ini [proxy]`（有网机） | 空 | 视情况 | 下载走代理才填 |

> `jenkins.yaml`（原始模板在 `server/deploy/jenkins.yaml`）的 `@@占位@@` 由 `gen_jenkins_yaml.py` 用 `config.ini`
> 的值填好、产出 `server/deploy/jenkins.rendered.yaml`，**不用手改**。它是一次性配置：加项目不动它（放
> `Jenkinsfile` 即可，D-020）；只有初次填 navigator、或 throttle 坑位用完时才手动改。

## 改配置不重启（UI 加载 JCasC）

改了配置（重跑 `gen_jenkins_yaml.py`）又不想重启 Jenkins，用 JCasC 插件网页热加载（需 `configuration-as-code` 插件，已在 `plugins.txt`）：

1. 把 `jenkins.rendered.yaml` 拷到服务器某路径（如 `/var/lib/jenkins/jenkins.yaml`）。
2. `Manage Jenkins → Configuration as Code`（直达 `http://<服务器IP>:8080/configuration-as-code/`）。
3. 「Path or URL」填该路径 → 点 **Apply new configuration**，当场生效、**不重启不碰 systemd**。

> ⚠ yaml 里 admin 密码是 `${JENKINS_ADMIN_PASSWORD}`，UI 加载时若该 env 不在会报"变量未解析"——
> 要么删掉 `securityRealm:` / `authorizationStrategy:` 两段（沿用现有账号），要么临时填真实密码。

## 接入代码仓（自研分支源插件 + 组织文件夹，D-020）

不用独立 webhook 适配器——触发交给你的分支源插件：

- `jenkins.yaml` 的 `organizationFolder` 用该插件做 navigator，扫内源 git 的目标组/owner（凭证 id 见 `plugins.txt`/插件文档）。
- 内源站把 push webhook 指向**插件在 Jenkins 注册的入口**（路径见插件文档；不支持就靠组织文件夹周期扫描兜底）。
- **加项目** = 仓里放根 `Jenkinsfile`（模板 `docs/Jenkinsfile.example`）→ 插件自动发现建 job，**零重启**。
- 流水线（编译 A/B/C + 仿真按 throttle 限 license）写在各仓 Jenkinsfile；license 池（c1/c2/c3 类别）在中央 `jenkins.yaml` 定义。

## 命令速查（左=脚本懒人封装，右=等价原始命令，记不住对照右列）

**有网机**

| 动作 | 命令 |
|---|---|
| 下插件 + 全部依赖 | `python3 local/admin/fetch_plugins.py`（`--dry-run` 只列不下载） |
| 打包整套 | `tar czf ci-bundle.tar.gz --exclude='*.local.ini' --exclude='__pycache__' ci` |

**服务器 · 装（需 root）**

| 动作 | 脚本/快捷 | 等价原始命令 |
|---|---|---|
| 解包 | — | `tar xzf ci-bundle.tar.gz -C /opt`（得 `/opt/ci`） |
| 装离线 .deb | `sudo bash server/deploy/install.sh` | `sudo apt-get install -y <deps_dir>/*.deb` |
| 拷插件 | — | `sudo cp <deps_dir>/plugins/*.hpi /var/lib/jenkins/plugins/` |
| 渲染 JCasC | `python3 server/deploy/gen_jenkins_yaml.py` | 填 config.ini 占位 → `jenkins.rendered.yaml` |
| 加载 JCasC | — | 拷到 `/var/lib/jenkins/jenkins.yaml` 重启，或 UI Apply |

**服务器 · 运维**

| 动作 | 脚本/快捷 | 等价原始命令 |
|---|---|---|
| 重启 | `sudo bash server/deploy/restart_jenkins.sh` | `sudo systemctl restart jenkins` |
| 改 drop-in 后重启 | `sudo bash server/deploy/restart_jenkins.sh reload` | `sudo systemctl daemon-reload && sudo systemctl restart jenkins` |
| 启 / 停 / 开机自启 | — | `sudo systemctl start \| stop \| enable jenkins` |
| 服务状态 | `bash server/deploy/showlog.sh status` | `systemctl status jenkins` |
| 实时日志 | `bash server/deploy/showlog.sh follow` | `journalctl -u jenkins -f` |
| 最近 N 行 | `bash server/deploy/showlog.sh 200` | `journalctl -u jenkins -n 200 --no-pager` |
| 今天日志 | `bash server/deploy/showlog.sh today` | `journalctl -u jenkins --since today` |
| 只看报错 | `bash server/deploy/showlog.sh error` | `journalctl -u jenkins \| grep -iE 'WARNING\|SEVERE\|error'` |
| 打开 UI | — | 浏览器开 `http://<服务器IP>:8080/`（admin 登录） |

> **脚本说明**（都在 `server/deploy/`，各管一件，能手动就手动）：
> - `install.sh`：只装离线 `.deb`（apt 本地装、自动解依赖）。
> - `gen_jenkins_yaml.py`：把 `config.ini` 填进 JCasC 模板 → `jenkins.rendered.yaml`；4 个 `[jenkins]` 字段 + 密码**必填**，缺即停。
> - `restart_jenkins.sh`：`systemctl restart jenkins` + 看状态；带 `reload` 参数先 `daemon-reload`（改过 systemd drop-in 才需）。
> - `showlog.sh`：封住 `journalctl` / `systemctl` 常用参数，默认看最近 100 行，可跟 `follow`/`status`/`today`/`error`/`<行数>`。

## 离线件清单（放 `local/offline/`，大文件已 .gitignore）

| 内容 | 来源 | 说明 |
|------|------|------|
| `jenkins_2.555.1_all.deb` | pkg.jenkins.io/debian-stable | Jenkins LTS（含 war + jenkins.service） |
| `openjdk-21-*.deb`（或等价） | 发行版 / 内网镜像 / Temurin | **Java 21**（2.555.x 要 21+）；服务器已自带可免 |
| `plugins/*.hpi` | 公网 Update Center（curl） | 全部插件 + 全部依赖（递归解，不漏） |

> 下包前到官网核对当前版本（装错是硬故障，C-10）。平台 Linux amd64，`.deb` 须架构匹配。
> 若 `apt install ./*.deb` 报缺系统依赖，把对应依赖 `.deb` 一并放进 `offline/`（apt 一起解）。

## 卸载 / 重置

```bash
sudo systemctl disable --now jenkins
sudo apt-get remove --purge -y jenkins
sudo rm -rf /etc/systemd/system/jenkins.service.d && sudo systemctl daemon-reload
sudo rm -rf /var/lib/jenkins        # 删 JENKINS_HOME（谨慎，不可恢复）
```

---

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

部署/运维操作全在本 README（原 `docs/quick_deploy.md` 已并入此处）。

## 关键设计

- **CI 框架 Jenkins**（D-016）：标准特性开箱（pipeline-as-code、auto-cancel、Web UI、官方 MCP 插件）；
  .deb + apt 离线安装（jenkins/java 的 .deb；插件全离线 .hpi 拷入默认路径；JCasC 配置即代码 D-018）。
- **触发=自研分支源插件 + 组织文件夹**（D-020）：插件扫内源 git 自动发现带 Jenkinsfile 的仓→建 job/触发；加项目零重启（不自建 webhook 适配器）。
- **仿真按 license 限并发**（D-003）：每仿真器一个 throttle 类别（限其 license 数）→ 同仿真器串行、不同仿真器并行；`numExecutors`=总并行（可配 `[jenkins] executors`）。
- **凭证不入仓**（C-1）：Jenkins admin 密码 / 下载代理密码经 env 或 `config.local.ini`。
- **纯 python3 标准库**：部署/取包/打包脚本无第三方依赖（下载靠系统 curl）；Jenkins 本体离线传入。
