#!/usr/bin/env python3
# implements: FR-14, FR-19
"""webhook 接收器 + 查询接口（role=server/webhook，python3 标准库）。同一受限端口：
- POST /              ：X-Auth-Token 校验 → 解析 repo/ref → 入队 sqlite，返回 task id 与查询地址。
- GET /tasks/<id>     ：查任务状态（json）。
- GET /tasks/<id>/log ：查任务日志。
GET/POST 均校验 X-Auth-Token（日志含代码/路径，内网亦须认证，C-1）。密钥不入仓
（env WEBHOOK_SECRET 或 config.local.ini [secrets]）。监听端口受限 80-90/443/8080-8090，见 03 设计。"""
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
_R = HERE
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
sys.path.insert(0, _R)
sys.path.insert(0, os.path.join(_R, "server", "scheduler"))
import ci_config  # noqa: E402
import db          # noqa: E402

_CFG = ci_config.load()
AUTH_HEADER = ci_config.get(_CFG, "webhook", "auth_header", "X-Auth-Token")
SECRET = ci_config.secret("WEBHOOK_SECRET", _CFG, "secrets", "webhook_secret")
DB_PATH = os.environ.get("CI_DB_PATH") or ci_config.expand(
    ci_config.get(_CFG, "scheduler", "db_path", os.path.join(_R, "var/ci.db")))


def _parse(body):
    """从 payload 取 repo/ref。通用 repo/ref；真实内网平台 payload 字段在此适配。"""
    d = json.loads(body or "{}")
    return d.get("repo", ""), d.get("ref", "main")


class Handler(BaseHTTPRequestHandler):
    def _auth_ok(self):
        return bool(SECRET) and hmac.compare_digest(self.headers.get(AUTH_HEADER, ""), SECRET)

    def _reply(self, code, msg, ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(msg.encode("utf-8"))

    def do_POST(self):
        if not self._auth_ok():
            return self._reply(401, "unauthorized\n")
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            repo, ref = _parse(body)
            if not repo:
                return self._reply(400, "missing repo\n")
            tid = db.enqueue(DB_PATH, repo, ref)
            self._reply(202, "queued: task %d\n  状态: GET /tasks/%d\n  日志: GET /tasks/%d/log\n"
                        % (tid, tid, tid))
        except Exception as e:  # noqa: BLE001
            self._reply(500, "enqueue failed: %s\n" % e)

    def do_GET(self):
        if not self._auth_ok():
            return self._reply(401, "unauthorized\n")
        if not self.path.startswith("/tasks/"):
            return self._reply(404, "not found\n")
        rest = self.path[len("/tasks/"):]
        want_log = rest.endswith("/log")
        id_str = rest[:-4] if want_log else rest
        try:
            tid = int(id_str)
        except ValueError:
            return self._reply(400, "bad task id\n")
        row = db.get(DB_PATH, tid)
        if not row:
            return self._reply(404, "no such task\n")
        if want_log:
            lp = row.get("log_path")
            if not lp or not os.path.exists(lp):
                return self._reply(404, "no log\n")
            with open(lp, encoding="utf-8", errors="replace") as f:
                return self._reply(200, f.read())
        return self._reply(200, json.dumps(row, ensure_ascii=False) + "\n",
                           "application/json; charset=utf-8")

    def log_message(self, *a):
        pass


def build_server(host, port):
    db.init(DB_PATH)
    return HTTPServer((host, int(port)), Handler)


def main():
    host, _, port = ci_config.get(_CFG, "webhook", "listen", "0.0.0.0:8080").partition(":")
    httpd = build_server(host, int(port))
    print("[webhook] 监听 %s:%s（X-Auth-Token 校验；POST 入队 / GET 查状态日志）db=%s"
          % (host, port, DB_PATH))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
