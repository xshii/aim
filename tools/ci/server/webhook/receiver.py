#!/usr/bin/env python3
# implements: FR-14, FR-19
"""webhook 适配器（role=server/webhook，python3 标准库）。CI 框架=Jenkins（D-016/D-017）。
内源 push webhook → 校验 X-Devcloud-Token → 解析 payload → 调 Jenkins buildWithParameters 触发构建。
- POST /：X-Devcloud-Token 常量时间校验 → 解析 (GIT_URL, GIT_SHA, BRANCH) → 触发 Jenkins job。
- GET  /：极简健康页，指向 Jenkins UI（任务列表/日志看 Jenkins 自带 UI，不再自造）。
幂等 / auto-cancel 交给 Jenkins job 的 disableConcurrentBuilds(abortPrevious)（D-017）。
密钥不入仓（C-1）：WEBHOOK_SECRET、JENKINS_ADMIN_PASSWORD 经 env / config.local.ini 注入。
监听端口受限 80-90/443/8080-8090（deploy.py check 校验）。"""
import base64
import hmac
import http.cookiejar
import json
import os
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
_R = HERE
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
sys.path.insert(0, _R)
import ci_config     # noqa: E402
import constants as C  # noqa: E402

_CFG = ci_config.load()
AUTH_HEADER = C.AUTH_HEADER
GIT_AUTH = ci_config.get(_CFG, "webhook", "git_auth", "ssh")
SECRET = ci_config.secret("WEBHOOK_SECRET", _CFG, "secrets", "webhook_secret")
JENKINS_PORT = ci_config.get(_CFG, "jenkins", "http_port", "8080")
JENKINS_URL = "http://127.0.0.1:%s" % JENKINS_PORT          # 同机直连 Jenkins
JOB = ci_config.get(_CFG, "jenkins", "job_name", "qsort-eval")
JK_USER = ci_config.get(_CFG, "jenkins", "admin_user", "admin")
JK_PASS = ci_config.secret("JENKINS_ADMIN_PASSWORD", _CFG, "secrets", "jenkins_admin_password")


def _parse(body):
    """从内部开源 push webhook payload 取 (repo, sha, branch)。
    repo：project.git_ssh_url（ssh）/ git_http_url（http），按 [webhook] git_auth 选；
    sha：checkout_sha（精确 commit，可空）；branch：ref 剥 refs/heads|tags/ 前缀（默认 main）。
    兼容裸 {repo,sha,branch}（便于手测/curl）。"""
    d = json.loads(body or "{}")
    proj = d.get(C.F_PROJECT) or d.get(C.F_REPOSITORY) or {}
    repo = (proj.get(C.F_HTTP_URL if GIT_AUTH == "http" else C.F_SSH_URL, "")
            or d.get("repo", ""))
    sha = d.get(C.F_CHECKOUT_SHA, "") or d.get("sha", "")
    branch = d.get(C.F_REF, "") or d.get("branch", "main")
    for pre in C.REF_PREFIXES:
        if branch.startswith(pre):
            branch = branch[len(pre):]
            break
    return repo, sha, branch or "main"


def _opener():
    """带 cookie 的 opener：crumb 与构建请求共用同一会话（Jenkins crumb 绑会话）。"""
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def trigger_build(repo, sha, branch, opener=None):
    """调 Jenkins buildWithParameters 触发 job。返回 (status_code, detail)。
    先取 CSRF crumb（同会话），再带 Basic Auth + crumb POST。crumb 取不到则不带（CSRF 关时）。"""
    opener = opener or _opener()
    auth = base64.b64encode(("%s:%s" % (JK_USER, JK_PASS)).encode()).decode()
    headers = {"Authorization": "Basic %s" % auth}

    try:
        creq = urllib.request.Request(JENKINS_URL + "/crumbIssuer/api/json", headers=headers)
        cj = json.loads(opener.open(creq, timeout=10).read().decode())
        headers[cj["crumbRequestField"]] = cj["crumb"]
    except Exception as e:  # noqa: BLE001  CSRF 关闭/旧版无 crumb：继续不带 crumb
        print("[webhook] 无 crumb（CSRF 关？继续）：%s" % e, flush=True)

    qs = urllib.parse.urlencode({"GIT_URL": repo, "GIT_SHA": sha, "BRANCH": branch})
    url = "%s/job/%s/buildWithParameters?%s" % (JENKINS_URL, urllib.parse.quote(JOB), qs)
    req = urllib.request.Request(url, data=b"", headers=headers, method="POST")
    resp = opener.open(req, timeout=15)
    return resp.status, resp.headers.get("Location", "")


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, msg, ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(msg.encode("utf-8"))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        authed = bool(SECRET) and hmac.compare_digest(self.headers.get(AUTH_HEADER, ""), SECRET)
        print("[webhook] POST %s  X-Devcloud-Event=%s  %s=%s  -> %s"
              % (self.path, self.headers.get(C.EVENT_HEADER, "-"), AUTH_HEADER,
                 "***" if self.headers.get(AUTH_HEADER) else "(缺)",
                 "认证通过" if authed else "认证失败→401"), flush=True)
        if not authed:
            return self._reply(401, "unauthorized\n")
        print("[webhook] body: %s" % (body[:2000] if body else "(空)"), flush=True)
        try:
            repo, sha, branch = _parse(body)
            print("[webhook] 解析: repo=%s sha=%s branch=%s" % (repo, sha, branch), flush=True)
            if not repo:
                # 非 push 事件 / payload 无 repo：确认收到但忽略，避免平台无意义重试。
                print("[webhook] 无 repo（非 push 事件？），忽略", flush=True)
                return self._reply(200, "ignored: no repo\n")
            status, loc = trigger_build(repo, sha, branch)
            print("[webhook] 已触发 Jenkins %s job=%s -> HTTP %s %s"
                  % (JENKINS_URL, JOB, status, loc), flush=True)
            self._reply(202, "queued in Jenkins: job=%s (%s)\n" % (JOB, loc or "see Jenkins UI"))
        except Exception as e:  # noqa: BLE001
            print("[webhook] 触发失败: %s" % e, flush=True)
            self._reply(502, "trigger failed: %s\n" % e)

    def do_GET(self):
        self._reply(200,
                    "<!doctype html><meta charset='utf-8'><title>CI webhook 适配器</title>"
                    "<p>webhook 适配器在线。任务列表 / 构建日志请看 Jenkins UI："
                    "<a href='http://%s:%s/'>Jenkins</a>（job: %s）。</p>"
                    % (self.headers.get("Host", "<host>").split(":")[0], JENKINS_PORT, JOB),
                    "text/html; charset=utf-8")

    def log_message(self, *a):
        pass


def main():
    host, _, port = ci_config.get(_CFG, "webhook", "listen", "0.0.0.0:8090").partition(":")
    httpd = HTTPServer((host, int(port)), Handler)
    print("[webhook] 适配器监听 %s:%s → Jenkins %s job=%s（POST 触发需 X-Devcloud-Token）"
          % (host, port, JENKINS_URL, JOB))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
