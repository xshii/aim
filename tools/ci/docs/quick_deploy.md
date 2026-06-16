════════════════════════════════════════════════════════════
 Quick Deploy · CI 部署速查
════════════════════════════════════════════════════════════

  › 自动生成（gen_quick_deploy.py 依据 config.ini），改配置后重跑。

  › 部署两段式：首次执行机 SSH/SCP bootstrap（admin）→ 服务器本地跑 deploy.py（server）。


▶ 准备
────────────────────────────────────────────────────────────
  1. 非敏感配置填 config.ini：[server] host、[offline] deps_dir、(远端) [remote]、(webhook) [webhook]。
  2. 敏感项填 config.local.ini（复制 config.local.ini.example，不入仓）：[proxy] 代理、[secrets] 密钥。
  3. 离线依赖放到 <部署目录>/offline（deps_dir 留空时）（见 OFFLINE_DEPENDENCIES.md）；或 [fetch] mode=auto 经代理自动下载。


▶ 本期要点
────────────────────────────────────────────────────────────
  • 部署两段式：首次 SSH/SCP 远端 bootstrap（D-010），之后服务器本地直跑（D-008），日常 HTTP 触发。
  • GitLab 端口探测：从候选 8929,9080,9443,18080,28080 探测空闲端口锁定，避开被占用端口。
  • CI 验证预生成代码：多种验证（合一 check.py）+ 收集 output/状态；运行型仅超时(120s)+资源限制。
  • 凭证不入仓：私钥留 ~/.ssh；密钥/token/代理密码经 env 或 config.local.ini。


▶ A. 首次远端 bootstrap（在执行机上，新机首搭）
────────────────────────────────────────────────────────────
  › 当前 [remote] host = (未配置)，[fetch] mode = manual。host 为空表示不启用远端、直接看 B 段。

  A1  admin 连通性自检（SSH / 远端 python3 / GitLab）
      python3 local/admin/deploy_remote.py check
  A2  fetch=auto 时经代理下载依赖到本地 deps_dir
      python3 local/admin/deploy_remote.py fetch
  A3  SSH/SCP 推代码 + 依赖到远端 dest
      python3 local/admin/deploy_remote.py push
  A4  一条龙：check → fetch → push → 远程跑 deploy.py all（含装 GitLab + 全自动 Runner）
      python3 local/admin/deploy_remote.py all
      ↳ 经 ssh -tt 远程执行；装 GitLab 时在本地终端手输 root 密码（回车默认 88888888）


▶ B. 服务器本地部署（代码到位后在服务器上执行）
────────────────────────────────────────────────────────────
  1   环境自检（python3 / dpkg / 依赖）
      cd /opt/ci && python3 server/deploy/deploy.py check
  2   探测并锁定 GitLab 端口（写回 config）
      python3 server/deploy/deploy.py port
  3   离线装 GitLab，过程中交互手输 root 初始密码（回车默认 88888888，≥8 位）
      python3 server/deploy/deploy.py gitlab
  4   全自动注册 Runner，concurrent=1（gitlab-rails 建项目+签 token，GitLab 16+ 新流程）
      python3 server/deploy/deploy.py runner
      ↳ 手动 fallback：deploy.py runner --token <glrt->
  5   浏览器打开 http://<本机IP，部署时自动锁定>:<锁定端口>，用 root + 手输的密码登录（首登后尽快改密）
  6   推送含 .gitlab-ci.yml 的仓库，触发流水线（含 qsort 冒烟）

  › 步骤 1-4 可一条龙：python3 server/deploy/deploy.py all（= check + host + port + gitlab + runner）。


▶ 触发构建（webhook / token，HTTP 直连）
────────────────────────────────────────────────────────────
详见 server/webhook/README.md。git push 自动触发；或 curl + trigger token：

    curl -X POST -F token=<TRIGGER_TOKEN> -F ref=main \
      http://<本机IP，部署时自动锁定>:<port>/api/v4/projects/<id>/trigger/pipeline


▶ 开发端查 CI 状态 / 拉日志（MCP，接 opencode）
────────────────────────────────────────────────────────────
标准 MCP（stdio）local/mcp/ci_control_server.py 直连 GitLab API，凭证用环境变量：

    GITLAB_API=http://<本机IP，部署时自动锁定>:<port>/api/v4 GITLAB_TOKEN=<token> GITLAB_PROJECT=<id> \
      python3 local/mcp/ci_control_server.py

  › 工具：get_pipeline_status / list_pipelines / get_job_log。opencode 接入见 local/mcp/opencode.json.example。


▶ qsort 冒烟（验证 CI 真实可用）
────────────────────────────────────────────────────────────
    python3 server/demo/qsort/smoke_qsort.py     # 编译→限制运行→比对，期望 5/5 通过


▶ 命令速查
────────────────────────────────────────────────────────────
  远端连通性自检      python3 local/admin/deploy_remote.py check
  远端一键 bootstrap  python3 local/admin/deploy_remote.py all
  服务器自检          python3 server/deploy/deploy.py check
  探测端口            python3 server/deploy/deploy.py port
  看锁定端口          python3 server/deploy/probe_port.py --show
  服务器一键          python3 server/deploy/deploy.py all  # check+host+port+gitlab+runner
  注册 Runner         python3 server/deploy/deploy.py runner   # 全自动；--token glrt- 手动
  一致性检查          python3 checks/consistency.py
  重新生成本文件      python3 gen_quick_deploy.py

  › 仿真并发：1（串行）。运行超时：120s。GitLab 候选端口：8929,9080,9443,18080,28080。
