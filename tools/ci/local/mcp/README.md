# 开发端 MCP（Jenkins 官方 mcp-server 插件）

> CI 框架=Jenkins（D-016）。MCP 由 Jenkins 官方 `mcp-server` 插件提供，**无自写代码**。
> 插件暴露 job/build 为 MCP 工具，供 opencode 等客户端查构建状态 / 拉日志。

## 服务端（几乎不用配，开箱即用）

1. **装插件**：`mcp-server` 已列在 `server/deploy/plugins.txt`，`deploy.py` 会从内源 Update Center 装上。
   无需 JCasC、无需额外配置——装上即自动暴露端点。
2. **生成 API token**：部署后在 Jenkins UI → 头像（右上）→ Security → API Token → 生成，命名（如 `opencode-mcp`），
   **复制一次存好**（只显示一次）。MCP 认证用它，不用密码。

自动暴露的 HTTP 端点（`<host>:<jenkins http_port>` 下）：

| 端点 | 用途 |
|------|------|
| `/mcp-server/mcp` | Streamable HTTP（**opencode 用这个**） |
| `/mcp-server/sse` | SSE 长连接 |
| `/mcp-server/stateless` | 无状态调用 |
| `/mcp-health` / `/mcp-server/metrics` | 健康检查 / 指标 |

**认证**：用 Jenkins 同一套凭证——HTTP Basic，头 `Authorization: Basic <base64(用户名:API_TOKEN)>`。

**（可选）生产调优**：Jenkins 启动加 `--httpKeepAliveTimeout=600000`（SSE 长连接更稳）。
要加就改 `server/deploy/systemd/jenkins-override.conf` 的 `ExecStart`，在 `--httpPort=...` 后追加该参数，
重跑 `deploy.py service`。不加也能用（仅影响 SSE 长连接稳定性）。

## 客户端（opencode）

见同目录 `opencode.json.example`：连 `http://<host>:<jenkins http_port>/mcp-server/mcp`，
带 `Authorization: Basic <base64(admin:API_TOKEN)>`。`admin` = `config.ini [jenkins] admin_user`。

```bash
# 生成 Basic 头的 base64（admin + 上面复制的 API token）
printf 'admin:<API_TOKEN>' | base64
```

## 与触发的分工

- **触发构建** → webhook 适配器（`server/webhook/`，X-Devcloud-Token → buildWithParameters）。
- **查状态 / 拉日志** → 本 MCP（mcp-server 插件）。两者独立。

> 参考：https://plugins.jenkins.io/mcp-server/
