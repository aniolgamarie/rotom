#!/usr/bin/env bash
# V2控制客户端；进程/路由/凭据/证据实现统一在冻结的agentcfg运行包中。
md_delegate_call() {
  local runner
  runner="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/run-model.sh"
  "$runner" "$@"
}

backend_probe() { md_delegate_call probe --backend codex "$@"; }
backend_start() { md_delegate_call start --backend codex "$@"; }
backend_resume() { md_delegate_call resume --backend codex "$@"; }
backend_cancel() { md_delegate_call cancel --backend codex "$@"; }
backend_status() { md_delegate_call status --backend codex "$@"; }
