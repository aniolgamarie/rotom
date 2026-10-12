# 公开 SDK simple 请求的有界输出缺省（草稿，待来源与设计复审）

固定 SDK 的 generation 通过公开 settings.stream 构造原 simple options，没有声明或发送 maxTokens；既有自有 Provider 要求 maxTokens 显式存在，因而安全拒绝这条路径。不能在未声明的 SDK 设置中偷偷添加字段、手写 checkpoint 冒称初始 generation、修改上游，或从缺省推导发送权限。本稿只决定自有模型适配层的参数转换，未授权按草稿实施。

拟新增显式自有入口 `createDurableSdkSimpleModelDispatch(input)`，输入仍是原八字段 models／ai／bridge／store／model／authorize／resultFacts／limits，输出仍是冻结的 models／close；不得增设客户端 mode、默认 cap、grant 或第九配置字段。原 `createDurableModelDispatch` 保持显式 maxTokens 契约，旧 readonly／hook Models 工厂保持原入口。新 phase Models 工厂在本增量稳定接受后才切换这一自有入口。

自有 Provider 复用同一内部算法，仅为新入口启用缺省策略：构造时从已捕获原 model 的公开 maxTokens 纯复制有限正安全整数，缺失、undefined、零、负数、非整数或 getter／Proxy 均失败；不调用 Models.getModel、authorize 或模型。这个值只是 Models simple 参数层的有界选值，不是可用预算、真实输出或 input_tokens 上界；官方 provider helper 后续可按上下文、thinking budget调整，不能声称所有 provider 的实际输出或账单硬上界。原 model 的完整有界规范值核、parent source 图以及原方法核保持，不冒称旧 Provider 已核所有属性标志。

新入口只允许 options.maxTokens 字段真正缺省时，以该已固定上限填入自有规范请求。显式值仍执行原正安全整数校验，显式 undefined 不当作缺省，不改已有 cap。signal、maxRetries=0、transport=sse 仍必须显式合格；未知字段、getter／Proxy 和不合格可选值仍失败，不静默修复 retry、transport 或 reasoning。不扩大 Context／Model JSON 范围，不丢弃可选 undefined；选择的服务公开设置与 metadata 必须自身符合既有输入契约。

转换必须在原 Provider 的 options 解析中完成，capture 和每次 alive 都用同一固定缺省重读原 options 对象；不得先复制给一层门面后遗失原参数在 await 期间的变化检测。原 model／Context／options 的有界规范请求仍构成 requestKey。规范 envelope 的 options.maxTokens 显式包含交给原 Models simple 入口的选值，原三次 authorize 必须审查相同 envelope；拒绝或预算不足仍零底层模型入口。账本 prepare→sending→result→settled、原 committedNow、unknown 占用、局部 identity 拒绝及关闭后独立事实链全部不变。

新入口还在首次 bridge／Context／外来回调之前纯捕获原 options 的完整有序 own keys、prototype、各 own data descriptor 及原值引用；它们只限既有 OPTIONS 白名单，signal 仅保留原引用，不遍历其私有图。每次 alive 在原 bridge／Context getter 之后、交出模型入口之前纯复核这个绑定，并重读原规范请求。maxTokens 真正缺省也是原绑定的一部分；缺省变成 own 同 cap、own cap 删除后又落到同缺省、其他属性标志／key 顺序／prototype 或原引用变化都拒绝，不能靠规范 JSON 恰相同放行。仅新命名入口增加此原绑定；旧严格入口的既有 canonical 行为不扩大。

stream 入口的首个外来调用也包括原 ai.createAssistantMessageEventStream：先纯捕获原绑定，合法时原 factory 恰调用一次，返回后立即纯复核该绑定，才可进入原 capture／bridge.take 与 admission。complete 不调用这个 factory，但同样在任何外来调用前固定绑定。初始绑定非法时不得等 factory 回调后重建 baseline；为保持原合成错误 stream 类型，只可调用原 factory 至多一次并返回固定拒绝，bridge／authorize／store／Models 均零调用。合法绑定在 factory 内漂移时也在 bridge.take 前拒绝，不新增 stream 分配或重试。

底层原 Models receiver、model／Context 的既有有界复制语义、原 signal 及其他选定 options 值不变。新的区别只有合法缺省变为显式有限 maxTokens；它不声称逐字保留原 SDK options，也不把公开 Model 元数据当授权。provider 最后 alive 与原模型入口继续相邻，不在中间执行新的外来回调。

默认增量仅涉及自有 provider、新增 sdk-simple-dispatch 默认测试及新 phase 工厂一处入口选择和必要组合回归。不得改 phase Task／Reader、SDK、账本／持久化算法或原测试断言。旧 Provider 完整原断言和旧六／七字段工厂保持；新增 fake 用原缺省 options 驱动 stream／complete、检查规范上限和三次原 authorize／sending ACK／ModelEntry；显式 cap 保留、原严格入口缺省仍拒绝、不合格 fixed metadata、own undefined、unknown/getter／Proxy、await 前后原 options／model 漂移均零新增发送。原源码与真实失败按实际运行留存，不制造缺新 API 红。受影响组合回归独立记录，不以多个 execution 拼同次总数。

原参数绑定的默认反例须覆盖两个规范值相同的方向：缺省新增 own 同 cap，以及原 own cap 删除后回落同 cap；也覆盖在最后 Context getter 中改变绑定的切点，证明仍零原 Models 入口。这样与仅重读规范值的算法形成实际区别，而非仅镜像 helper 实现。

首个 stream factory 内的绑定变化须另测上述两个同 cap 方向，要求 factory 一次、bridge 与原 Models 零入口；初始 getter／Proxy／未知字段等非法绑定也测拒绝后原 factory 不可借回调将其修复，且无 bridge／authorize／store／Models 调用。所有切点使用自有 fake，原 SDK 不在默认测试中启动。

该有界适配设计仍须核官方公开缺省语义并独立复审；默认实现和公开 SDK generation／retry／恢复／压缩证据分开验收。RootTask、owner、实际预算计量／账单／模型、严格 input_tokens 和 Full 未资格。正式7/100、产品 gate=false、严格计量前自动审核关闭不变。
