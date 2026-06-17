# Quick Deploy · Jenkins CI（.deb 离线 + 手动拷贝）

> CI 框架 = Jenkins（.deb apt 安装）。链路：仓库 push → 自研分支源插件发现/触发 → Jenkins 跑该仓
> `Jenkinsfile`（编译/仿真，throttle 限 license）；官方 MCP 插件接 opencode 查结果。
> 代码托管仍用内网现有仓库（不新建）。
>
> 交付模型：**有网机下载 → 介质/手动拷贝 → 服务器本地部署**（无 SSH 推送）。

整条链就三步：**① 有网机下离线件 → ② 拷进内网服务器 → ③ 服务器跑 deploy.py**。

---

## ① 有网机：下离线件（一次性，纯外网即可）

> Windows + Git Bash 即可（有 `curl` + `python3`）。要走代理就填 `config.ini [proxy]`；纯外网留空=直连。
> curl 不读系统代理/PAC，须显式配（含密码的代理放 `config.local.ini [proxy]`，不入仓）。

1. **插件（含全部依赖）** —— curl + 公网 `update-center.json` 解依赖，自动 sha256 校验 + 闭包自检 + 打 tar.gz：

   ```bash
   python3 local/admin/fetch_plugins.py            # 据 plugins.txt 下全部插件+依赖
   python3 local/admin/fetch_plugins.py --dry-run  # 只解依赖、列出闭包(name/version/url)，不下载
   ```

   产出：`tools/ci/local/offline/plugins/*.hpi` + `tools/ci/local/offline/jenkins-plugins.tar.gz`。

2. **Jenkins + Java 的 .deb** —— 用浏览器或 curl 手动下，放进 `tools/ci/local/offline/`（版本见下方「离线件清单」）：

   ```bash
   curl -fLO https://pkg.jenkins.io/debian-stable/binary/jenkins_2.555.1_all.deb
   # Java 21 的 .deb（openjdk-21-jre-headless 等，来源因发行版/内网镜像而异）一并放进 offline/
   ```

   > 下包前到官网核对当前版本（装错版本是硬故障）。Jenkins 2.555.x 要求 Java 21+。

## ② 送进内网服务器

`packship.py` 把整套 `tools/ci`（代码 + `local/offline` 的 .deb/插件）送过去。目标读 `config.ini [ship]`
（`host`/`user`/`port`/`dest`/`ssh_opts`）。

```bash
# 能直连服务器：据 [ship] 打包成 tar.gz 并 scp（dest 默认 /opt → 解包得 /opt/ci）
python3 local/admin/packship.py
# 或不打包，直接传目录（rsync 优先，否则 scp -r；同样排除 config.local.ini 密钥）
python3 local/admin/packship.py --dir
# 临时覆盖目标：
python3 local/admin/packship.py --scp root@10.0.0.5:/opt/ -p 22
```

**不能直连服务器**（下载机与服务器分属两网）：`[ship] host` 留空 → 只打包出 `local/offline/ci-bundle.tar.gz`，
人肉搬介质，服务器上解包：

```bash
tar xzf ci-bundle.tar.gz -C /opt        # 解出 /opt/ci（含代码 + local/offline 的 .deb/plugins）
ls /opt/ci/local/offline/               # 应见 *.deb
ls /opt/ci/local/offline/plugins/       # 应见一批 .hpi（数量 > plugins.txt 行数 = 依赖已下全）
```

> tar.gz 已含 `local/offline/plugins/*.hpi`，无需再单独解 `jenkins-plugins.tar.gz`。

## ③ 服务器：本地部署（需 root）

1. 填配置：
   - `config.ini`：`[jenkins]`（端口/job 名/admin/executors）、`[offline] deps_dir`、`[limits]`。
   - `config.local.ini`（不入仓）：`[secrets] jenkins_admin_password`。
   - `plugins.txt`：填上你的【分支源插件】短名；`jenkins.yaml`：把组织文件夹的 navigator 占位换成该插件配置。
2. 一键部署（check → init → service）：

   ```bash
   sudo python3 server/deploy/deploy.py all
   # 或分步：check（自检）/ init（apt 装 .deb + 拷插件 + 渲染 JCasC）/ service（密钥环境文件 + systemd）
   ```

   `init` 把 `deps_dir/plugins/*.hpi` 拷进 `/var/lib/jenkins/plugins`；`service` 写 systemd drop-in 并起 `jenkins`。

---

## 接入代码仓（自研分支源插件 + 组织文件夹）

不再用独立 webhook 适配器——**触发交给你的分支源插件**（D-020）：

