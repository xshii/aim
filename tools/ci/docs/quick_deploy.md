════════════════════════════════════════════════════════════
 Quick Deploy · 自研 CI 调度器
════════════════════════════════════════════════════════════

  › 自动生成（gen_quick_deploy.py 依据 config.ini），改配置后重跑。

  › 纯 python3 标准库调度器，替代 GitLab（D-013）：webhook 入队 → 单 worker 串行 checkout+评测 → sqlite → MCP/网页查。


▶ 准备
────────────────────────────────────────────────────────────
  1. config.ini：[scheduler]（db/工作区/concurrency/git_auth）、[webhook] listen、[remote]（远端 bootstrap）。
  2. config.local.ini（不入仓）：[secrets] webhook_secret；[scheduler] ssh_key 或 http_token（git checkout 用）。
  3. 代码托管用内网现有仓库（不新建）；仓库后台配 WebHook 指向本服务（见 C 段）。


▶ 本期要点
────────────────────────────────────────────────────────────
  • 组件：webhook 接收器(+只读 UI) + 单 worker 串行调度 + sqlite 任务库 + MCP（接 opencode）。
  • 仿真串行：concurrency=1（单 worker 天然串行 = License 数）。
  • webhook 端口仅限 80-90 / 443 / 8080-8090；认证头 X-Devcloud-Token（平台固定，见 constants.py）。
  • 纯标准库零依赖、内网离线；凭证不入仓（ssh_key/token/密钥经 config.local.ini）。git_auth=ssh。


▶ A. 首次远端 bootstrap（在执行机上，可选）
────────────────────────────────────────────────────────────
  › 当前 [remote] host = (未配置)。host 为空 = 不用远端，直接在服务器跑 B 段。

  A1  admin 连通性自检（SSH / 远端 python3 / 管理员权限）
      python3 local/admin/deploy_remote.py check
  A2  SSH/SCP 推代码到远端 /opt/ci（纯 python，无 .deb）
      python3 local/admin/deploy_remote.py push
  A3  一条龙：check → push → 远程跑 deploy.py all
      python3 local/admin/deploy_remote.py all
      ↳ 非 root 用户经 ssh -tt 交互输 sudo 密码


▶ B. 服务器本地部署（需 root）
────────────────────────────────────────────────────────────
  1   环境自检（python3 / git / systemctl / root / webhook 端口范围）
      sudo python3 server/deploy/deploy.py check
  2   初始化 sqlite + 工作区/日志目录
      sudo python3 server/deploy/deploy.py init
  3   安装并启用 systemd 服务（ci-webhook + ci-worker）
      sudo python3 server/deploy/deploy.py service

  › 步骤 1-3 一条龙：sudo python3 server/deploy/deploy.py all。


▶ C. 接入内网代码仓 WebHook
────────────────────────────────────────────────────────────
  1. 仓库后台 → WebHook → URL 填 http://<服务器IP>:8080/
  2. Token 填共享密钥（= config.local.ini [secrets] webhook_secret），平台据此发 X-Devcloud-Token 头。
  3. 订阅事件：Push Hook。push 即触发评测。


▶ 触发与查看结果
────────────────────────────────────────────────────────────
push 代码 → 平台 POST webhook → 入队 → worker 串行 checkout+评测 → 存 sqlite。查看：

    浏览器:   http://<服务器IP>:8080/            # 任务列表/详情/日志（只读）
    命令行:   curl http://<服务器IP>:8080/tasks/<id>/log
    服务日志: journalctl -u ci-webhook -u ci-worker -f


▶ 开发端 MCP（接 opencode）查任务状态/日志
────────────────────────────────────────────────────────────
    CI_DB_PATH=/opt/ci/var/ci.db python3 local/mcp/ci_control_server.py

  › 工具：get_task_status / list_tasks / get_task_log。opencode 接入见 local/mcp/opencode.json.example。


▶ 端到端 demo（验证链路）
────────────────────────────────────────────────────────────
    python3 server/scheduler/smoke_scheduler.py   # 建临时仓 → 入队 → checkout → 编译 qsort+比对 → passed


▶ 命令速查
────────────────────────────────────────────────────────────
  远端 bootstrap  python3 local/admin/deploy_remote.py all
  服务器一键部署  sudo python3 server/deploy/deploy.py all
  环境自检        sudo python3 server/deploy/deploy.py check
  看服务状态      systemctl status ci-webhook ci-worker
  看任务(网页)    http://<host>:8080/
  端到端 demo     python3 server/scheduler/smoke_scheduler.py
  一致性检查      python3 checks/consistency.py
  重新生成本文件  python3 gen_quick_deploy.py

  › 仿真并发：1（单 worker 串行）。运行超时：120s。webhook 端口白名单：80-90/443/8080-8090。


▶ 卸载 / 重置（停服务 + 清数据）
────────────────────────────────────────────────────────────
    sudo systemctl disable --now ci-webhook ci-worker
    sudo rm -f /etc/systemd/system/ci-webhook.service /etc/systemd/system/ci-worker.service
    sudo systemctl daemon-reload
    rm -rf /opt/ci/var      # 删 sqlite/工作区/日志（谨慎，不可恢复）
