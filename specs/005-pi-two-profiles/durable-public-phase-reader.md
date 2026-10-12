# 固定公开 phase Reader 设计

本决定只新增自有 `phase-reader.ts` 与默认测试。它组合公开 RegistryReader／RegistrySnapshot，并把两个已创建的自有 phase Task 放进实际 task 选择结果。原 SDK／默认 registry／builtin 不修改、不冻结；不调用私有 helper，不把同名 task 安装进原 registry，不热换已有 Harness。本组件尚未实现；后续完整 readonly／Models 工厂接线另行验收。

## 输入和输出

导出 `createDurablePhaseReader({base, generationTask, compactionTask, verifyCurrent})`。输入恰四个 own enumerable 数据字段，拒绝未知字段、getter、Proxy；这是受信服务工厂配置，不接受客户端提交的 task／registry 来取得权限。base 是构造期自有 readonly registry 的原公开 Reader；两 task 是 `createDurablePhaseTasks` 产生的原 token，分别名为 pi.generation／pi.compaction、version=1，与原 base builtin token 不同。组件不靠私有品牌识别 token，不把 token／数字 ID 当授权。

两个提供的新 token 恰有 definition 字段，definition 按原公开契约恰五项必需 name／version／initial／phases／abort，仅允许 migrate／hooks 可选，不虚构 input／checkpoint 属性。initial／abort／可选 migrate 为非 Proxy 函数；普通 own phase map 至少有对应 request／summarize，至多 64 项，每项为非 Proxy 函数，名称沿用 phase 组件的非空／200字符／控制字符拒绝规则。原 base 的三个 builtin／Root 仍只核既有公开 name／version 和完整有界原引用图，不把此新 token 验证误作私有 SDK 品牌。

输出是冻结的自有 `{registry, check, close}`；registry 只公开 `snapshot, subscribe`，不公开 install／uninstall。snapshot 始终返回同一冻结的自有 front snapshot，包含公开的 `installed, extension, tools, sections, tasks, task`。允许的原 base 固定为一项 rotom.durable.readonly extension、两个 rotom_read／rotom_search tool、四个 task（原 generation、pi.tool、原 compaction、rotom.durable.request）、零 sections；这是本轮明确的首批路线，不自动接收后来安装的插件。

原 base snapshot、方法及选择结果分别捕获。front 的 tasks() 保持原顺序，仅用两新 token 替代 generation／compaction；task(name) 与 tasks() 中的同一 token 严格一致。pi.tool／RootTask、extension、tool 保持原 item 引用。installed／tools／sections 使用自有冻结数组和 row 容器，不冻结其原 item；数组身份不作 SDK 的 task 身份证明。未知 task／extension 名返回 undefined，且进入前仍检查当前来源。

## 检查和实际调用

构造时，在任何外来 verifyCurrent、base.snapshot、公开表或 subscribe 回调之前，先纯捕获原输入字段的描述符／原型、base 的 snapshot／subscribe 原方法及所在 owner／描述符／继承链，以及两个提供 token 的完整原 own definition 引用图。图按既有边界限制为 4096 个对象、64 层、字符串／键合计 1 MiB，拒绝 getter／Proxy；函数只保存真实引用，不扫描闭包。首次外来调用返回后必须复核这些调用前的原 guard，不能等回调已换掉 token 的 phase handler 后才把新函数当原值捕获。

选定方法的继承链捕获从 target 开始的所有非通用对象及原 prototype 链接，直到 Object.prototype／Function.prototype／null 为止，包括选定方法 owner 上方的非通用超类；每层拒绝 Proxy。仅保存选定名称的原方法描述符，不遍历其他方法或私有槽，不声称防护通用 global prototype 修改。

所有原函数用模块局部捕获的 Reflect.apply 裸调用，保留原 receiver 与参数，不读取函数自身 call／apply。只核选定公开方法／字段，不扫描 SDK 全图或闭包，也不修改原生／SDK 函数对象。

原 base 返回的 snapshot 在取得后立即捕获其身份与选定方法所在 owner／描述符／继承链；尚未返回的对象不虚构调用前身份。首次 snapshot 及各公开表调用前后检查先前捕获的输入／token／方法描述符，保存选定 base task／definition／extension／tool 和原返回容器的有界公开 own 数据引用图。拒绝缺项、增项、顺序改变、同名重复、错误 kind/version 或不合格容器。读取返回容器不能触发 getter／Proxy。不以创建时一次检查代替后续来源检查。

check 先取得本组件同步 busy 边界并纯核原来源，再调用原 verifyCurrent（receiver 为原四字段输入）；只接受同步 literal true。普通同 realm Promise 仅用捕获的原生 then 添加双 undefined handler 观察，始终拒绝；特殊 Promise／thenable 不执行未知 getter。随后再次纯核、调用原 base.snapshot 并要求仍是原 snapshot；按原 receiver 重读六个公开表／选择方法，与原规范表逐项一致，最后纯核所有已捕获原引用／描述符／自有 token 和 closed 状态。最后纯核后不再调用外来 callback，再返回公开结果。

