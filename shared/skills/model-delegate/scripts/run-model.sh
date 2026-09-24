#!/usr/bin/env bash
# V2唯一入口。执行器路径由显式实例的已部署记录与内容收据决定。
set -euo pipefail
umask 077
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${AGENTCFG_PYTHON:-python3}" -B -I "$script_dir/run-model.py" "$@"
