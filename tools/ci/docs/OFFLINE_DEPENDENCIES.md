# 离线依赖清单（OFFLINE_DEPENDENCIES）

> implements: FR-9, FR-17
> CI 框架=Jenkins（.deb + apt 离线安装）。内网无外网、**内网 Update Center 也装不了插件**，故
> jenkins/java 的 `.deb` 与**全部插件（含依赖）**都须提前在有网环境下载好，放到 `tools/ci/local/offline/`
>（随代码 bootstrap 推到服务器 `[offline] deps_dir`）。`deploy.py` apt 装 `.deb` + 把插件 `.jpi` 拷进
> Jenkins 默认插件路径 `/var/lib/jenkins/plugins`。

## 一键产出（有网机，推荐）

```bash
# 1) 改 config.ini [fetch] 版本/URL 为内网可下的版本（装错版本是硬故障，务必核对）：
#    jenkins_version / jenkins_deb / jenkins_deb_url / java_deb / java_deb_url
# 2) 走代理：export HTTPS_PROXY=http://user:pass@proxy:8080（明文密码不入仓 C-1）
python3 local/admin/fetch_offline.py     # 下 jenkins/java 的 .deb → tools/ci/local/offline/
python3 local/admin/fetch_plugins.py     # 据 plugins.txt 从公网下全部插件 + 全部依赖 → local/offline/plugins/
```

产出内容（`tools/ci/local/offline/`，大文件已 `.gitignore`）：

| 内容 | 来源 | 说明 |
|------|------|------|
| `jenkins_2.555.1_all.deb` | pkg.jenkins.io/debian-stable | Jenkins LTS Debian 包（含 war + jenkins.service） |
| `openjdk-21-jre-headless.deb`（或等价） | 发行版 / 内网镜像 / Temurin | **Java 21**（Jenkins 2.555.x 要求 Java 21+，已不支持 17） |
| `plugins/*.jpi` | 公网 Update Center（plugin-cli） | **全部插件 + 全部依赖**（递归解依赖，不漏） |

## 插件（全部离线，公网下）

内网 Update Center 装不了插件，故全部插件离线传。`local/admin/fetch_plugins.py` 在**有网机**（可达公网
插件库）用 `jenkins-plugin-manager`（plugin-cli）按 `server/deploy/plugins.txt` 下插件：

- plugin-cli **递归解析整棵依赖树**（依赖的依赖…全下），手动下 `.jpi` 才会漏依赖；
- 清单 `server/deploy/plugins.txt`：`git`/`workflow-aggregator`/`configuration-as-code`/`job-dsl`/`throttle-concurrents`/`mcp-server`；
- 也可命令行指定：`python3 local/admin/fetch_plugins.py mcp-server git`；
- **公网机是 Windows**：`fetch_plugins.py` 跨平台（纯标准库 + java），装 python3 + java 后 `python local\admin\fetch_plugins.py` 即可；
- 产出 `.jpi` 随 `offline/` 推到服务器，`deploy.py` 拷进 `/var/lib/jenkins/plugins`（jenkins 默认插件路径）。
- 验证下全：Jenkins 启动日志若报 `Failed to load: X (missing dependency Y)` 即缺依赖；不报即闭包完整。

## Java 21（直接装 JDK/JRE）

Jenkins 2.555.x 要 Java 21+。直接装一个 JDK/JRE 21 的 `.deb`，apt 与 Jenkins 一起装上即可：
- `config.ini [fetch] java_deb_url` 填得到下载地址时，`fetch_offline.py` 自动下；
- 来源因发行版/内网镜像而异（`openjdk-21-jre-headless` 等），URL 留空时**手动**把该 `.deb` 放进 `tools/ci/local/offline/`；
- 或服务器已自带 Java 21，则无需此 `.deb`（apt 装 jenkins 时用系统 `/usr/bin/java`）。

## 传入内网与安装

```bash
# 随 bootstrap 推送（执行机上）：offline/ 在代码树内，scp 随代码一起推到 <dest>/local/offline
python3 local/admin/deploy_remote.py push
# 服务器上安装（deploy.py init 自动做）
sudo python3 server/deploy/deploy.py all          # apt 装 .deb + 拷插件 .jpi 进默认路径 + JCasC + systemd
```

## 放置后验证

```bash
ls -l tools/ci/local/offline/                            # 应见 jenkins_*.deb、java 的 .deb
ls -l tools/ci/local/offline/plugins/                    # 应见一批 .jpi（数量 > 列出的插件数 = 依赖已下全）
sudo python3 server/deploy/deploy.py check         # 校验 .deb + 插件 .jpi 就位 + 端口 + root + apt/dpkg
```

## 注意

- **平台 Linux x86_64(amd64)**；`.deb` 与架构匹配。换架构（arm64）须取对应架构的 `.deb`。
- `.deb` 的系统依赖（如 `adduser`/`procps`/`psmisc` 等）一般已装；若 `apt install ./*.deb` 报缺依赖，
  把对应依赖 `.deb` 一并放进 `offline/`（apt 会一起解）。
- 版本随时间更新：下包前到 jenkins.io / 你的内网镜像 核对当前可下版本，改 `config.ini [fetch]`（C-10：不臆造）。
