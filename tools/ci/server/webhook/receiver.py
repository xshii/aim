#!/usr/bin/env python3
# implements: FR-19
"""
内源托管 webhook 接收器（role=server/webhook，Python 3.8 标准库 http.server，零依赖）。
接受内部代码托管站的入站 webhook：校验请求头共享密钥（默认 X-Auth-Token，常量时间比较）→
经 GitLab trigger token 触发对应流水线。与 GitLab 同机部署，转发本地 GitLab API。
共享密钥(WEBHOOK_SECRET)与 trigger token(GITLAB_TRIGGER_TOKEN) 不入仓（env / config.local.ini，C-1）。
用法: python3 server/webhook/receiver.py（凭证经环境变量或 config.local.ini 注入）
"""
import hmac
import os
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

_R = os.path.dirname(os.path.abspath(__file__))
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
sys.path.insert(0, _R)
import ci_config  # noqa: E402

CFG = ci_config.load()


def _g(key, default=""):
    return ci_config.get(CFG, "webhook", key, default)


AUTH_HEADER = _g("auth_header", "X-Auth-Token")
SECRET = ci_config.secret("WEBHOOK_SECRET", CFG)
TRIGGER_TOKEN = ci_config.secret("GITLAB_TRIGGER_TOKEN", CFG)
REF = _g("ref", "main")
PROJECT = _g("project_id", "")
# 内网 GitLab 走 HTTP 直连，不经任何代理（D-008）；屏蔽环境里的 HTTP(S)_PROXY。
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def trigger_url():
    """GitLab trigger API：env GITLAB_API 优先，否则由 [server].host + [gitlab].http_port 组装。"""
    api = os.environ.get("GITLAB_API", "").rstrip("/")
    if not api:
        host = ci_config.get(CFG, "server", "host", "").strip()
        port = ci_config.get(CFG, "gitlab", "http_port", "").strip()
        if not (host and port):
            raise RuntimeError("缺 GITLAB_API 或 server.host/gitlab.http_port（C-10）。")
        api = "http://%s:%s/api/v4" % (host, port)
    if not PROJECT:
        raise RuntimeError("缺 [webhook] project_id（C-10）。")
    return "%s/projects/%s/trigger/pipeline" % (api, urllib.parse.quote(str(PROJECT), safe=""))


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, msg):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(msg.encode("utf-8"))

    def do_POST(self):
        if not SECRET:
            return self._reply(500, "server 未配置 WEBHOOK_SECRET\n")
        if not hmac.compare_digest(self.headers.get(AUTH_HEADER, ""), SECRET):
            return self._reply(401, "unauthorized\n")
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)                 # 丢弃 body（共享密钥模式不解析）
        if not TRIGGER_TOKEN:
            return self._reply(500, "server 未配置 GITLAB_TRIGGER_TOKEN\n")
        data = urllib.parse.urlencode({"token": TRIGGER_TOKEN, "ref": REF}).encode()
        try:
            with _DIRECT.open(trigger_url(), data=data, timeout=15) as r:
                self._reply(202, "triggered: HTTP %s\n" % r.getcode())
        except Exception as e:  # noqa  含配置错误(RuntimeError)与网络错误，统一返回而不崩溃服务
            self._reply(502, "trigger failed: %s\n" % e)

    def log_message(self, fmt, *a):                 # 不打印请求头，避免泄露鉴权信息
        sys.stderr.write("[webhook] " + (fmt % a) + "\n")


def main():
    if _g("enabled", "false").lower() != "true":
        raise SystemExit("[webhook] enabled=false（改 config.ini [webhook] enabled=true 启用）。")
    try:
        trigger_url()                               # 启动即校验触发目标，缺配置 fail-fast（C-10）
    except RuntimeError as e:
        raise SystemExit(str(e))
    listen = _g("listen", "0.0.0.0:9100")
    host, _, port = listen.partition(":")
    srv = HTTPServer((host, int(port or 9100)), Handler)
    print("[webhook] 监听 %s，鉴权头 %s（共享密钥）→ 触发 GitLab ref=%s" % (listen, AUTH_HEADER, REF))
    srv.serve_forever()


if __name__ == "__main__":
    main()
