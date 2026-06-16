# GitLab CE 特性开启清单

> implements: FR-10
> 本清单规定 GitLab CE 为支撑本 CI 系统所需开启 / 禁用的特性，每项附理由。
> 所有配置须遵守宪法 C-1（不外泄）：凡涉及对外联网上报的一律禁用。

## 必须开启

| 特性 | 理由 | 关联 |
|------|------|------|
| 私有项目（Private） | 内部 benchmark 仓库不得公开 | C-1, O-4 |
| CI/CD（Pipelines） | 运行评测流水线 | FR-1, FR-2 |
| Runner 注册 | 接入仿真机执行任务 | FR-3 |
| Webhook | 触发流水线、回调（HTTP 直连） | FR-14 |
| 定时流水线（Scheduled Pipelines） | nightly 全量回归 | FR-1 |
| 备份（gitlab-ctl backup） | 数据可恢复 | 运维 |
| 容器镜像仓库（可选） | 当前无 Docker，**默认不开**；未来若需再评估 | — |

## 必须禁用（宪法 C-1）

| 特性 | 理由 |
|------|------|
| Usage Ping / Service Ping（使用数据上报） | 禁止任何向外部上报使用数据 |
| Version Check（版本检查外联） | 禁止外联 GitLab 服务器 |
| 错误/遥测上报（Sentry 等外部端点） | 禁止数据外发 |
| 任何指向公网的集成（外部 OAuth、外部对象存储等） | 不外泄 |

## gitlab.rb 关键片段

见同目录 `gitlab.rb.example`。核心：
```ruby
# 禁用对外遥测（C-1）
gitlab_rails['usage_ping_enabled'] = false
gitlab_rails['sentry_enabled'] = false
# 关闭新用户注册（内部私有）
gitlab_rails['gitlab_signup_enabled'] = false
```

## 验证

```bash
sudo gitlab-ctl reconfigure
sudo gitlab-ctl status        # 组件全部 run:
# 网页确认：能建 Private 项目、能拿 Runner Token、无外联遥测
```