1. `jenkins.yaml` 的 `organizationFolder` 用该插件做 navigator，扫内源 git 的目标组/owner。
2. 内源站把 push webhook 指向**插件在 Jenkins 注册的入口**（具体路径见插件文档；不支持就靠组织文件夹周期扫描兜底）。
3. **加项目** = 仓里放根目录 `Jenkinsfile`（模板 `docs/Jenkinsfile.example`）→ 插件自动发现建 job，**零重启**。

## 触发与查看

```bash
# Jenkins UI：组织文件夹 / 各仓 job / 构建列表 / 控制台日志 / 产物（admin 登录）
http://<服务器IP>:8080/
journalctl -u jenkins -f         # Jenkins 日志（含分支源扫描/触发）
```

## 开发端 MCP（官方 mcp-server 插件，接 opencode）

Jenkins 装 `mcp-server` 插件后自带 MCP 端点（无需自写）。端点：`http://<服务器IP>:8080/mcp-server/mcp`
（Basic `base64(admin:API_TOKEN)`）。搭建 + API token + 接入见 `local/mcp/README.md`。

## 本机可验项（无需真 Jenkins）

```bash
python3 server/demo/qsort/eval.py server/demo/qsort   # qsort 功能+性能评测（被测仓 Jenkinsfile 的评测 stage 即跑它）
```

## 命令速查

| 动作 | 命令 |
|------|------|
| 有网机下插件 + 打 tar.gz | `python3 local/admin/fetch_plugins.py` |
| 只看依赖闭包不下载 | `python3 local/admin/fetch_plugins.py --dry-run` |
| 打包整套送服务器 | `python3 local/admin/packship.py`（或 `--dir` 直传目录） |
| 服务器一键部署 | `sudo python3 server/deploy/deploy.py all` |
| 环境自检 | `sudo python3 server/deploy/deploy.py check` |
| 看服务状态 | `systemctl status jenkins` |

> 端口白名单：80-90 / 443 / 8080-8090（deploy.py check 校验）。

## 离线件清单（有网机产出 → 放 `tools/ci/local/offline/`，大文件已 .gitignore）

| 内容 | 来源 | 说明 |
|------|------|------|
| `jenkins_2.555.1_all.deb` | pkg.jenkins.io/debian-stable | Jenkins LTS Debian 包（含 war + jenkins.service） |
| `openjdk-21-jre-headless.deb`（或等价） | 发行版 / 内网镜像 / Temurin | **Java 21**（2.555.x 要 Java 21+，不支持 17）；服务器已自带 Java 21 则可免 |
| `plugins/*.hpi` | 公网 Update Center（curl） | **全部插件 + 全部依赖**（递归解，不漏） |
| `jenkins-plugins.tar.gz` | 上面 plugins/ 打包 | 搬运用；服务器上 `tar xzf` 解出 `plugins/` |

> 下包前到官网核对当前版本（装错版本是硬故障）；版本更新后同步上面命令/表（C-10：不臆造）。

## 插件离线获取细节（fetch_plugins.py，不用 plugin-cli/java）

- 从公网 `update-center.actual.json` 取依赖图，**纯 Python BFS 解整棵依赖树** → curl 并发下 → 逐个 **sha256 校验** → 读 `.hpi` MANIFEST 做**闭包自检**（缺谁/被谁依赖都列出）→ 打 tar.gz。
- 清单见 `server/deploy/plugins.txt`；命令行也可指定：`python3 local/admin/fetch_plugins.py mcp-server git`。
- 换源：默认 `updates.jenkins.io`；`--uc-url` 或 `--uc-file`（离线塞一份 json）可改。
- 验证下全：静态自检外，Jenkins 启动日志若报 `Failed to load: X (missing dependency Y)` 即缺依赖。

## 放置后验证（服务器）

```bash
ls -l <deps_dir>/            # 应见 jenkins_*.deb、java 的 .deb
ls -l <deps_dir>/plugins/    # 应见一批 .hpi（数量 > plugins.txt 行数 = 依赖已下全）
sudo python3 server/deploy/deploy.py check   # 校验 .deb + 插件就位 + 端口 + root + apt/dpkg
```

## 注意

- **平台 Linux x86_64(amd64)**；`.deb` 与架构匹配（arm64 须取对应架构 .deb）。
- `.deb` 的系统依赖（adduser/procps/psmisc 等）一般已装；若 `apt install ./*.deb` 报缺依赖，把对应依赖
  `.deb` 一并放进 `offline/`（apt 一起解）。**全部满足则部署全程不外联。**

## 卸载 / 重置

```bash
sudo systemctl disable --now jenkins
sudo apt-get remove --purge -y jenkins
sudo rm -f /etc/ci-jenkins.env
sudo rm -rf /etc/systemd/system/jenkins.service.d
sudo systemctl daemon-reload
sudo rm -rf /var/lib/jenkins        # 删 JENKINS_HOME（谨慎，不可恢复）
```
