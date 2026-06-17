#!/usr/bin/env python3
# implements: FR-14, FR-19
"""webhook 接收器 + 极简只读 Web UI（role=server/webhook，python3 标准库）。同一受限端口：
- POST /              ：X-Auth-Token 校验 → 解析 repo/ref → 入队 sqlite，返回 task id。
- GET  /              ：HTML 任务列表（最近 50，状态上色）。
- GET  /tasks/<id>    ：HTML 详情（状态表 + 完整日志，html.escape 防注入）。
- GET  /tasks/<id>/log：纯文本日志（给 curl/脚本）。
POST 必须 X-Auth-Token（防滥触发，密钥不入仓 C-1）；GET 内网只读放开（浏览器直接看）。
监听端口受限 80-90/443/8080-8090，见 03 设计。"""
import hmac
import html
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

STYLE = ("<style>body{font-family:monospace;margin:2em}"
         "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 10px;text-align:left}"
         ".passed{color:green}.failed{color:#c00}.error{color:#900}"
         ".running{color:#e80}.queued{color:#888}"
         "pre{background:#f4f4f4;padding:1em;overflow:auto;white-space:pre-wrap}</style>")


def _parse(body):
    """从 payload 取 repo/ref。通用 repo/ref；真实内网平台 payload 字段在此适配。"""
    d = json.loads(body or "{}")
    return d.get("repo", ""), d.get("ref", "main")


def _esc(v):
    return html.escape("" if v is None else str(v))


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, msg, ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(msg.encode("utf-8"))

    def _html(self, code, body):
        self._reply(code, body, "text/html; charset=utf-8")

    def do_POST(self):
        if not (SECRET and hmac.compare_digest(self.headers.get(AUTH_HEADER, ""), SECRET)):
            return self._reply(401, "unauthorized\n")
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            repo, ref = _parse(body)
            if not repo:
                return self._reply(400, "missing repo\n")
            tid = db.enqueue(DB_PATH, repo, ref)
            self._reply(202, "queued: task %d (GET /tasks/%d)\n" % (tid, tid))
        except Exception as e:  # noqa: BLE001
            self._reply(500, "enqueue failed: %s\n" % e)

    def do_GET(self):
        if self.path in ("/", "/ui"):
            return self._list()
        if self.path.startswith("/tasks/"):
            rest = self.path[len("/tasks/"):]
            return self._log(rest[:-4]) if rest.endswith("/log") else self._detail(rest)
        return self._reply(404, "not found\n")

    def _list(self):
        trs = "".join(
            "<tr><td><a href='/tasks/%(id)s'>%(id)s</a></td><td class='%(st)s'>%(st)s</td>"
            "<td>%(repo)s</td><td>%(ref)s</td><td>%(t)s</td></tr>"
            % {"id": r["id"], "st": _esc(r["state"]), "repo": _esc(r["repo"]),
               "ref": _esc(r["ref"]), "t": _esc(r["created_at"])}
            for r in db.list_tasks(DB_PATH, 50))
        self._html(200,
                   "<!doctype html><meta charset='utf-8'><title>CI 任务</title>%s"
                   "<h2>CI 评测任务（最近 50）</h2><table>"
                   "<tr><th>#</th><th>状态</th><th>repo</th><th>ref</th><th>创建</th></tr>"
                   "%s</table>" % (STYLE, trs))

    def _detail(self, id_str):
        try:
            tid = int(id_str)
        except ValueError:
            return self._reply(400, "bad task id\n")
        row = db.get(DB_PATH, tid)
        if not row:
            return self._reply(404, "no such task\n")
        log = ""
        if row.get("log_path") and os.path.exists(row["log_path"]):
            with open(row["log_path"], encoding="utf-8", errors="replace") as f:
                log = f.read()
        fields = "".join("<tr><th>%s</th><td>%s</td></tr>" % (k, _esc(row.get(k)))
                         for k in ("id", "state", "repo", "ref", "exit_code",
                                   "created_at", "started_at", "finished_at"))
        self._html(200,
                   "<!doctype html><meta charset='utf-8'><title>任务 %d</title>%s"
                   "<p><a href='/'>&larr; 列表</a></p>"
                   "<h2>任务 %d <span class='%s'>%s</span></h2><table>%s</table>"
                   "<h3>日志</h3><pre>%s</pre>"
                   % (tid, STYLE, tid, _esc(row["state"]), _esc(row["state"]),
                      fields, _esc(log) or "（无日志）"))

    def _log(self, id_str):
        try:
            tid = int(id_str)
        except ValueError:
            return self._reply(400, "bad task id\n")
        row = db.get(DB_PATH, tid)
        if not row or not row.get("log_path") or not os.path.exists(row["log_path"]):
            return self._reply(404, "no log\n")
        with open(row["log_path"], encoding="utf-8", errors="replace") as f:
            self._reply(200, f.read())

    def log_message(self, *a):
        pass


def build_server(host, port):
    db.init(DB_PATH)
    return HTTPServer((host, int(port)), Handler)


def main():
    host, _, port = ci_config.get(_CFG, "webhook", "listen", "0.0.0.0:8080").partition(":")
    httpd = build_server(host, int(port))
    print("[webhook] 监听 %s:%s（POST 入队需 X-Auth；GET 网页/日志只读）db=%s"
          % (host, port, DB_PATH))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
