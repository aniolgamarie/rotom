#!/usr/bin/env bash
# 默认仅执行仓库隔离测试；旧V1测试保留为来源资料。
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd -- "$repo"
exec "$repo/.venv/bin/python" -m pytest -q tests/test_model_delegate_contract.py tests/test_model_delegate_context.py tests/test_model_delegate_backends.py tests/test_pi_delegate_retirement.py
