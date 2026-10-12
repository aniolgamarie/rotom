# Durable 模型调用身份的公开组合决定

状态：2026-10-06 root 设计决定。仅授权自有离线身份组件；未开放 Models 发送、Durable 服务、Full 或严格计量。输入为固定 durable 1.0.1、实际 Base chord/pi-ai 1.0.2 的已核验公开来源。

## 已有事实与采用的接缝

`HookApi.taskId` 和 `conversationId` 是公开的原生数字记录 ID，不能与 Rotom task/run/request ID 或 `SubmissionId` 混用。Chord 公开 `Context.abortSignal` 可读取。固定 Harness 先以 `withoutAbortSignal` 清除基础 signal，再为每个 task invocation 建立 controller scope，所以 generation `beforeRequest` 与 compaction `beforeCompact` 的 `context.abortSignal`，在该固定对象构造链上与 Models `options.signal` 是同一对象。一般嵌套 `withAbortSignal` 可以产生组合 signal；不能把这个固定调用链的结论扩展到所有 Context。

自有组件只通过上述公开 hook 与 Models 参数关联，不读取 scheduler 私有对象，不使用全局当前任务、prompt/message 哈希、模板字段或自定义请求 header 携带身份。SDK native ID 与 service/store/deployment/owner 作用域需要在下一层共同绑定；原生数字本身不证明权限。

## 第一批接口与不变量

在 `agents/pi/packages/durable-service/src/call-identity.ts` 提供 `createDurableCallIdentityBridge()`，返回固定generation/compaction hook容器、`take(signal,operation)`、`check(signal,operation,originalIdentity)`和`close()`。不导入或构造真实SDK、不访问存储、网络、账号或预算，不创建任务队列、持久attempt或任何授权。

hook 仅读取公开 API 的 task/conversation ID 和 Context signal，不访问请求消息、模型文本、entries、instructions 或 memo。捕获合法原生安全正整数及真正的 Node AbortSignal，拒绝缺失、伪造、Proxy、已中止信号和异常；错误固定且不带输入或 SDK 异常正文。Context 的公开 getter 可以读取，不能因一般数据入口拒绝 getter 而改用 SDK 私有字段。

内部 WeakMap 按 signal 对象保存一个待消费身份，`beforeRequest` 登记 generation，`beforeCompact` 登记 compaction；返回 undefined，不替换 SDK 消息或 compaction 决策。相同 signal 在待消费状态下重复 hook 不覆盖旧身份并失败。消费后下一次 hook 只允许同一 native task/conversation 与 kind；这些内存观察不构成新的 durable attempt，发送账本必须另行分配和持久化。跨 invocation 或进程恢复的 signal 不能按数值 ID 自动重建匹配。

固定 durable 的普通 hook 异常会被捕获并报告，之后仍可能调用 Models。因此任何 hook 验证失败（包括重复、冲突、非法或无法取得 signal）均退役整个桥接组件，抛出固定错误但不把 throw 当停止 SDK 的证据。Models 一侧的 `take()` 必须独立检查组件退役状态，即使旧 signal 留有待消费记录也不能再取得身份。这个保守失败范围只停止本桥接组件的新匹配；不表示其他 SDK 工作或进程物理结束。不能仅删除新失败的 key 或保留旧合法记录来绕过被吞掉的 hook 异常。

`take(signal, operation)` 只允许 generation 对 `streamSimple`、compaction 对 `completeSimple`，一次消费后不能再次用于派发。未登记、错误方法、已中止、冲突或已退役均失败；对已有 signal 的错误方法/身份冲突保留退役，不能通过下一次 hook 隐式修复。`fetchDeferred`、`cancelDeferred` 不具有对应 hook，明确 unsupported，不执行或猜测网络取消。`close()` 只退役本组件的内存接缝，不表示 SDK idle、任务终态、物理终止、清理完成或预算释放。

成功返回只含固定 schema、native task/conversation ID 和 call kind 的冻结观察对象。调用它不授权、不证明实际发送，也不生成账单/attemptId。未匹配或恢复的 deferred 调用须由服务保留 unknown/blocked，不自动补发、换 signal、换 provider 或清零预算。

异步Models准入在take后可能等待owner/SQLite；期间close、被SDK吞掉的另一hook错误、中止或同signal的下一hook会使旧调用失效。因此check仅读取当前记录和原生signal品牌，要求bridge/record仍有效、record已消费、operation对应kind且identity为take返回的**原同一对象**，成功返回exacttrue；它不重新arm、不消费新记录、不读取identity字段/body或授予权限。复制ID和值不能恢复旧调用。下一合法hook会替换原记录，所以无论其待消费或已消费，旧对象check均失败。wrapper每个派发前await的前后及最后同步入口都须重新check；已发生结果的迟到持久对账另行验证collector/store，不要求重新发送身份。

## Models 组合与后续门槛

公开 `Models.streamSimple` 同步返回事件流，不能改成 `Promise<Stream>`。未来 wrapper 可先返回公开工厂创建的自有 outer stream，再异步等待当前 owner、可信 conversation/task 映射、路由资格、累计预算及持久 sending gate，全部核验后调用原 Models 并转发。拒绝必须遵守终态 error event 协议。`completeSimple` 是 Promise，可以先等待 gate 再调用。这里仅记录已固定公开协议，不在身份组件中实现发送或错误流。

首次 SDK 模型请求无须假定 submit Promise 先返回 TaskId：可信控制面必须在提交前持久绑定 native conversation 与 service task；hook 提供实际 native TaskId，Models gate 再完成该 scope 下的持久 attempt 登记。该登记顺序、兼容恢复及未知发送的事务尚未实现，不把本设计当公开 SDK 已提供 fence。缺少当前映射时拒绝发送。

固定内建 DeepSeek 普通 OpenAI Completions SSE 静态路径无 deferred capability，配置 maxRetries=0 会关闭所见 pi-ai retry helper 和 SDK request retry 选项。仍需证明实际 selected route/公开 fetch/onPayload/认证与所有真正网络 attempt 的覆盖；不能凭这些选项签严格计量。其他 provider、后台协议、OAuth refresh 或同名替换版本独立资格验证，缺能力明确 unsupported/unverified。

## 验证

默认测试只运行自有组件和自有 hook API/Context/AbortController 替身，不导入 durable、Chord、pi-ai、SQLite 或第三方宿主。验证 generation/compaction、多任务交错、一次消费、重复/冲突、同 invocation 顺序请求、组合/替换 signal 不匹配、abort/close、字段类型和异常正文清理。请求内容用会抛错的属性哨兵，证明组件没有读取它；观察对象不含文本、模型参数、令牌、授权标签或持久 attempt。

替身通过仅说明身份组件的本地行为。固定 SDK 实际 hook/signal runtime、接缝覆盖、发送/账本事务、恢复、网络资格与 Full gate 另验；不勾 T078/T085。
