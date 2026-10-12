#!/bin/bash
# 可信固定脚本在项目根外；默认不执行外部工具。
set -euo pipefail
if [[ $# -lt 1 || "$1" != "--run" ]]; then
  printf '%s\n' 'DAILY_EXECUTION_NOT_ENABLED' >&2
  exit 2
fi
shift
if [[ $# -ne 3 || ! "$2" =~ ^/tmp/.+ || "$2" == *'/../'* || "$2" == *'/./'* ]]; then
  printf '%s\n' 'DAILY_ARGUMENTS' >&2
  exit 2
fi
mode="$1"
project_root="$2"
editor="$3"
# 根与build/private-home的nofollow检查由外部可信checker完成。
cd -- "$project_root"
case "$mode" in
  shell)
    printf '%s\n' gamma alpha beta | LC_ALL=C sort > build/shell-lines.txt
    cat -- build/shell-lines.txt
    ;;
  editor)
    "$editor" --headless --clean -u NONE -U NONE -i NONE --noplugin -n \
      --cmd 'set noswapfile nobackup nowritebackup' \
      editor-note.txt -c '%s/visibility: pending/visibility: checked/' -c 'write' -c 'qa!'
    ;;
  *) printf '%s\n' 'DAILY_ARGUMENTS' >&2; exit 2 ;;
esac
