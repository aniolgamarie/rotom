#!/usr/bin/env bash
# V2控制客户端；进程/路由/凭据/证据实现统一在冻结的agentcfg运行包中。
md_delegate_call() {
  local runner
  runner="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/run-model.sh"
  "$runner" "$@"
}

md_poll() { md_delegate_call poll "$@"; }
md_wait() { md_delegate_call wait "$@"; }
md_resume() { md_delegate_call resume "$@"; }
