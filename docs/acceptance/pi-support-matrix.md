# Pi 支持与验收状态

## 当前 spec：已完成

2026-09-24 用户明确将其他三平台实机及真实账号/服务验收移出 spec 001，未来另行处理。
本 spec 按 Linux x86_64 软件范围正常验收完成；依据见 [范围修订](../../specs/001-unify-pi-capabilities/scope-change-20260924.md)。

- Scope：`001-unify-pi-capabilities-linux-software` revision 1。
- 候选：`9d6a927093f066c9428a5c193a636c4d73c5e64c946d24dc6a08185cf3f0dbf0`，recipe 与当前运行源码匹配。
- 四配方：pi-default、pi-managed、pi-codex、pi-cursor；mock/native 及每配方双路径冷重建。
- 正式结果：**81 passed / 0 failed / 0 not-run / 0 stale**，`check-release` rc 0，`release_approved=true`，仅适用于本 scope。
- 任务：**107/107 完成，另有原计划5项转出**，不称原112项测试全部通过。
- [关闭报告](pi-spec-closure-20260924/README.md)、[正式批准](pi-spec-closure-20260924/check-release.json)、[当前 scope](pi-spec-closure-20260924/scope.json)。

## 完整能力与平台事实：保留未验证项

原 `001-unify-pi-capabilities` revision 2 的 364 项范围未改，仍为 81 passed / 283 not-run，`release_approved=false`。
以下表格表示旧完整范围的执行事实，不是当前 spec 未完成工作量：

| 平台 | 引擎 | passed | failed | not-run | stale | not-selected |
|---|---|---:|---:|---:|---:|---:|
| darwin-arm64 | bun | 0 | 0 | 21 | 0 | 0 |
| darwin-arm64 | node | 0 | 0 | 70 | 0 | 0 |
| darwin-x86_64 | bun | 0 | 0 | 21 | 0 | 0 |
| darwin-x86_64 | node | 0 | 0 | 70 | 0 | 0 |
| linux-arm64 | bun | 0 | 0 | 21 | 0 | 0 |
| linux-arm64 | node | 0 | 0 | 70 | 0 | 0 |
| linux-x86_64 | bun | 20 | 0 | 1 | 0 | 0 |
| linux-x86_64 | node | 61 | 0 | 9 | 0 | 0 |

其他三个平台尚未原生验证；Linux 的10项真实账号/服务 live 同样未执行。
Codex、Cursor、MCP、web、代理、终端的后续验证意图保留，不因移出 spec 改成 not-selected。
后续工作见 [独立清单](../follow-ups/pi-platform-and-live-validation.md)。

Codex 保留官方 CLI；系统／受管配置和组织或未知账号无法核验时仍拒绝执行。此次范围修订不修改运行保护或扩大支持声明。

原始证据归档 [pi-cold-9d6a9270](pi-cold-9d6a9270/index.json) 保持不变；其他历史候选不继承为本候选通过。
