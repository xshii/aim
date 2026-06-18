# Quick Deploy · Jenkins CI（.deb 离线 + 手动拷贝）

> 链路：仓库 push → 自研分支源插件发现/触发 → Jenkins 跑该仓 `Jenkinsfile`（编译/仿真，throttle 限 license）。
> 交付：**有网机下载 → 介质手动拷贝 → 服务器本地部署**（不可 SSH，全程手动）。

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

## ③ 服务器：部署（需 root）

先填配置（见下「填什么」），再一键部署：

```bash
sudo python3 server/deploy/deploy.py all   # check → init(apt 装 .deb + 拷插件 + 渲染 JCasC) → service(systemd 起服务)
# 分步：deploy.py check / init / service
```

## 填什么（配置一览）

**必改只有 3 项**（管理员密码 + 分支源插件 id + 它的 navigator）；其余有默认值，接受即可不填。

| 配置项 | 文件 · 位置 | 默认 | 必改 | 说明 |
|---|---|---|:--:|---|
| `http_port` | `config.ini [jenkins]` | `8080` | 否 | 端口；仅限 80-90 / 443 / 8080-8090 |
| `job_name` | `config.ini [jenkins]` | `benchmark-ci` | 否 | 组织文件夹顶层名 |
| `executors` | `config.ini [jenkins]` | `4` | 按需 | 总并行构建数 |
| `admin_user` | `config.ini [jenkins]` | `admin` | 否 | 管理员用户名 |
| `deps_dir` | `config.ini [offline]` | `/opt/ci/local/offline` | 否 | 离线件落地目录 |
| `mem_mb`/`cpu_sec`/`wall_sec`/`nofile` | `config.ini [limits]` | `2048`/`60`/`120`/`256` | 按需 | 评测沙箱资源上限 |
| `jenkins_admin_password` | `config.local.ini [secrets]`（**不入仓**） | `change-me` | **是** | admin 密码；等效 env `JENKINS_ADMIN_PASSWORD` |
| `http_proxy`/`https_proxy` | `config.local.ini [proxy]`（有网机） | 空 | 视情况 | 下载走代理才填 |
| 分支源插件短名 | `server/deploy/plugins.txt` 末行 | 占位 | **是** | 换成你自研分支源插件短名（D-020） |
| 组织文件夹 navigator | `server/deploy/jenkins.yaml` 的 `organizations{}` | 空占位 | **是** | 你插件的 SCMNavigator DSL（仓库组/owner + 凭证 id） |

> `jenkins.yaml` 的 `@@占位@@` 由 `deploy.py` 自动用 `config.ini` 的值填好，不用手改。

## 接入代码仓（分支源插件 + 组织文件夹，D-020）

- `jenkins.yaml` 的 `organizationFolder` 用你的分支源插件做 navigator，扫内源 git 目标组/owner。
- **加项目** = 仓里放根 `Jenkinsfile`（模板 `docs/Jenkinsfile.example`）→ 插件自动发现建 job，**零重启**。
- 查看 `http://<服务器IP>:8080/`（admin 登录）；MCP 接 opencode 见 `local/mcp/README.md`。

## 命令速查（左=脚本懒人封装，右=等价原始命令，记不住对照右列）

**有网机**

| 动作 | 命令 |
|---|---|
| 下插件 + 全部依赖 | `python3 local/admin/fetch_plugins.py`（`--dry-run` 只列不下载） |
| 打包整套 | `tar czf ci-bundle.tar.gz --exclude='*.local.ini' --exclude='__pycache__' ci` |

**服务器 · 部署（需 root）**

| 动作 | 脚本/快捷 | 等价原始命令 |
|---|---|---|
| 解包 | — | `tar xzf ci-bundle.tar.gz -C /opt`（得 `/opt/ci`） |
| 装离线 .deb | `sudo bash server/deploy/install.sh` | `sudo apt-get install -y <deps_dir>/*.deb` |
| 一键部署 | `sudo python3 server/deploy/deploy.py all` | check→init→service 三步 |
| 自检 | `sudo python3 server/deploy/deploy.py check` | — |

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
> - `install.sh`：只装离线 `.deb`（apt 本地装、自动解依赖）；插件 / JCasC / systemd 用 `deploy.py` 或手动。
> - `restart_jenkins.sh`：`systemctl restart jenkins` + 看状态；带 `reload` 参数先 `daemon-reload`（改过 systemd drop-in 才需）。
> - `showlog.sh`：封住 `journalctl` / `systemctl` 常用参数，默认看最近 100 行，可跟 `follow`/`status`/`today`/`error`/`<行数>`。
>
> `deploy.py all` 是完整安装（含插件/JCasC/systemd）；`install.sh` 只是其中"装 .deb"那一步的快捷。

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
sudo rm -rf /etc/ci-jenkins.env /etc/systemd/system/jenkins.service.d && sudo systemctl daemon-reload
sudo rm -rf /var/lib/jenkins        # 删 JENKINS_HOME（谨慎，不可恢复）
```
