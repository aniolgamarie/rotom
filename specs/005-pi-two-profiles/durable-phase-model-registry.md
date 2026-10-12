# phase Models 工厂设计（待独立复审）

本决定新增显式 `createDurableReadonlyPhaseModelRegistry`，复用已有 readonly／Models 算法，组合已验收 phase Task 与新的固定 phase Reader。尚未授权按本稿写集成代码；须先独立复审并完成 Reader 组件稳定验收。旧草稿与公开接缝证据保留，不把设计当 SDK 或产品验收。

## 公共契约与来源

输入恰七字段 durable／rootTask／control／verifyCurrent／sourceIdentity／registryIdentity／modelDispatch；modelDispatch 恰七字段 models／ai／store／model／authorize／resultFacts／limits。输出仍是冻结的 `{registry, models, check, close}`。旧六字段工厂与旧七字段 hook Models 工厂保留原含义，不新增客户端 mode／snapshot／task 参数，不热换活动实例。

新入口的 verifyCurrent 以原七字段 input 为 receiver、零实参调用，使用捕获的 Reflect.apply；这一新契约不改变旧入口的调用方式。只接受同步 literal true，普通 Promise 仅安全观察后拒绝，未知 thenable／constructor 不执行。原 input／modelDispatch 的 descriptor／prototype／字段身份、原 rootTask／control／model／limits 图与选定 SDK／Models／store 方法在首次外来回调前纯捕获，并在回调后复核。秘密值不进入摘要或错误。

新路线的 sourceIdentity／registryIdentity 由受信服务来源与权限控制面核对，必须对应实际 phase Task／Reader／源码路线；构造器只核合法固定身份及原引用，不声称一个 hex 字符串自身证明语义。集成默认检查不提供持久授权或实际来源摘要资格。

构造时只核 authorize 与 limits 的原来源。实际 budget 尚未产生，不预执行 authorize、不加第八配置字段；它仍在 provider 原三轮 envelope 检查与账本准入时产生和核对。

## 最小私有接线

保持原 createReadonlyRegistry 内部的 base registry／snapshot／方法／四 task／一 extension／两个工具核验。另增私有 `executionSnapshot`，默认等于 base snapshot；仅新构造分支在下述 project 后将其设置为实际 front snapshot。execute 两次原 api.registry 检查改核 executionSnapshot，原 base.snapshot()==baseSnapshot 和公开表／原引用检查保持。

已有内部 wiring 保留 origin／fail／hooks；新分支仅增加以下四项自有闭包，不进入公开 input：

- project(baseRegistry, baseSnapshot, finalReadonlyPure)：在 base snapshot／完整 table checker／finalReadonlyPure 已建立后、原内部最终 check 前调用一次。新分支保存该 pure 闭包，创建私有 phase Reader，取得其实际 inner front，再创建下述自有外层 Reader／front；返回自有 `{registry, snapshot}`。readonly 对外 registry 改为外层 Reader，executionSnapshot 是这个 Reader 实际返回的外层 front；原 base 和 inner Reader 不向客户端暴露。旧分支没有 project。
- qualify(checkBase)：将原 readonly 的 check 主体独立为同一个自有 checkBase 闭包。新分支的公开 check 及工具内部每次 lexical check 都交给 qualify，后者同步调用原主体，不改主体的表、引用或控制算法；旧分支没有 qualify，仍直接运行原主体。这样工具 await 后的检查同样包含 phase 活性，不能只检查函数引用而漏掉 phase 私有关闭。调用链和精确窗口见下节。
- beforeExecute()：仅新分支在 execute 最开始调用，检查完整工厂已 published，且不在 checking／reading 中；否则永久关闭工厂并固定拒绝，零 getTask／commit／control／模型入口。紧接着的原 lexical check 由 qualify 完成全厂资格检查。原内部构造 check 不调用该 execution 门。

- readContextSignal(context)：仅新分支将工具首次取得 abortSignal 与 guard 中每次重读原 Context.abortSignal 的两处公共属性读取交给此私有函数；旧分支仍按原表达式读取。它先核 ready／published 且无 closed／checking／reading，再只为本次同步公共 getter 设置 reading，读取原属性恰一次，返回后做最后跨源 pure，并在 finally 清 reading。所得原值继续由既有 native signal 校验，不改变 Context／receiver／返回引用，不反射或重写 SDK getter；getter 只返回已经 aborted 的原 signal 时仍由 caller 局部拒绝，不因此关闭其他任务。getter 内重入 saved phase／tool 时分别由 phaseVerify／beforeExecute 拒绝并关闭整厂，零原 handler／新增工具或模型执行；该门不跨 await、不覆盖其他工具方法，不阻止独立异步任务正常运行。

外层 Reader 是自有冻结的 snapshot／subscribe 两方法对象，外层 front 是自有冻结的六公开方法对象。它们只裸调用捕获的 inner 原方法，保留原 inner receiver、调用参数和原 item／token／数组结果引用；snapshot 核 inner 返回的是已捕获 inner front，再返回同一个外层 front。subscribe 原 listener 和返回 disposer 完全保留，不冻结或替换原 disposer。各外层调用及私有 Reader.check 均用同步 reading 门包围，调用后核最后跨源 pure；inner 失败、Reader 重入或最后纯核失败都先关闭整厂再固定拒绝。没有直接 inner 方法泄漏，Reader 任一可达自关闭不能被调用方 catch 后绕过 Models 准入。此前返回的原 disposer 仍属于宿主生命周期，不能把它的未来错误冒称 Reader 内部关闭或物理清理证明。

