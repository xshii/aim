════════════════════════════════════════════════════════════
 Quick Deploy · Jenkins CI（.deb 离线）
════════════════════════════════════════════════════════════

  › 自动生成（gen_quick_deploy.py 依据 config.ini），改配置后重跑。

  › CI 框架=Jenkins（.deb apt 安装）：webhook 适配器校验 token → 调 Jenkins buildWithParameters；Jenkins(JCasC 预配) 跑 qsort 功能+性能评测；官方 MCP 插件接 opencode。代码托管仍用内网现有仓库。


▶ 准备
────────────────────────────────────────────────────────────
  1. 有网机：跑 local/admin/fetch_offline.py 产出离线件到 tools/ci/local/offline/（jenkins_2.555.1_all.deb + plugin-cli jar + Java21 的 .deb）。
  2. config.ini 客户端：[fetch]（版本/URL）、[remote]（远端 bootstrap）。
  3. config.ini 服务端：[jenkins]（端口/job/admin/内源 UC）、[offline] deps_dir、[webhook] listen、[limits]。
  4. config.local.ini（不入仓）：[secrets] webhook_secret + jenkins_admin_password。
  5. 代码托管用内网现有仓库（不新建）；仓库后台配 WebHook 指向 webhook 适配器（见 C 段）。


▶ 本期要点
────────────────────────────────────────────────────────────
  • 组件：webhook 适配器(触发) + Jenkins(.deb，JCasC 预配 job/串行/auto-cancel) + 官方 MCP 插件。
  • 仿真串行：numExecutors=1（固定，D-003；单节点同一时刻仅 1 个构建 = License 数）。
  • Jenkins 端口 8080、webhook 端口 8090，均仅限 80-90 / 443 / 8080-8090；认证头 X-Devcloud-Token。
  • 离线：jenkins/java 的 .deb apt 安装；插件由服务器从内源 UC 装；JCasC 配置即代码；凭证不入仓。git_auth=ssh。


▶ 离线件获取（有网机，一次性）
────────────────────────────────────────────────────────────
  F1  改 config.ini [fetch] 版本/URL 为内网可下版本，下 .deb + plugin-cli jar
      python3 local/admin/fetch_offline.py
      ↳ 走代理：export HTTPS_PROXY=...
  F2  Java：把 JDK/JRE 21 的 .deb 放进 tools/ci/local/offline/（[fetch] java_deb_url 为空时手动放）
  F3  产出在 tools/ci/local/offline/（大文件已 .gitignore），随 bootstrap 推送或手动放到 deps_dir=/opt/ci/local/offline


▶ A. 首次远端 bootstrap（在执行机上，可选）
────────────────────────────────────────────────────────────
  › 当前 [remote] host = (未配置)。host 为空 = 不用远端，直接在服务器跑 B 段。

  A1  admin 连通性自检（SSH / 远端 python3 / 管理员权限）
      python3 local/admin/deploy_remote.py check
  A2  SSH/SCP 推代码 + offline/ 到远端 /opt/ci
      python3 local/admin/deploy_remote.py push
  A3  一条龙：check → push → 远程跑 deploy.py all
      python3 local/admin/deploy_remote.py all
      ↳ 非 root 用户经 ssh -tt 交互输 sudo 密码


▶ B. 服务器本地部署（需 root）
────────────────────────────────────────────────────────────
  1   环境自检（root / apt-get / dpkg / 端口范围 / 离线 .deb 就位）
      sudo python3 server/deploy/deploy.py check
  2   apt 装 jenkins/java 的 .deb + 从内源 UC 装插件 + 渲染 JCasC
      sudo python3 server/deploy/deploy.py init
  3   写密钥环境文件 + Jenkins systemd drop-in + 启用 jenkins/ci-webhook
      sudo python3 server/deploy/deploy.py service

  › 步骤 1-3 一条龙：sudo python3 server/deploy/deploy.py all。


▶ C. 接入内网代码仓 WebHook
────────────────────────────────────────────────────────────
  1. 仓库后台 → WebHook → URL 填 http://<服务器IP>:8090/（webhook 适配器，非 Jenkins 端口）
  2. Token 填共享密钥（= config.local.ini [secrets] webhook_secret），平台据此发 X-Devcloud-Token 头。
  3. 订阅事件：Push Hook。push 即触发 Jenkins job=qsort-eval 评测。


▶ 触发与查看结果
────────────────────────────────────────────────────────────
push → 适配器校验 token+解析 payload → Jenkins buildWithParameters(GIT_URL/GIT_SHA/BRANCH)。查看：

    Jenkins UI: http://<服务器IP>:8080/            # 构建列表/控制台日志/产物（admin 登录）
    适配器日志: journalctl -u ci-webhook -f
    Jenkins 日志: journalctl -u jenkins -f


▶ 开发端 MCP（官方 mcp-server 插件，接 opencode）
────────────────────────────────────────────────────────────
  › Jenkins 装 mcp-server 插件后自带 MCP 端点，无需自写。opencode 接入见 local/mcp/opencode.json.example。

    MCP 端点: http://<服务器IP>:8080/mcp-server/   # 用 admin + API token 认证


▶ 本机可验项（无需真 Jenkins）
────────────────────────────────────────────────────────────
    python3 server/demo/qsort/eval.py server/demo/qsort   # qsort 功能+性能评测
    python3 server/webhook/test_receiver.py               # 适配器单测（mock Jenkins）
    python3 checks/consistency.py                          # spec↔代码 一致性闸门


▶ 命令速查
────────────────────────────────────────────────────────────
  有网机下离线件  python3 local/admin/fetch_offline.py
  远端 bootstrap  python3 local/admin/deploy_remote.py all
  服务器一键部署  sudo python3 server/deploy/deploy.py all
  环境自检        sudo python3 server/deploy/deploy.py check
  看服务状态      systemctl status jenkins ci-webhook
  Jenkins UI      http://<host>:8080/
  一致性检查      python3 checks/consistency.py
  重新生成本文件  python3 gen_quick_deploy.py

  › 仿真并发：numExecutors=1（串行，D-003）。admin 用户：admin。端口白名单：80-90/443/8080-8090。


▶ 卸载 / 重置（停服务 + 清数据）
────────────────────────────────────────────────────────────
    sudo systemctl disable --now jenkins ci-webhook
    sudo apt-get remove --purge -y jenkins                    # 卸 Jenkins（含 jenkins.service）
    sudo rm -f /etc/systemd/system/ci-webhook.service /etc/ci-jenkins.env
    sudo rm -rf /etc/systemd/system/jenkins.service.d         # 删端口/JCasC drop-in
    sudo systemctl daemon-reload
    sudo rm -rf /var/lib/jenkins                              # 删 JENKINS_HOME（谨慎，不可恢复）
