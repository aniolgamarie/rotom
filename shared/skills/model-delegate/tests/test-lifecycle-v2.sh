#!/usr/bin/env bash
# Popen与所有宿主均由pytest隔离夹具替换，不执行账号或模型。
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd -- "$repo"
exec "$repo/.venv/bin/python" -m pytest -q tests/test_model_delegate_lifecycle.py tests/test_model_delegate_cli.py tests/test_model_delegate_batch.py tests/test_model_delegate_codex_worker.py tests/test_pi_delegate.py
