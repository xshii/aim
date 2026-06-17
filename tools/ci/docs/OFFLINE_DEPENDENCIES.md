# 离线依赖清单（OFFLINE_DEPENDENCIES）

> implements: FR-9, FR-17
> CI 框架=Jenkins（D-016）。内网无外网。Jenkins 离线部署所需的 WAR + 插件 + JDK 须**提前在有网
> 环境下载好**，打成一个 `jenkins-offline.tar.gz`，传入内网放到 `config.ini [offline] deps_dir`
> （默认 `/opt/ci/offline`），由 `server/deploy/deploy.py` 解包部署。

## 一键产出（推荐）

有网机器上跑 `server/deploy/fetch_offline.py`，自动下 WAR + JDK21 + 插件（含依赖）并打包：

```bash
# 1) 改 fetch_offline.py 顶部四个版本变量为当前 LTS / 当前发行版（装错版本是硬故障，务必核对）
#    JENKINS_VERSION / JDK_TAG / JDK_FILE / PM_VERSION
# 2) 下载（走代理：export HTTPS_PROXY=http://user:pass@proxy:8080，明文密码不入仓 C-1）
python3 server/deploy/fetch_offline.py            # 产出 ./offline-build/jenkins-offline.tar.gz
```

产出的 `jenkins-offline.tar.gz` 内含：

| 内容 | 来源 | 说明 |
|------|------|------|
| `jenkins.war` | get.jenkins.io/war-stable/<ver>/ | Jenkins LTS 本体（~80MB） |
| `plugins/*.jpi` | plugin-installation-manager-tool 据 `plugins.txt` 下 | 插件 + 依赖（工具自动解析） |
| `jdk/` | Adoptium Temurin JDK 21（linux x64） | 自包含 JDK21（Jenkins 2.555.x 要求 Java 21+），免依赖服务器已装 java |

总量约 ~350MB。慢网下载约数分钟到数小时，一次性。

## 插件清单

`server/deploy/plugins.txt`（一行一个插件短名，依赖自动解析）：
`git`、`workflow-aggregator`(pipeline)、`configuration-as-code`(JCasC)、`job-dsl`(JCasC 建 job)、
`throttle-concurrents`(多节点串行)、`mcp-server`(官方 MCP)。增删插件改它，重跑 fetch_offline.py。

## 传入内网与放置

```bash
# 方式 a：手动拷贝
scp offline-build/jenkins-offline.tar.gz <server>:/opt/ci/offline/   # = [offline] deps_dir

# 方式 b：随 bootstrap 推送（执行机上）
#   先把 jenkins-offline.tar.gz 放到本地 [offline] deps_dir，再：
python3 local/admin/deploy_remote.py push        # 推代码 + 离线包到远端
```

## 放置后验证

```bash
ls -l /opt/ci/offline/jenkins-offline.tar.gz
sudo python3 server/deploy/deploy.py check        # 校验离线包就位 + 端口 + root
```

## 注意

- **平台固定 Linux x86_64(amd64) + JDK21**（Jenkins 2.555.x 要求 Java 21+，已不支持 Java 17）。换架构（arm64）须改 fetch_offline.py 的 JDK 下载 URL。
- 服务器已装 JDK21+ 时，可在 `config.ini [jenkins] java_home` 指向它，离线包仍需 WAR + 插件。
- 版本随时间更新：下包前到 jenkins.io / adoptium.net / plugin-installation-manager-tool releases
  核对当前版本，改 fetch_offline.py 顶部变量（C-10：不臆造版本号）。
