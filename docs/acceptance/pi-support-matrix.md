# Pi 支持与验收状态

## Spec 001：历史约定范围已完成

2026-09-24 用户明确将其他三平台实机及真实账号/服务验收移出 spec 001，未来另行处理。
本 spec 按 Linux x86_64 软件范围正常验收完成；依据见 [范围修订](../../specs/001-unify-pi-capabilities/scope-change-20260924.md)。

- Scope：`001-unify-pi-capabilities-linux-software` revision 1。
- 历史候选锁摘要：`9d6a927093f066c9428a5c193a636c4d73c5e64c946d24dc6a08185cf3f0dbf0`，recipe 与当次验收源码匹配；该值不是 Git commit。
- 四配方：pi-default、pi-managed、pi-codex、pi-cursor；mock/native 及每配方双路径冷重建。
- 正式结果：**81 passed / 0 failed / 0 not-run / 0 stale**，`check-release` rc 0，`release_approved=true`，仅适用于本 scope。
- 任务：**107/107 完成，另有原计划5项转出**，不称原112项测试全部通过。
- [关闭报告](pi-spec-closure-20260924/README.md)、[正式批准](pi-spec-closure-20260924/check-release.json)、[当前 scope](pi-spec-closure-20260924/scope.json)。

## 当前 checkout 与历史证据

2026-09-28 审查时，`locks/pi/manifest.json` 的 identity 已变为 `ade694a1f05c81670f58a9a56162e7d8b7ba48ba39ba1a859191064c976af2b3`，不同于上述历史候选。当前锁身份应直接读取该 manifest；后续源码修改也可能使运行包或执行身份变化。

历史 81/81 结果保留，不能据此宣称当前 checkout 已通过 native/cold 验证。新候选需重新取得与锁、源码、运行包、配方和平台匹配的证据；Python/TypeScript 隔离回归通过仅证明其测试范围。真实宿主、其他平台和账号验证按各自授权边界执行，未执行时保持未验证。

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
