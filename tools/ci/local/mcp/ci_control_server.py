#!/usr/bin/env python3
# implements: FR-12, FR-20
"""开发端 MCP（role=local/mcp，stdio，标准 MCP 握手，python3 标准库，零依赖）。
直连本地 sqlite 任务库，供 opencode 等 MCP 客户端查评测状态/列表/日志（无 GitLab）。
工具：get_task_status / list_tasks / get_task_log。db 路径经 env CI_DB_PATH 或 config [scheduler] db_path。
接入 opencode 见同目录 opencode.json.example。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_R = HERE
while _R != "/" and not os.path.isfile(os.path.join(_R, "ci_config.py")):
    _R = os.path.dirname(_R)
sys.path.insert(0, _R)
sys.path.insert(0, os.path.join(_R, "server", "scheduler"))
import ci_config  # noqa: E402
import db          # noqa: E402

PROTOCOL = "2024-11-05"
DB_PATH = os.environ.get("CI_DB_PATH") or ci_config.expand(
    ci_config.get(ci_config.load(), "scheduler", "db_path", os.path.join(_R, "var/ci.db")))

TOOLS = [
    {"name": "get_task_status", "description": "查询某评测任务的状态",
     "inputSchema": {"type": "object", "properties": {"task_id": {"type": "integer"}},
                     "required": ["task_id"]}},
    {"name": "list_tasks", "description": "列最近评测任务",
     "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "get_task_log", "description": "取某任务日志尾部",
     "inputSchema": {"type": "object", "properties": {"task_id": {"type": "integer"}},
                     "required": ["task_id"]}},
]


def _text(s):
    return {"content": [{"type": "text", "text": s}]}


def _call(name, args):
    if name == "get_task_status":
        row = db.get(DB_PATH, args["task_id"])
        return _text(json.dumps(row, ensure_ascii=False) if row else "not found")
    if name == "list_tasks":
        return _text(json.dumps(db.list_tasks(DB_PATH, args.get("limit", 20)),
                                ensure_ascii=False))
    if name == "get_task_log":
        row = db.get(DB_PATH, args["task_id"])
        if not row or not row.get("log_path") or not os.path.exists(row["log_path"]):
            return _text("no log")
        with open(row["log_path"], encoding="utf-8", errors="replace") as f:
            return _text(f.read()[-4000:])
    raise ValueError("unknown tool %s" % name)


def handle(req):
    m = req.get("method")
    rid = req.get("id")
    if m == "initialize":
        res = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
               "serverInfo": {"name": "ci-control", "version": "2.0"}}
    elif m == "tools/list":
        res = {"tools": TOOLS}
    elif m == "tools/call":
        p = req.get("params", {})
        res = _call(p["name"], p.get("arguments", {}))
    else:
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": rid, "result": res}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            resp = handle(json.loads(line))
        except Exception as e:  # noqa: BLE001
            resp = {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32603, "message": str(e)}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
