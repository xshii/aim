#!/usr/bin/env bash
# Jenkins 日志/状态速查（封住几条容易忘的 journalctl/systemctl 参数）。日志可能需 sudo 才看得到。
# 用法：
#   bash showlog.sh           # 最近 100 行（默认）
#   bash showlog.sh 300       # 最近 300 行
#   bash showlog.sh follow    # 实时跟踪（journalctl -u jenkins -f）
#   bash showlog.sh status    # 服务状态（systemctl status）
#   bash showlog.sh today     # 今天的日志
#   bash showlog.sh error     # 只挑 WARNING/SEVERE/error/exception 行
set -u
UNIT=jenkins

case "${1:-100}" in
  follow|-f)   exec journalctl -u "$UNIT" -f ;;
  status)      exec systemctl --no-pager status "$UNIT" ;;
  today)       exec journalctl -u "$UNIT" --since today --no-pager ;;
  error|err)   journalctl -u "$UNIT" --no-pager | grep -iE 'WARNING|SEVERE|error|exception' ;;
  *[!0-9]*)    echo "用法: showlog.sh [<行数,默认100>|follow|status|today|error]"; exit 2 ;;
  *)           exec journalctl -u "$UNIT" -n "$1" --no-pager ;;
esac
