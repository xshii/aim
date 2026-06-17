# 离线依赖清单（OFFLINE_DEPENDENCIES）

> implements: FR-9, FR-17
> CI 框架=Jenkins（.deb + apt 离线安装）。内网无外网。所需 `.deb` 与插件须**提前在有网环境下载好**，
> 放到 `tools/ci/offline/`（随代码 bootstrap 推到服务器 `[offline] deps_dir`），由 `deploy.py` 用 apt 安装。

## 一键产出（推荐）

有网机器上跑 `server/deploy/fetch_offline.py`，按 `config.ini [fetch]` 的版本/URL 下载并产出到 `tools/ci/offline/`：

```bash
# 1) 改 config.ini [fetch] 的版本/URL 为内网可下的版本（装错版本是硬故障，务必核对）
#    jenkins_version / jenkins_deb_url / plugin_manager_url / java_deb_url
# 2) 下载（走代理：export HTTPS_PROXY=http://user:pass@proxy:8080，明文密码不入仓 C-1）
python3 server/deploy/fetch_offline.py            # 产出到 tools/ci/offline/
```

> 需有网机本机有 `java`（跑 plugin-manager 解插件依赖）。

产出内容（`tools/ci/offline/`，大文件已 `.gitignore`）：

| 内容 | 来源 | 说明 |
|------|------|------|
| `jenkins_2.555.1_all.deb` | pkg.jenkins.io/debian-stable | Jenkins LTS Debian 包（含 war + jenkins.service） |
| `plugins/*.jpi` | plugin-installation-manager-tool 据 `plugins.txt` 下 | 插件 + 依赖（自动解析） |
| `openjdk-21-jre-headless.deb`（或等价） | 发行版 / 内网镜像 / Temurin | **Java 21**（Jenkins 2.555.x 要求 Java 21+，已不支持 17） |

## Java 21（直接装 JDK/JRE）

Jenkins 2.555.x 要 Java 21+。直接装一个 JDK/JRE 21 的 `.deb`，apt 与 Jenkins 一起装上即可：
- `config.ini [fetch] java_deb_url` 填得到下载地址时，`fetch_offline.py` 自动下；
- 来源因发行版/内网镜像而异（`openjdk-21-jre-headless` 等），URL 留空时**手动**把该 `.deb` 放进 `tools/ci/offline/`；
- 或服务器已自带 Java 21，则无需此 `.deb`（apt 装 jenkins 时用系统 `/usr/bin/java`）。

## 传入内网与安装

```bash
# 随 bootstrap 推送（执行机上）：offline/ 在代码树内，scp 随代码一起推到 <dest>/offline
python3 local/admin/deploy_remote.py push
# 服务器上 apt 安装（deploy.py init 自动做）
sudo python3 server/deploy/deploy.py all          # apt install ./offline/*.deb + 放插件 + JCasC + systemd
```

## 放置后验证

```bash
ls -l tools/ci/offline/                            # 应见 jenkins_*.deb、plugins/、java 的 .deb
sudo python3 server/deploy/deploy.py check         # 校验 .deb 就位 + 端口 + root + apt/dpkg
```

## 注意

- **平台 Linux x86_64(amd64)**；`.deb` 与架构匹配。换架构（arm64）须取对应架构的 `.deb`。
- `.deb` 的系统依赖（如 `adduser`/`procps`/`psmisc` 等）一般已装；若 `apt install ./*.deb` 报缺依赖，
  把对应依赖 `.deb` 一并放进 `offline/`（apt 会一起解）。
- 版本随时间更新：下包前到 jenkins.io / 你的内网镜像 核对当前可下版本，改 `config.ini [fetch]`（C-10：不臆造）。
