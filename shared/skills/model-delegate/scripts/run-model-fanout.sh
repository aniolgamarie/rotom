#!/usr/bin/env bash
# 只提交显式批次给已存在的Pi管理者，不自行fork执行器。
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${AGENTCFG_PYTHON:-python3}" -B -I "$script_dir/run-model.py" --batch-client "$@"
