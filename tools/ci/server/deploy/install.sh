#!/usr/bin/env bash
# 装 Jenkins/Java 的离线 .deb（apt 本地装，自动解依赖）。需 root。
# 插件 / JCasC / systemd 等其余步骤手动操作（或用 deploy.py）。
# 用法：sudo bash install.sh [deps_dir]      # deps_dir 默认 /opt/ci/local/offline
set -eu
DEPS="${1:-/opt/ci/local/offline}"
debs=("$DEPS"/*.deb)
[ -e "${debs[0]}" ] || { echo "没找到 .deb 于 $DEPS"; exit 1; }
DEBIAN_FRONTEND=noninteractive apt-get install -y "${debs[@]}"
