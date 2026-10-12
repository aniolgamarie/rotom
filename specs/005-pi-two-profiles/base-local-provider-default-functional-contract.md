# Base 本地提供者默认功能验证

2026-10-09 root 子包，依据已停止写入的 `base-provider-followup-functional-verification-evidence-review01` 与 `base-provider-existing-test-harness-evidence-review01`。仅补默认 fake API 功能检查，不加载官方 SDK，不证明真实 UI、会话持久化或正式 host support。当前四场 SDK 注册探针的计划与守卫不变。

唯一代码写入者可改 `tests/fixtures/pi/mock-guard.mjs`，并新增 `agents/pi/runtime/tests/base-local-providers.test.ts`。`scripts/test-pi-mock.mjs` 与全部生产插件、upstream/vendor、包清单保持只读，特别不能给 `todo-vendor` 打源码补丁。复用真正的入口和公开自有 factory/helper；假对象只替代测试中的 Pi/UI/overlay peer，不能复制业务实现来制造通过。

2026-10-09 默认运行增量：固定四文件已实际进入全部业务测试，新八项功能检查及配置回归通过。现有 `mock-boundaries.test.mjs` 的拒写负例只预期 Node 权限模式的 `ERR_ACCESS_DENIED`，当前 bwrap 只读挂载实际返回 `EROFS`。root 允许唯一 writer 仅修改该测试的拒写断言与必要读取 import：精确接受这两个拒绝码，写前/拒绝后同一自有目标字节必须一致；其他错误仍失败。不改 guard、脚本、FS/网络/进程保护，不 fake 错误，也不扩 provider stub。保留原失败，只重跑这个受影响模块，报告跨轮覆盖而非同次全绿。

## 最小功能范围

1. Footer：在合成 footer/session/turn 数据下触发已注册回调和命令，检查输出中的关键状态及自有监听器 shutdown 清理。不要断言真实 TUI 位置、主题或实际 Git 行为。
2. Loop Guard：固定配置和时间，通过真实安装 helper 与捕获的 handlers 验证重复工具行为的允许/阻断边界；检查真实 checkpoint 经 fake `appendEntry` 输出，再从合成 branch 恢复。覆盖超出真实 `checkpointScanLimit`、错误 customType/version 或未关联结果等不兼容恢复负例；恢复接口没有 wallclock TTL/now，不创造时间过期语义。没有 session_shutdown handler，不能创造一个来通过。
3. Todo：用 fake 注册工具与 session branch 验证真实 reducer/tool response 的增改行为、`details` 重放、不同 session 的槽隔离和 shutdown 驱逐；用显式 `importOverlay` seam 提供 fake widget，不加载实际 overlay/TUI。
4. Todo timer：控制 2 秒 prewarm timer；分别观察 shutdown 前后触发，验证实际允许的 import 与 UI/widget 效果。源码没有取消 timer，不要把“shutdown 取消 prewarm”写成期望或通过。若实际迟到回调有功能问题，保留失败并交 root，不修改 upstream/vendor 代码绕过。

不要重复现有纯配置/helper suite 的业务断言；可作为 mock 接线变更的必要回归运行。每项输入为合成固定值，无真实账户、模型请求、git/外部子进程或业务根。

## 测试解析边界

对三个本地 provider 的已知入口/子模块，mock guard 可增加精确 parentURL 范围的 `pi-tui` 和 `pi-ai` 自有假导出，以及 `todo-vendor` 相对 `.js` 到实际 `.ts` 的有界映射。既有包拒绝、网络、子进程和路径保护不得放松；未知 peer/parent 继续拒绝。`@agentcfg/pi-runtime` 保持用仓库自有真实 helper，不能用 fake helper 绕过 manager/选定能力检查。默认 fake SDK 导出不变成原生版本观察或官方实现。

先保存 guard 即时前像，写真实功能测试并保留首次失败，再仅补最小测试解析与 fixture。最终通过后停止写入，保存稳定 diff/pins/报告并独立复核。固定验收命令为 `node scripts/test-pi-mock.mjs agents/pi/runtime/tests/base-local-providers.test.ts agents/pi/runtime/tests/plugin-policy.test.ts agents/pi/runtime/tests/todo-config.test.ts tests/fixtures/pi/mock-boundaries.test.mjs`，使用已固定 Node v24.14.0 和现有临时 HOME/断网 fake harness。必要时仅为正确 owner/ns 视图使用固定测试命令的工具审查，不转换为第三方宿主 smoke。

任务记录区分完成、进行中、失败待决策、环境不足未验证。真实来源/接口前提推翻、需要生产代码变更或更宽解析、两次有效修复仍失败时由 root 决策。正式 8/100、AUTO OFF、原生四场等待独立授权。
