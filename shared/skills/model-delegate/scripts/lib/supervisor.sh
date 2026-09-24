#!/usr/bin/env bash
# V2控制客户端；进程/路由/凭据/证据实现统一在冻结的agentcfg运行包中。
md_delegate_call() {
  local runner
  runner="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/run-model.sh"
  "$runner" "$@"
}

md_start() { md_delegate_call start "$@"; }
md_status() { md_delegate_call status "$@"; }
md_cancel() { md_delegate_call cancel "$@"; }
