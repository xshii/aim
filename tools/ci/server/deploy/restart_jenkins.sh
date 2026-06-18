#!/usr/bin/env bash
# Jenkins 重启速记（省得记命令）。需 root。
# 用法：
#   sudo bash restart_jenkins.sh          # 重启 + 看状态
#   sudo bash restart_jenkins.sh reload   # 改过 systemd drop-in 后：先 daemon-reload 再重启
set -eu
[ "${1:-}" = reload ] && systemctl daemon-reload
systemctl restart jenkins
systemctl --no-pager status jenkins
