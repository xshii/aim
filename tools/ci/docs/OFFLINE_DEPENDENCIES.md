# 离线依赖清单（OFFLINE_DEPENDENCIES）

> implements: FR-9, FR-17
> 内网不支持从外网 git clone / 下载。以下依赖须**提前在有网环境下载好**，
> 传入内网放到 `config.ini [offline] deps_dir`（默认 `/opt/ci/offline`）。文件名需与 config 一致。

## 两种获取方式（FR-17）

- **manual**（默认）：在有网环境手动下载（见下），放进 `deps_dir`。
- **auto**：在**执行机**（admin 侧，有外网/经代理）经 `local/admin/deploy_remote.py fetch` 自动下载，
  再随 `push` 推到远端 `deps_dir`。配置：
  - `config.ini [fetch] mode=auto`，并填 `gitlab_url`/`runner_url`/`runner_deps_url`（文件名取 `[offline]`）。
  - 代理（**含明文密码，不入仓**）放 `config.local.ini [proxy]` 的 `http_proxy`/`https_proxy`，
    或等效环境变量 `HTTP_PROXY`/`HTTPS_PROXY`。
  - 下载到 `deps_dir`，已存在则跳过。URL 缺失即停（C-10，不编造）。


## 手动下载清单（v19.0.1，amd64 / Ubuntu jammy）

在**有网环境**下载以下三个文件，放进 `deps_dir`（默认 `/opt/ci/offline`）。
版本/架构须与你的服务器匹配（下面是 19.0.1 / amd64 / Ubuntu 22.04 jammy 示例）。

```bash
cd /opt/ci/offline      # = config.ini [offline] deps_dir

# 1) GitLab CE 本体
wget -O gitlab-ce_19.0.1-ce.0_amd64.deb \
  "https://packages.gitlab.com/gitlab/gitlab-ce/packages/ubuntu/jammy/gitlab-ce_19.0.1-ce.0_amd64.deb/download.deb"

# 2) GitLab Runner 主程序
wget -O gitlab-runner_amd64.deb \
  "https://s3.dualstack.us-east-1.amazonaws.com/gitlab-runner-downloads/v19.0.1/deb/gitlab-runner_amd64.deb"

# 3) GitLab Runner helper-images（Runner 的依赖，离线必需）
wget -O gitlab-runner-helper-images.deb \
  "https://s3.dualstack.us-east-1.amazonaws.com/gitlab-runner-downloads/v19.0.1/deb/gitlab-runner-helper-images.deb"
```

下好后这三个文件名应与 config.ini [offline] 的 gitlab_archive / runner_archive / runner_deps 一致：

| config 项 | 文件名 |
|-----------|--------|
| gitlab_archive | gitlab-ce_19.0.1-ce.0_amd64.deb |
| runner_archive | gitlab-runner_amd64.deb |
| runner_deps | gitlab-runner-helper-images.deb |

> 换版本/系统时：到 packages.gitlab.com（GitLab CE）和 gitlab-runner-downloads（Runner）
> 找对应版本链接，相应改文件名与 config。


## 需要准备的文件

| config 项 | 默认文件名 | 内容 | 从哪获取 |
|-----------|-----------|------|---------|
| gitlab_archive | gitlab-ce.deb | GitLab CE 离线安装包（社区版） | packages.gitlab.com 对应发行版的 .deb |
| runner_archive | gitlab-runner.deb | GitLab Runner 离线安装包 | packages.gitlab.com 的 gitlab-runner .deb |
| runner_deps | gitlab-runner-helper-images.deb | **Runner 依赖包**（新版必需） | 同源，版本须与 runner 一致 |

## 准备步骤（在有网环境做）

1. 下载上述文件，按表中“默认文件名”重命名（或改 config.ini 对应项匹配你的实际文件名）。
2. 如果走 LFS：把这三个文件打成一个压缩包，用 git-lfs 管理，传入内网后解压到 `deps_dir`。

## 放置后验证

```bash
ls -l /opt/ci/offline/
# 应看到 gitlab-ce.deb, gitlab-runner.deb（或你在 config 改的名字）
python3 ci_config.py        # 打印配置，确认 deps_dir 与文件名正确
```

## 注意

- GitLab/Runner 的 .deb 若有未满足的系统依赖，也需一并离线提供对应 .deb。

## 依赖包（重要）

`.deb` 用 `dpkg -i` 装时**不会自动拉依赖**，离线环境必须把依赖包一并下好放进 deps_dir。

### gitlab-runner 的依赖
新版 gitlab-runner（19.x+）拆出了 `gitlab-runner-helper-images`，离线安装必须一并提供，
否则报：`gitlab-runner depends on gitlab-runner-helper-images; however ... not installed`。

查依赖与下载（在有网的同款系统上）：
```bash
apt-cache depends gitlab-runner                       # 看依赖列表
apt-get download gitlab-runner-helper-images          # 下载依赖包（版本须与 runner 一致）
```
把下到的 `gitlab-runner-helper-images_<版本>_all.deb` 放进 deps_dir，
并在 config.ini [offline] runner_deps 里填它的文件名（多个用逗号分隔）。

`ca-certificates / git / curl / tar` 一般系统已自带；若缺，也需一并离线提供。

### 安装方式
setup_runner.py / install_gitlab.py 会优先用 `apt-get install ./*.deb`（自动解析本地包依赖），
失败再回退 `dpkg -i 多包`。所以只要依赖包都在 deps_dir 且在 config 列出，即可一次装好。
