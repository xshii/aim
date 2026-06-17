#!/usr/bin/env python3
# implements: FR-21
"""任务队列（sqlite，python3 标准库）。状态机：queued → running → {passed|failed|error}。
passed/failed=评测门禁结果；error=系统错（checkout 失败/超时/崩溃）。供 worker 与 MCP 共用。"""
import datetime
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  repo        TEXT    NOT NULL,
  ref         TEXT    NOT NULL,
  state       TEXT    NOT NULL DEFAULT 'queued',
  created_at  TEXT    NOT NULL,
  started_at  TEXT,
  finished_at TEXT,
  exit_code   INTEGER,
  log_path    TEXT
);
CREATE INDEX IF NOT EXISTS idx_state ON tasks(state);
"""


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def connect(db_path):
    d = os.path.dirname(db_path)
    if d:
        os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init(db_path):
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def enqueue(db_path, repo, ref):
    conn = connect(db_path)
    cur = conn.execute(
        "INSERT INTO tasks(repo, ref, state, created_at) VALUES(?,?,'queued',?)",
        (repo, ref, _now()))
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def claim(db_path):
    """原子取一个 queued 任务置 running（BEGIN IMMEDIATE 支持未来多 worker）。无则 None。"""
    conn = connect(db_path)
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM tasks WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            conn.execute("COMMIT")
            return None
        conn.execute("UPDATE tasks SET state='running', started_at=? WHERE id=?",
                     (_now(), row["id"]))
        conn.execute("COMMIT")
        return dict(row)
    finally:
        conn.close()


def finish(db_path, tid, state, exit_code, log_path):
    conn = connect(db_path)
    conn.execute(
        "UPDATE tasks SET state=?, exit_code=?, log_path=?, finished_at=? WHERE id=?",
        (state, exit_code, log_path, _now(), tid))
    conn.commit()
    conn.close()


def reset_stale(db_path):
    """worker 启动时把残留 running（上次崩溃）标 error，返回条数。"""
    conn = connect(db_path)
    n = conn.execute("UPDATE tasks SET state='error', finished_at=? WHERE state='running'",
                     (_now(),)).rowcount
    conn.commit()
    conn.close()
    return n


def get(db_path, tid):
    conn = connect(db_path)
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_tasks(db_path, limit=20):
    conn = connect(db_path)
    rows = conn.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
