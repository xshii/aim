#!/usr/bin/env python3
"""集中易变常量：内部开源 webhook 头 / push payload 字段 / 端口白名单。
平台适配或字段变更只改本文件，避免散落各处来回改（C-7 精神）。
任务状态机已随自研调度器移除（D-016 改用 Jenkins，构建状态由 Jenkins 维护）。"""

# --- 内部开源 webhook 请求头 ---
AUTH_HEADER = "X-Devcloud-Token"       # 共享密钥头（POST 触发认证）
EVENT_HEADER = "X-Devcloud-Event"      # 事件类型头（如 "Push Hook"）

# --- push payload 字段（receiver._parse 据此提取 repo/ref）---
F_PROJECT = "project"
F_REPOSITORY = "repository"            # project 缺失时回退
F_SSH_URL = "git_ssh_url"
F_HTTP_URL = "git_http_url"
F_CHECKOUT_SHA = "checkout_sha"
F_REF = "ref"
REF_PREFIXES = ("refs/heads/", "refs/tags/")

# --- webhook / Jenkins 对外端口白名单（内网防火墙：80-90 / 443 / 8080-8090）---
ALLOWED_PORTS = frozenset(range(80, 91)) | {443} | frozenset(range(8080, 8091))
