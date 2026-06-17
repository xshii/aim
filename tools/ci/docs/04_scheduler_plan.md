# 自研极简 CI 调度器 实现计划

> 设计与代码骨架见 `docs/03_scheduler_design.md`。本文件只列**任务顺序 / 文件 / 防坑要点 / 验证 / commit**。
> 全程 TDD（标准库 `unittest`），python3.8，每任务一次 commit。在 `feat/scheduler-ci` 分支实施。

| # | 任务 | 文件 | 验证 |
|---|------|------|------|
| T1 | sqlite 队列 | `server/scheduler/db.py` (+`test_db.py`) | `cd server/scheduler && python3 -m unittest test_db` |
| T2 | git checkout | `server/scheduler/checkout.py` (+test) | 同上 test_checkout |
| T3 | worker 串行循环 | `server/scheduler/worker.py` (+test) | 同上 test_worker |
| T4 | webhook 改入队 | 改 `server/webhook/receiver.py` (+test) | 同上 test_receiver |
| T5 | MCP 改查 sqlite | 改 `local/mcp/ci_control_server.py` (+test) | 同上 test_mcp |
| T6 | deploy 改 systemd | 改 `server/deploy/deploy.py` + `systemd/*.service` | `py_compile` + 端口校验 `8080∈ALLOWED, 9100∉` |
| T7 | 删 GitLab + 同步 | 删 6 文件；改 `config.ini`/`01_spec.md`/`consistency.py` | `python3 checks/consistency.py` 通过 |
| T8 | quick_deploy 重写 | 改 `gen_quick_deploy.py` | 重生成 + py_compile |
| T9 | 端到端冒烟 | `server/scheduler/smoke_scheduler.py` | qsort 经调度器跑出 `passed` |

## 关键防坑要点（实现时照 03 设计）

- **T1**：`claim()` 用 `BEGIN IMMEDIATE` 事务原子取任务（支持未来多 worker）；`reset_stale()` 启动时清悬挂 `running`→`error`。
- **T2**：http token 用 `GIT_ASKPASS` 临时脚本提供，**绝不进命令行**（C-1，防 `ps` 泄露）；先 `rmtree(dest)` 再 clone。
- **T3**：`run_one(cfg, do_checkout=, run_pipeline=)` 注入式，便于单测 stub；`concurrency=1` 即仿真串行；异常→`error`、门禁非零→`failed`。
- **T4**：保留 `X-Auth-Token` + `hmac.compare_digest`；校验后入队（删 GitLab trigger 转发）；暴露 `build_server()` 供测试。
- **T5**：暴露 `handle(req)` 供测试；工具 `get_task_status`/`list_tasks`/`get_task_log`；db 路径经 `CI_DB_PATH`/config。
- **T6**：`check` 校验 `[webhook] listen` 端口 ∈ `{80-90,443,8080-8090}` 否则停（C-10）；需 root；systemd unit 用 `%CI_ROOT%` 占位替换。
- **T7**：`config.ini` 加 `[scheduler]`、`[webhook] listen=0.0.0.0:8080`、删 GitLab 项；`01_spec.md` 加 FR-21/D-013、删 GitLab 专属 FR 内容；`consistency.py` 的 `server` 递归已覆盖 `scheduler`。
- **T9**：临时 git repo 装入 `demo/qsort` → 入队 → `worker.run_one` 真实 checkout + 跑 `smoke_qsort.py` → 断言 `passed`。

## 验收（全绿才算完成）

```bash
cd tools/ci
python3 -m py_compile $(git ls-files '*.py')
for t in db checkout worker receiver mcp; do (cd server/scheduler && python3 -m unittest test_$t); done
python3 server/scheduler/smoke_scheduler.py     # → passed
python3 checks/consistency.py                    # → 通过
```

## Self-review

Spec 全覆盖（FR-1/2/3/6/7/13/14/12/20/21 + 端口/X-Auth/git-ssh-http 三约束各有归属）；唯一明示裁剪：webhook payload 字段按通用 `repo`/`ref`，真实平台格式在 T4 `_parse` 适配。
