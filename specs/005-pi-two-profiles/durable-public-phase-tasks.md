# 公开 TaskDefinition 的原处理函数转发与 phase 登记

本文件确定下一步自有组件的接口，不修改上游或已验收的 registry／hook bridge／Models 工厂。公开接口的静态可行性已有归档；该组件尚未实现或取得实际 SDK 资格，也没有选择新的产品 Reader。当前恢复路径的拒绝行为保留。

## 目标与公开边界

新增 `agents/pi/packages/durable-service/src/phase-tasks.ts` 及对应默认测试。仅通过根导出的原 `GenerationTask`、`CompactionTask`、`defineTask` 和公开 `Task.definition`、`TaskDefinition`、`PhaseHandler`、`RunningTask`、`TaskRuntime`、`Context` 工作。不得修改或冻结原 SDK 对象、调用私有 scheduler 方法、替换宿主函数、导入其私有模块，或改写原 handler 的输入与状态机。

新接口为 `createDurablePhaseTasks({durable, verifyCurrent})`，输入恰为这两个 own 数据字段。`durable` 来自受信固定公开 SDK；捕获其原 `defineTask` 方法与两个原 Task。`verifyCurrent` 以原 input 为 receiver，必须同步返回 `true`，但这个布尔值本身不提供 owner、用户授权、计量或发送资格。Promise 不准入；仅在所捕获 native Promise 结构仍匹配时安全观察本 realm 普通 Promise 的结果，避免原 rejected Promise 成为未处理拒绝。未知 thenable 不查看 then、getter 或调用代码。未知配置字段、Proxy、所需方法的 getter、源结构或方法漂移固定失败。返回冻结的自有 `{generationTask, compactionTask, bridge, check, close}`，仅供未来受信新 Reader／Models 工厂；业务客户端不能调用 phase 登记或指定 task ID。

构造不调用原 phase／initial／abort／migrate，不打开 Harness、SQLite、模型、业务根或进程。只调用恰两次捕获的公开 `defineTask`，以原 `durable` 为 receiver；返回 Task 必须是闭合 `{definition}`，其值为传入的自有原 definition。原 generation／compaction Task 的 name 分别为 `pi.generation`、`pi.compaction`，version 都为 1。完整公开 definition 仅允许 `name, version, initial, phases, abort` 和可选 `migrate, hooks`；**没有名为 input 或 checkpoint 的 definition 字段**。二者的输入／checkpoint 兼容是原函数与状态机语义的兼容。

## 完整转发与稳定来源

捕获原 definition 的完整 own 数据描述符、所有 phase 名称和原函数、initial／abort／可选 migrate，以及可选 hooks 的原引用和有界公开结构。所有 phase 都保留，不能只复制 request／summarize。该固定候选至少要求 generation 的 `request` 与 compaction 的 `summarize` 存在；阶段集合的增删、函数替换或对象结构漂移在后续检查中拒绝。

自有 definition 与 phases 容器冻结。每个 phase 恰调用一次捕获的原函数，receiver 为原 phases 对象，三个实参分别为原 task、原 runtime、原 Context；不克隆、不冻结、不添加字段。initial／abort／migrate 同样只转发一次，receiver 为原 definition，实参数目和值保持；hooks 保持原引用，SDK 对其原 handler receiver 的处理保持。所有这些入口，以及 verifyCurrent、defineTask、Context getter、原生 aborted getter／Promise then，都使用模块加载时捕获的原生 Reflect.apply 的局部裸调用；不能从原函数对象读取可写的 call／apply 属性来选择实际入口。函数引用相同不能证明其 call getter 未改写实际调用。不得为此冻结或修改 SDK 函数对象。转发得到的返回值或原异常继续交给调用方，不把原异常写进自有摘要或日志。对自有检查失败只产生固定错误码。