外层 subscribe 必须先保存 inner 成功返回的原 disposer，再进行最后跨源 pure。若随后失败，先关闭整厂，并用捕获的 Reflect.apply 对本次已取得的合格原 disposer 恰一次清理，receiver=undefined、零实参；清理失败固定为未知，不重试或声称成功。若 inner 调用本身抛错，外层没有原回执，不能补造清理或重复 inner 已做的 cleanup。该增量专门覆盖 inner 最后表回调改变 Models／store、而 inner 自身 Reader 源仍相同的情况。

new hooks(builtin) 只核原 builtin token 与已捕获 SDK generation／compaction／pi.tool 一致，返回 null；不安装旧身份 hooks。原 definition 自带 hooks 由 phase Task 保留。SDK builtin 不安装替代品、不 patch；只有传给 Harness 的公开 Reader task 结果选择两自有 token。phase Reader 前提与图边界沿用其独立设计。

finalReadonlyPure 是已有最后纯源核的闭包，独立于 checkSnapshot，不执行 base／front 方法、verify、Context getter或模型。新分支保存原闭包，不公开给客户端，不以 phase.check 冒充它；最后纯核同时覆盖 executionSnapshot 的自有原结构及新 token 图。

## 构造资格与无环检查

完整工厂具有私有 ready／published／closed／checking／reading 状态，以及只包围 createDurablePhaseTasks 调用的 phaseConstruction 标记。ready 仅指组件已装配到可执行最终检查，published 在最终检查成功后、无外来调用的返回之前才设为 true。phaseConstruction 在 finally 清除；它只让 phase 组件自己的首次构造 verify 使用受信外部当前检查与纯来源，不让 phase 提前执行：组件自有 ready／busy 仍拒绝 defineTask 中的提前 handler。

phase 构造返回之后、published 之前，phase verify 固定拒绝实际 phase 入口并关闭整厂。published 后，checking／reading 中的外来回调同样不能进入实际 phase。唯一例外是下述同步 phaseCheckWindow 中被捕获的原 phase.check 自己发起的 verify；该原 check 在 verify 前已取得 phase 组件自己的 busy，外来回调直接重入 token 会被组件拒绝，不进入原 handler。phaseCheckWindow 只包围这一原 check 的一次裸调用，finally 复位，绝不跨 await、Reader、readonly check 主体或其他外来调用保持。完整构造最后必须检查 phase 没有被提前尝试关闭。

Reader 构造及构造期取得 inner／outer front snapshot 只进行元数据选择，Reader verify 使用外部当前检查＋已有纯来源核；不调用尚未完成的内部执行检查。该特许只包围自己的 Reader 构造与获取初始 snapshot，finally 复位。完整工厂 ready 后，Reader verify 进入 internalCheck。构造期 readonly 工具仍由 beforeExecute 拒绝。

检查图固定为：

- originPure：原 input／SDK／两 task／Models／store／limits 等纯核，不调用 Reader、phase、snapshot 或 verify。
- phase verify：只接受 phaseConstruction，或 ready 且 checking 且 phaseCheckWindow，或 published 且不 checking／reading；再核原外部 verify＋originPure／finalReadonlyPure。拒绝先关闭整厂；不调用 Reader／phase.check。
- qualify：先拒 closed 或 checking；取得同步 checking 门 → originPure → 裸调用原 checkBase → 裸调用原 phase.check（仅这次调用设 phaseCheckWindow）→ 最后跨源 pure；finally 清两个门。唯一构造例外是自己 createReadonlyRegistry 调用范围内、尚未 ready 的原最终 checkBase，可核元数据但暂不运行 phase.check；该范围标记也在 finally 清除，实际 phase／工具仍由 published 门拒绝。不得让构造特许变成客户端模式。
- internalCheck：要求 ready／未 closed，调用私有 readonly.check（它进入 qualify），再作最后纯核。readonly 工具自己的每次 check 也进入同一 qualify，不绕过 phase 活性。internalCheck 与 qualify 都不调用 Reader，原 checkBase 只保留 readonly 原核验。
- Reader verify：构造期元数据检查；运行期 internalCheck。
- 公共 check：顺序 internalCheck、Reader.check、最后跨源 pure；不把整个顺序的 checking 门保持到 Reader verify 再次进入 internalCheck，避免正常调用自锁。

Reader 自有 busy、外层 reading 和 qualify 自有 checking 各自防同步重入；reading 允许正常 inner Reader.verify 进入 internalCheck，但 phase／工具实际执行不能借此入场。phaseCheckWindow 的安全性来自原 phase.check 先取得自有 busy 的已验收实现和原方法引用，不能泛化为允许任意 checking 中的 phase。普通 phase handler 在 begin 返回后执行原 SDK 代码，允许它正常调用 Models／工具；这些资格门不保持到原 handler 的异步生命周期结束。不借助私有宿主状态或函数改写实现。

