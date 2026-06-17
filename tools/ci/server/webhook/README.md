# Webhook 适配器（→ Jenkins）

> implements: FR-14, FR-19
> CI 框架=Jenkins（D-016）。`receiver.py` 是 webhook 适配器（D-017）：校验内源站自定义鉴权头
> `X-Devcloud-Token`（共享密钥常量时间比较）→ 解析 push payload → 调 Jenkins
> `buildWithParameters` 触发评测 job。与 Jenkins 同机，HTTP 直连，无需 ssh/隧道。

## 为何保留适配器（而非纯 Generic Webhook Trigger 插件）

内部开源用 `X-Devcloud-Token` **请求头**认证 + 复杂 push payload。适配器复用已验证的校验/解析
逻辑，且解耦——内部开源不需知道 Jenkins job/token 细节。Generic Webhook Trigger 配 header
token + JSONPath 繁琐且多一个插件依赖。

## 链路

```
内源 push ──webhook(POST, X-Devcloud-Token 头, push payload)──▶ receiver.py
  校验 token(hmac.compare_digest) → _parse(repo/sha/branch)
  → POST http://127.0.0.1:<jenkins端口>/job/<job>/buildWithParameters?GIT_URL=..&GIT_SHA=..&BRANCH=..
     (Basic Auth: admin + JENKINS_ADMIN_PASSWORD；先取 CSRF crumb，同会话)
  → Jenkins job 串行执行(numExecutors=1) + auto-cancel(disableConcurrentBuilds abortPrevious)
```

幂等 / auto-cancel 交给 Jenkins job（同分支新构建取消旧的）；适配器只校验+触发，不维护状态。

## 配置

```bash
# config.ini [webhook]：listen（端口仅限 80-90/443/8080-8090）、git_auth（ssh|http，决定取 payload 哪个 url）
# config.ini [jenkins]：http_port / job_name / admin_user
# 密钥不入仓（C-1）：env 或 config.local.ini [secrets]
export WEBHOOK_SECRET=<与内源站一致的共享密钥>
export JENKINS_ADMIN_PASSWORD=<Jenkins admin 密码，适配器据此调 API>
# 部署时由 deploy.py 写入 systemd EnvironmentFile（0600），手动起服务用上面 env。
python3 server/webhook/receiver.py          # 监听 [webhook] listen
```

内源站把 webhook 指向 `http://<本机>:<webhook端口>/`，请求头带 `X-Devcloud-Token: <共享密钥>`，
订阅 Push Hook。

## 手测（curl，mock 内源 payload）

```bash
curl -X POST http://<host>:<webhook端口>/ \
  -H "X-Devcloud-Token: <共享密钥>" \
  -d '{"repo":"git@host:g/qsort.git","sha":"<commit>","branch":"main"}'
# 期望 202 queued in Jenkins；构建在 Jenkins UI 查看。
```

## 单测（mock Jenkins，无需真 Jenkins）

```bash
python3 server/webhook/test_receiver.py     # token 校验 + payload 解析 + buildWithParameters URL 构造
```

## 与 MCP 的分工

- **触发构建** → 本适配器（X-Devcloud-Token → Jenkins buildWithParameters）。
- **查状态 / 拉日志** → Jenkins 官方 `mcp-server` 插件（开发端接 opencode，见 `local/mcp/`）。
