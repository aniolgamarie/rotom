# 私有异步工具请求引用

公开 SDK 的 `tool_call` 和 `ToolDefinition.execute(toolCallId, params, signal, onUpdate, ctx)` 使用同一个 `toolCall.id`。事件 handler 会被 await，但其 input 可被后续扩展修改；实际准入必须在自有 execute 内捕获最终参数，再等待私有请求分配，并将原 id、同一捕获输入和引用绑定到同一 PreparedOperation。此结论来自固定公开源码，不证明当前 SDK 的 ALS 传播或产品持久 RPC 已通过。

`confirmed-intent-scope.ts` 现要求恰好一个私有请求分配器：原 `allocateRequest` 或新 `allocateRequestAsync`。同步模式保留 `bindingForTool()`；异步模式使用 `bindingForToolAsync()`，等待后只返回冻结的 session_scope / intent_ref / request_ref 或 null。跨模式方法返回 null，不调用另一个分配器。异步 toolCallId 严格匹配持久 Store 的 ASCII `[!-~]{1,512}`，允许嵌套斜杠；同步模式原有规则保留。

每次调用先核验 active、submitAccepted、running、原 ALS、当前配置和双时钟。同一原 scope 的 pending Map 在可信 callback 前占槽，同 ID 并发共享一次分配，已成功 ID 复用同一冻结绑定。pending 加 memo 共同受 maxRequests 限制；没有淘汰、失败重试或新 ID 替代旧 ID。callback 只取得冻结的 session_scope / intent_ref / tool_call_id，不取得目标正文、认证或执行回调；返回值必须是非 Proxy 的原生 Promise，不调用 thenable getter。异常、拒绝、非法引用均使原 scope 失败退役。

scope 的 stopped 会让等待及时返回 null；迟到 resolve / reject 不恢复能力。每次 await 后复核原 scope、ALS、phase、submit 接受门和全部 current / 时钟字段。内存退役不证明后端分配物理取消，也不证明持久墓碑已写；真实异步适配器必须自身有界、原子核验 authority 与持久退役，未知结果保留待恢复状态。可信 callback 不得重入控制器或等待模型。

同 ID 的分配幂等只保证一个 request_ref，不保证一个下游操作。产品还须在原 admission 账本中把引用、最终输入、operation_id / operation_digest 绑定，并阻止同 scope / ID 重复 execute 签发新操作。不同 ID 和嵌套 ID 可以取得不同引用，后续预算、同意图拒绝锁及 Writer 竞争仍由原账户和执行契约处理。当前人工 admission 仍生成随机引用，尚未接此私有能力；不增加可由模型提交 refs 的参数或 RPC。

新增39项和原87项在一次默认组合中126通过，稳定两文件独立审查无剩余P1/P2。旧同步模式拒绝 Promise 分配器的行为红单独保留。测试只使用自有回调与 ALS，不执行 SDK、RPC、进程、账号或持久文件。证据归档为 `risk-intent-async-request`，不是持久映射、终止或产品 Full 通过；正式任务仍7/100。

原官方 intent SDK10 review01 明确固定了旧自有文件 SHA `616b21c2137c88be54286a9e33b4febbed8f901bd2bc865acda983fecbee7391`。当前异步接口 SHA 为 `395fa8fe8c564542e73f515c2a1c0fe1d6690f6c6fe72c2ae7551ceaaf592376`，因此旧组合材料已失效并保留历史。固定官方 SDK 文件没有被修改；它们的静态证据不能代替新自有代码/SDK 组合验证。重新准备与授权范围见 [native-intent-scope-probe.md](native-intent-scope-probe.md)。