完整返回之前先设置内部 ready，执行上述公共 check，并核闭合输出来源；成功后才设置 published，且设置后至返回不执行任何外来调用。任何失败清除资格并关闭组件，不返回半构造产物。ready／published 都不能被解释成产品 writer／owner ready。

## 最后模型入口与失败范围

Models 使用同一私有 phase bridge。bridge 门面先 internalCheck，再裸调用捕获的原 phase take／check；无论正常返回或固定拒绝，随后纯核原 input、readonly、两 task、Models、store 和 limits。原 phase bridge 最后会读取 Context getter，所以这项跨源纯核必须在该 getter之后；中间不再执行其他 getter／snapshot／verify／外来回调，然后才把原 identity／true 交给 provider。

跨源 pure 失败永久关闭工厂。phase 自有固定 phase-unavailable 表示整体完整性失效，也关闭该工厂；用原 owned error 的数据 code 识别，不执行未知 getter／Proxy。不因局部 signal-invalid／identity-stale／identity-retired／identity-consumed／operation-invalid／identity-unmatched 等拒绝关闭其他合法任务。拒绝不退款或新授权；旧 identity 不使顺序新 lease 复活。

不改变 provider 的最后 alive 与原 Models 入口相邻、原接收者／参数、重试关闭、账本 prepare→sending→result→settled、unknown 占用或该任务后续付费拒绝规则。源检查失败不能用查询缺记录来补造未发送。

## 关闭和迟到事实

close 幂等：先 closed=true、published=false，再依次关闭私有 Reader、readonly、phase、dispatch 的自有资格。它不造 publication，不执行 SDK seal、不释放 owner，不签进程或 IO 停止；订阅的原 disposer 仍可由宿主公开生命周期使用。新读／工具／模型资格必须失败。直接 phase 结构失败可能先在组件自身关闭；下一次工具、Reader 或 Models 资格检查必须经 qualify 核原 phase.check 并关闭整厂，不以纯引用相同推断该组件仍活。

事实门面保持独立 factsOrigin：即使关闭，仍只核原 modelDispatch／collector／recordResult／settle 来源，再记录已经发生的结果并按原账本有限结算。不得调用活性 check 重授权限，不重新发送、不发布成功、不退款未知占用。只复用现有记录／结算／错误语义，不增加第二队列、恢复算法或日志顺序。默认 close 不声称一般外来 SDK 函数异常下的物理资源清理完成。

## 验收范围

仅修改自有 registry 与新增 phase-model-registry 默认测试，必要公共导出另明确；provider／phase Task／Reader／SDK 的算法与原六源增量不重写。既有受影响 readonly140+新增1、Models71 的当前原断言保持，只运行受影响路径与新组合；不无故重跑 storage／requests／OS／其他已验收组件。

新默认组合用 fake 原公开 Task／Registry／Models／stream／store／control，证明实际 outer front 引用与 base 来源独立、原 two task、初次／顺序 retry／新 invocation recovery／压缩、原 signal／Context／args、局部取消与迟到旧 identity、原错误和例外 finally、三次授权／真实原 sending callback计数、提前 phase／工具零入口、最后 snapshot／verify／Context getter 改源时零底层模型入口、闭合配置和新 verify receiver、关闭后迟到原事实不授新权。另证 inner Reader 非函数订阅回执及重入被捕获后，后续合法 phase／Models／工具仍零入口；构造最终 check 和运行期 readonly／Reader 元数据回调直接调用 saved phase／tool 时零原 handler／getTask／模型入口；正常可信 phase.check 不自锁，工具 await 后 phase 已关闭时不得执行控制面。预算在运行时按原 envelope 检查，构造时 authorize 调用数为零。

工具 Context getter 的默认反例分别在初次取 signal、工具 guard 重读，以及一次原 getTask await 完成后的 guard 中调用 saved phase；不由 fake helper 预先设置 reading。相同新测试在完整旧组合源码上应记录真实原 handler 进入的第一失败点，修后 handler／Model／控制 backend 零新增入口且全厂闭合。另证 getter 中调用 saved tool 零新增 API 读取；getter 正常返回原 signal 时仍成功，并且抛错或来源变化后 finally 清门而不重新开放。已经发生的 SDK 读取／事实按实际切点分列，不把前段读数说成零。

外层订阅还须验证：inner 成功后仅跨 Models／store 的最后 pure 失败，原 disposer 先保存并清理一次；清理抛错仍一次且未知；inner 自己已抛并清理时 outer 不重复；成功回执仍是原 disposer，关闭后仍可由公开生命周期使用。

首次新增 API 能力不冒称旧实现行为红；发现实际缺陷才保存完整旧源码与同新测试的真实失败。稳定组件复审只签默认范围。公开 SDK 初始／恢复／重试／压缩全路径的合成探针要另准备可审查材料并独立授权；RootTask／业务根／owner／严格 input_tokens／真实模型与账单及 Full 均未资格。正式7/100、产品 gate=false、自动审核关闭保持。