原 source 检查覆盖顶层输入描述符、公开 SDK 的所选成员、两个原 Task／definition／phase-map／函数及自有返回 token／definition。只检查已捕获的公开来源，不能证明任意恶意闭包内部状态。`check()` 先执行原 verifyCurrent，再完成不调用外来函数的原数据／方法复核。每个原函数入口前也完成这项最后纯复核，使 verifyCurrent 同步改变源后不能调用旧捕获函数。构造期间自有组件尚未 ready，defineTask 的回调提前执行传入 phase 时必须拒绝，零原 handler 调用。执行 verifyCurrent 或 Context getter 的同步检查期间使用私有 busy 边界；外层准入未完成前，对 check／phase／bridge 的同步重入不能放行原 handler 或消费登记。合法不同任务的异步并发仍允许。来源／配置或上述完整性检查失败永久关闭该自有组件。

## 以原 phase 调用为登记边界

仅 `generation.request` 和 `compaction.summarize` 的原 handler 调用期间建立登记。其他 phase、initial、abort、migrate 不登记发送身份。所有 phase 在取得 ready／同步 busy 边界并完成纯源前核后，必须先用纯 own／原生读捕获原 RunningTask 核心、原 runtime 三项字段和 Context abortSignal 的原描述符；该捕获不能执行 Context getter，且必须发生在 verifyCurrent 等外来代码之前。随后才调用原 verifyCurrent／原 Context getter，并在登记或原 handler 入口之前复核先前捕获的原身份／描述符与源。否则回调可同时修改 task.id 和 runtime.taskId，再把一致的新值伪装为原值。

phase 开始时必须核公开 RunningTask 的原 `id, conversationId, kind, version` 与原 runtime 的 `taskId, conversationId` 一致，`task.state.status` 为 running 且 `task.state.checkpoint.phase` 为当前转发入口；不读 input、消息或私有 runtime 字段来补造权限。任务与会话 ID 必须为正安全整数。

固定 SDK 的 runtime 恰有 `taskId, conversationId, signal` 三项所需 own 数据字段；本组件使用这些公开字段的原描述符，拒绝 getter 替身，不虚构 runtime.kind／version。原 signal 必须是未 aborted 的原生 AbortSignal。原 Context 的公开 `abortSignal` 允许 SDK 的公开 getter，但读取结果必须是同一原 signal；读取之后再次进行纯源／身份／原生 aborted 核对。不能从传入的字符串、复制 signal、客户端 task ID 或原 SDK attempt 猜身份。

同一个 scheduler invocation 可以在多个 phase 中复用同一 runtime、Context 和 signal，不能把 signal 当作唯一模型调用编号。每次目标 phase 建立一个不同的自有私有 lease 与冻结四字段 identity：`{schema:1, nativeTaskId, nativeConversationId, call_kind}`。identity 仅关联原 phase 调用，既不是永久 attemptId，也不是发送序号或用户授权。lease 不在返回接口中暴露。

同一 signal 的目标 phase 只能顺序登记：旧 lease 已退出，且复用时必须仍是原 runtime／Context、原任务 ID／会话 ID／kind／version。SDK 每次 commit 后可提供新的 RunningTask record 对象，跨 phase 不要求同 record 引用；每个 lease 只保留本次原 task 引用用于身份核验。并发或重入目标 phase、同 signal 换 runtime／Context／任务属于关联完整性失败，拒绝并永久关闭组件。正常取消只永久退役该 signal 的登记，不能关闭其他任务的合法 signal；关闭后的登记全部拒绝。不同原 signal 的合法 phase 可以并行。新的顺序 lease 不会使旧 identity 复活；迟到 Models 准入必须因原 identity 不再是当前 lease 而失败。

`bridge` 恰提供冻结的 `take(signal, operation)` 与 `check(signal, operation, identity)`，兼容现有 Models 门面所用 ABI。take 仅在当前活跃 lease 中消费一次；generation 只匹配 streamSimple，compaction 只匹配 completeSimple。返回原冻结 identity，不复制。check 要求同一原 signal、当前活跃且已消费的同一 identity 对象以及正确 operation，并复核当前原 phase 来源与身份。未匹配／已消费／已退出／旧 identity／错误 operation 都拒绝；不提供 deferred 或其他发送路径。错误 operation 或重复 take 退役当前 lease，正常取消退役该 signal；迟到旧 identity 的 check 只拒绝该旧调用，不得退役新的合法 lease。只有源／配置漂移或前述关联完整性失败才永久关闭整个组件，保留其他任务继续工作的边界。

