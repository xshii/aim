#!/usr/bin/env python3
"""集中易变常量：内部开源 webhook 头 / push payload 字段 / 任务状态 / 端口白名单。
平台适配或字段变更只改本文件，避免散落各处来回改（C-7 精神）。"""

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

# --- 任务状态机：queued → running → {passed|failed|error} ---
ST_QUEUED = "queued"
ST_RUNNING = "running"
ST_PASSED = "passed"
ST_FAILED = "failed"
ST_ERROR = "error"

# --- webhook 对外端口白名单（内网防火墙：80-90 / 443 / 8080-8090）---
ALLOWED_PORTS = frozenset(range(80, 91)) | {443} | frozenset(range(8080, 8091))
