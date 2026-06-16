#!/usr/bin/env python3
# implements: FR-12, FR-20
"""
CI 操作 MCP server（role=local/mcp，stdio，标准 MCP 握手，Python 3.8 标准库，零依赖）。
合并原 mcp_stdio + ci_control_server（M3）。给开发端（人 / opencode 等 MCP 客户端）查 CI：
查流水线状态、列流水线、拉 job 日志。经 GitLab REST API（HTTP 直连，内网可达）访问。
接入 opencode：见同目录 opencode.json.example。凭证用环境变量（不入仓，C-1）：
  GITLAB_API     如 http://10.0.0.10:8929/api/v4
  GITLAB_TOKEN   personal access token
  GITLAB_PROJECT 项目 ID 或 URL-encoded 路径，如 42 或 group%2Fproject
用法: GITLAB_API=... GITLAB_TOKEN=... GITLAB_PROJECT=... python3 ci_control_server.py
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("GITLAB_API", "").rstrip("/")
TOKEN = os.environ.get("GITLAB_TOKEN", "")
PROJECT = os.environ.get("GITLAB_PROJECT", "")
# 内网 GitLab 走 HTTP 直连，不经任何代理（D-008）；屏蔽开发机环境里的 HTTP(S)_PROXY。
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ---------- 最小标准 MCP stdio server（JSON-RPC over stdio） ----------
class StdioMCP:
    PROTOCOL = "2024-11-05"

    def __init__(self, name, version="0.1.0"):
        self.name, self.version, self.tools = name, version, {}

    def tool(self, name, description, schema, handler):
        self.tools[name] = (description, schema, handler)

    def _send(self, obj):
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    def _ok(self, rid, result):
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def _err(self, rid, code, msg):
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}

    def _handle(self, req):
        method, rid = req.get("method"), req.get("id")
        if rid is None:                              # 通知（如 notifications/initialized）：不回应
            return None
        if method == "initialize":
            cv = (req.get("params") or {}).get("protocolVersion") or self.PROTOCOL
            return self._ok(rid, {"protocolVersion": cv,
                                  "capabilities": {"tools": {}},
                                  "serverInfo": {"name": self.name, "version": self.version}})
        if method == "ping":
            return self._ok(rid, {})
        if method == "tools/list":
            return self._ok(rid, {"tools": [
                {"name": n, "description": d, "inputSchema": s}
                for n, (d, s, _) in self.tools.items()]})
        if method == "tools/call":
            p = req.get("params") or {}
            name, args = p.get("name"), (p.get("arguments") or {})
            if name not in self.tools:
                return self._err(rid, -32602, "unknown tool: %s" % name)
            try:
                text = self.tools[name][2](args)
                return self._ok(rid, {"content": [{"type": "text", "text": text}], "isError": False})
            except Exception as e:  # noqa
                return self._ok(rid, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        return self._err(rid, -32601, "unknown method: %s" % method)

    def serve(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            resp = self._handle(req)
            if resp is not None:
                self._send(resp)


# ---------- GitLab API ----------
def _check_env():
    missing = [k for k, v in (("GITLAB_API", API), ("GITLAB_TOKEN", TOKEN),
                              ("GITLAB_PROJECT", PROJECT)) if not v]
    if missing:
        raise RuntimeError("缺少环境变量：%s（勿编造，请正确配置）" % ", ".join(missing))


def _req(method, path):
    _check_env()
    url = "%s/projects/%s%s" % (API, urllib.parse.quote(str(PROJECT), safe=""), path)
    r = urllib.request.Request(url, method=method)
    r.add_header("PRIVATE-TOKEN", TOKEN)
    try:
        with _DIRECT.open(r, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": "HTTP %s" % e.code, "detail": e.read().decode("utf-8", "replace")}
    except Exception as e:  # noqa
        return {"error": str(e)}


def get_pipeline_status(args):
    pid = args.get("pipeline_id")
    if not pid:
        lst = _req("GET", "/pipelines?per_page=1")
        if not (isinstance(lst, list) and lst):
            return "无流水线记录。"
        pid = lst[0].get("id")
    res = _req("GET", "/pipelines/%s" % pid)
    if isinstance(res, dict) and "error" in res:
        return json.dumps(res, ensure_ascii=False)
    return "pipeline %s: status=%s ref=%s sha=%s\n%s" % (
        res.get("id"), res.get("status"), res.get("ref"),
        (res.get("sha") or "")[:8], res.get("web_url", ""))


def list_pipelines(args):
    limit = int(args.get("limit", 5))
    res = _req("GET", "/pipelines?per_page=%d" % limit)
    if isinstance(res, dict) and "error" in res:
        return json.dumps(res, ensure_ascii=False)
    lines = ["#%s %s (%s)" % (p.get("id"), p.get("status"), p.get("ref"))
             for p in res] if isinstance(res, list) else []
    return "\n".join(lines) if lines else "无记录。"


def get_job_log(args):
    job_id = args.get("job_id")
    if not job_id:
        return "需要 job_id。"
    _check_env()
    url = "%s/projects/%s/jobs/%s/trace" % (
        API, urllib.parse.quote(str(PROJECT), safe=""), job_id)
    r = urllib.request.Request(url)
    r.add_header("PRIVATE-TOKEN", TOKEN)
    try:
        with _DIRECT.open(r, timeout=30) as resp:
            log = resp.read().decode("utf-8", "replace")
        return log[-4000:] or "（日志为空）"     # 只回尾部，错误通常在末尾
    except Exception as e:  # noqa
        return "拉日志失败：%s" % e


def main():
    s = StdioMCP("ci_control")
    s.tool("get_pipeline_status", "查流水线状态（不传 pipeline_id 则查最新）",
           {"type": "object", "properties": {
               "pipeline_id": {"type": ["integer", "string"], "description": "流水线 ID，可空"}}},
           get_pipeline_status)
    s.tool("list_pipelines", "列最近若干条流水线",
           {"type": "object", "properties": {
               "limit": {"type": "integer", "description": "条数，默认 5"}}},
           list_pipelines)
    s.tool("get_job_log", "拉取某 job 的日志尾部（含错误）",
           {"type": "object",
            "properties": {"job_id": {"type": ["integer", "string"]}},
            "required": ["job_id"]},
           get_job_log)
    s.serve()


if __name__ == "__main__":
    main()