原 phase promise resolve／reject 都在 finally 中退出相应 lease，未消费 lease 也不能留给以后发送。退出不调用模型、账本或 SDK，不释放预算、不制造结果或终止证明；幂等清理不能覆盖原 handler 异常。原 handler 仍在运行时 close 只封闭自有登记与新入口，不宣称 SDK 或网络物理停止。关闭后的迟到原结果是否可记录，继续由既有 Models resultFacts／store 独立资格判断，本组件不拒绝合法旧事实或重新授权。

## 不放宽永久发送与恢复语义

此组件最多证明所选原 phase 给出的身份。实际发送仍在唯一 Models 门面中执行原请求捕获、严格授权、prepare、持久 sending、最后同步核对和原入口；原模型参数不由 phase wrapper 增删。永久 attempt 与调用意图由控制面分配，不以 phase 次数、Task ID、SDK attempt、signal、输入 hash 或新 lease 自动授权。

旧发送 unknown、持久回执未知或旧预算预留未对账时，后续 retry／recovery 即使取得新的 phase 身份也必须被授权层拒绝；明确的新有界授权仍须保留原 unknown 预留。该组件不实现退款、恢复接管、取消确认、自动补发或计量。尚未完成的控制面和实际 SDK 验收继续开放。

未来新 Reader 必须在构造时固定选择这两个稳定自有 Task token，完整保留原其他 task／tools／extension／section 查找与源检查；不通过默认 registry.install 重注册 builtin，也不热换正在运行的 Reader。旧 factory 与旧 hooks 不加入这条 phase 登记链，避免双登记。上述 Reader／Models 接线另列阶段，本组件通过默认检查不表示它们已实现。

## 有界默认检查与后续真实资格

默认测试使用原生自有 AbortController、纯 fake 公开 Task／runtime／Context、fake defineTask 与原处理函数，沿用现有 tmp HOME／XDG／断网／进程 guard；不导入或启动 SDK、第三方宿主、SQLite、真实进程或模型。直接执行自有 phase wrapper 和 bridge，覆盖原 receiver／实参／一次转发，完整 phase／initial／abort／migrate／hooks，两个不同 signal 并行，同 signal 顺序新 identity、未消费退出、重复消费、重入／重叠、错误关联／operation、取消／close 与迟到旧 identity。取消一个 signal、错 operation 或旧 identity check 均需验证其他合法 task 不受影响，旧 identity 也不能关闭新的顺序 lease。

source／verifyCurrent／Context getter 同步漂移的具体回归要求零原 handler 调用或零后续 bridge 消费，尤其要覆盖首次目标及非目标 phase 在 verifyCurrent 中被一致修改的原 ID／signal／Context 描述符。函数自身 call／apply 属性或 getter 被替换时，真实原函数、receiver、参数仍须恰调用一次，替代 spy／getter 零调用；原校验函数返回 false 不能被其 own call 伪造成 true。phase resolve／reject 均清理，旧原异常不被清理覆盖。不能只测试复制后的期望对象或手动登记伪 hook。原 bridge／registry／provider 文件不改，其既有全量默认测试无需在没有受影响变更时反复执行；新增测试由 `node scripts/test-pi-mock.mjs agents/pi/packages/durable-service/tests/phase-tasks.test.ts` 运行并单独记录。

写入完成后先验收稳定 diff 与独立定点复审。以后真实公开 SDK 资格必须验证新的固定 Reader 选中了这些原转发 handlers，以及初次／同 invocation 多 phase／retry／恢复 summarize／后台 compaction 的实际 Models 入口；准备具体断网合成材料后按独立授权执行。公开静态源码和 fake wrapper 默认通过都不能替代上述运行证据或 T086／Full 验收。