所有 Reader／front snapshot 方法都经过上述 check。同步重入、原来源漂移、非法返回或检查失败永久关闭本组件并给出固定错误，原异常／内容不进入摘要。busy finally 必须释放；close 幂等，只关闭此组件的后续选择资格。不得用全局方法替换、SDK patch 或伪装新的 snapshot 来延续漂移后的资格。

此检查承认固定可信 SDK 原函数体及闭包的边界，不声称能证明任意外来函数的内部代码。自有 token 的完整公开 definition 原引用图需复核，但函数本体通过捕获的真实指针调用；不靠其 own.call 属性检查。

## 订阅与关闭

RegistryReader.subscribe 是公开 publication 通知接口。scheduler 登记 listener，通知只触发 kick，稍后才读取 snapshot；base 先发布再同步通知，listener 异常会传播。自有 Reader 按原 receiver／原 listener 调用捕获的原 base.subscribe，不造新的 publication，不修改 listener，不把 close 当作 SDK seal／进程停止。

subscribe 在原登记前后核来源。正常返回的原 disposer 必须是非 Proxy 函数，并原样交给调用者；原 SDK disposer 不冻结、不改写。原 disposer 在本组件 close 后仍可执行。若已取得 disposer 后的检查失败，使用捕获的 Reflect.apply 调用该原 disposer 恰一次清理本次登记；清理失败记固定未知错误，不重登、不盲重试。原 subscribe 未返回 disposer 即抛错属于未知登记回执，本组件关闭，不补造已经清理的证明。

原 base 后续 publication 仍通过原订阅唤醒 scheduler；下一次本 Reader 检查会因原 snapshot 已改变而拒绝。in-place 数据漂移可能没有 publication 通知，所以每次检查仍核原数据。close 不主动伪造 listener 通知，也不证明 host 已停止；完整服务必须按宿主公开 seal／关闭顺序释放订阅与执行资源，该生命周期尚未验收。

## 后续 readonly／Models 接线的不变量

新增独立的 phase Models 工厂分支；旧无 hooks 工厂和旧 hook Models 工厂保持各自原配置语义。复用内部 readonly execute 验证逻辑时，必须在新构造期把它的预期 api.registry 绑定到实际 front snapshot，原 base source 另行检查。不得复制／改写 SDK 的 api、Context、参数或数字 ID，也不能用旧 basesnapshot 冒充真实 ToolExecutionApi.registry。

新分支只把本 Reader 交给公开 Harness；Models 用同一私有 phase bridge，保留 provider 最后准入、原 ledger prepare→sending→result→settled、unknown 占用及关闭后限定事实结算。组件检查之间不得形成 reader.check→phase.check→reader.check 的循环；phase verify 必须是受信的原来源／当前权限检查，不递归调用其外层 Reader。每个外来检查后的最后纯复核覆盖 readonly 和 Models 原来源，不因追加 phase 检查而留下新的变更窗口。完整工厂的具体内部接口与构造 ready 边界必须另冻结、审查和测试，不能以本 Reader 通过替代。

## 默认验收

只用 fake 公开 base／snapshot／Task、自有函数与原生 AbortController／Promise，沿用既有 mock runner 的临时 HOME／XDG／断网／进程守卫。不得导入 SDK、打开 SQLite、启动宿主／原生锁探针、读取账号或调用模型。

覆盖四字段闭合配置、精确两项替代、task()/tasks() token 一致、原 pi.tool／Root／工具 item 引用、固定 front 身份、未知名称、原接收者／参数／次数、原方法继承链、source getter／Proxy 零执行、输入／prototype／definition／extension／工具／原返回数组及 base snapshot 漂移、最后外来调用后的纯复核、同步重入、Promise 固定拒绝、close 后全方法拒绝但原 disposer 可释放。必须验证首次 base.snapshot／verify 回调修改新 token 原 handler 时构造被拒，不能把修改后的 handler 当成首次原值。订阅覆盖原 listener／disposer、publication 唤醒而没有快照自动替换、登记后失去资格的恰一次清理、未知登记回执不假称清理成功。

首次新增能力的默认通过不冒充旧实现行为红；若复审发现缺陷，则用完整旧源码和同一新增测试保存实际失败，再做最小修复和稳定增量复审。不反复重跑不受影响组件。

本层不证明实际 Reader 已被 Harness 选中、真实 initial／retry／recovery／压缩全部模型入口、原 agent 扩展／工具选择、永久授权、owner、业务根、严格 input_tokens、模型账单或 Full。正式任务 7/100 和全部产品 gate 保持 false，自动审核继续关闭。
