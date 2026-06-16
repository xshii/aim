# Webhook 触发构建

> implements: FR-14, FR-19
> 触发方式：webhook（HTTP）。GitLab 直接 HTTP 可达（本机/内网），webhook 与 token
> 触发均可正常工作。无需 ssh、无需隧道。
> 内源代码托管站经独立接收器 `receiver.py`（X-Auth 共享密钥）接入，见「方式三」。

## 方式一：git push 自动触发（最常用）

`git push` → GitLab 按 `.gitlab-ci.yml` 自动触发流水线。无需额外操作。

## 方式二：webhook / API 主动触发

GitLab 直接 HTTP 可达，外部网页/系统可直接发 HTTP 触发：

### Pipeline Trigger Token（推荐）
GitLab 项目 → Settings → CI/CD → Pipeline trigger tokens → 创建 token。
```bash
curl -X POST \
  -F token=<TRIGGER_TOKEN> \
  -F ref=main \
  http://<host>:<port>/api/v4/projects/<project_id>/trigger/pipeline
```
- `<host>:<port>` = config.ini 的 server.host + 探测锁定的 gitlab.http_port
- token 权限仅触发、可吊销轮换

### 配在网页/外部系统的 webhook
把上面的 URL + token 配进网页的 webhook 动作即可，点一下就触发。
GitLab 也支持入站 webhook（project hooks）用于更复杂的事件联动。

## 方式三：内源代码托管站 webhook（X-Auth，FR-19）

内部代码托管站经入站 webhook 触发评测，但其自定义鉴权头 GitLab 不直接认。用独立接收器
`receiver.py`（role=server/webhook，与 GitLab 同机）：校验请求头共享密钥 → 用 GitLab trigger
token 触发流水线。

```bash
# 1) 配 config.ini [webhook]：enabled=true、listen、auth_header（默认 X-Auth-Token）、project_id、ref
# 2) 配密钥（不入仓）：env 或 config.local.ini [secrets]
export WEBHOOK_SECRET=<与内源站一致的共享密钥>
export GITLAB_TRIGGER_TOKEN=<GitLab 项目 trigger token>
# 3) 启接收器（与 GitLab 同机）
python3 server/webhook/receiver.py
# 4) 在内源站把 webhook 指向 http://<本机>:9100/，请求头带 X-Auth-Token: <共享密钥>
```

- 校验用 `hmac.compare_digest` 常量时间比较，防时序侧信道。
- 密钥/ token **不入仓**：环境变量优先，其次 `config.local.ini [secrets]`（gitignore）。
- 接收器只校验+转发，不解析 body（共享密钥模式）。

## 与 MCP 的分工

- **触发构建** → webhook / token / 内源 X-Auth 接收器（本文）
- **查状态 / 拉错误日志** → MCP `ci_control_server`（开发端用，接 opencode，见 `local/mcp/`）

## 地址说明

GitLab 地址 = `http://<server.host>:<gitlab.http_port>`。端口由 `probe_port.py`
从候选中探测一个空闲端口锁定（因服务器部分端口被其他 CI 服务占用）。
