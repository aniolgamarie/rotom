# Reviewer 可信控制面实施边界

日期：2026-10-05。以下是自有模块的已实现组合语义，尚未开放产品自动审批。

模型只返回封闭七字段 wire 结论。用户来源、当前 PreparedOperation、角色/风险类别、所选路线、会话/意图/请求引用均来自可信宿主。`ReviewerDecisionControl` 不注册模型 RPC、不加载 SDK、不持有工具执行回调。其票据是私有内存中的对象身份，不能由模型提交的 JSON、source、摘要或字符串句柄替代。

## 决定与原许可

`OperationAdmissions.prepared()` 只返回原 pending 准备投影，不提供正文，不重建终态操作。控制器 begin、发送提交和结论阶段都复核原 context 与重新解析的 resolution；Base、关闭、hard deny、角色禁止、必须人工均在账本/SDK attempt 之前拒绝或交还人工路径。

结论阶段先不可逆结算本控制票据，再将传输结论保存到 reviewer 账本，然后再次复核 current。有效且仍允许自动通过的 allow 通过原 `OperationAdmissions.issue(source="reviewer")` 取得原操作的一次许可，后续仍由原 consume 先烧掉许可、复核，再进入 ExecutionStore。中途配置/取消/目标/根改变没有许可；记账或回执失败不补签、不重新推理。记账完成后发生变化时，历史模型 allow 与授权 discarded 分开，不为模型质量评测改写历史结论。

原许可账本现要求受信`reviewer_current(prepared, current)`同步检查器：reviewer issue与consume都只有exact True放行，缺失/其他值/异常固定unqualified，模型不能安装该函数。回调取得原准备投影与current的深拷贝，不取得private input；consume先不可逆烧许可，再做原校验和该复核，失败后不得补发或重新消费。human/deterministic不调用它。检查器可读取现有账户短锁，顺序Admission→account→ledger，账户/ledger临界区不得反调Admission，回调不得重入同一Admission或等待网络/SDK进程。三个模块162项通过，之后仅澄清锁序注释；实际临时授权文件组合20项加hook/账户组合共96项在最终源码通过，分别记录，不累加。真实文件更新/同字节替换/缺失/损坏/过期/权限/忙锁均阻止旧reviewer许可消费，仍未实现真实scope/model/quality检查器与Host factory。

ask 返回 awaiting-human，没有自动许可；可信人工可对原准备对象作一次明确决定。没有 UI 时产品适配器必须维持 blocked。deny 撤销原准备对象并保留意图拒绝锁；新的自动请求不能靠命令改写或换 Provider 解除。新的用户意图必须由真实宿主输入产生，而非模型声称。

## 持久请求与预算

同一获准 OS 账号/预算周期固定一个私有 reviewer 根；profile 切换、重启或重连不得另选根清零。请求墓碑、意图锁和预算在同一 JSON 文件事务中，复用 Tree 的固定目录、no-follow、单链接、0600、比较替换及文件/目录 fsync，并用私有 flock 串行化。它不承诺跨文件事务，也不替代 ExecutionStore。

顺序为 reserve → 持久 claim_attempt → 建立 SDK 进程 → 持久 commit_send → 一次实际平台调用 → mark_sent/finish。claim 后失去启动回执不建第二个 SDK 进程；commit 后失去发送回执保持 unknown、一次已提交调用及预留，不重发。查询重复操作仅返回原墓碑，不再取得发送权。账号 ledger 的请求引用必须由可信宿主持久分配，与真实 SDK toolCallId 的映射在产品接线时完成，不能每次随机生成或 hash 账号材料。

同时最多一个尚未解决的自动判断占用同一可信用户意图。有效 deny/ask，以及已提交但未知或故障的判断锁住该意图；保守阻止其全部自动复审，不声称能够判定任意字符串的语义等价。允许结论完成后可判断同意图下新的操作。确认零发送的终态没有模型结论，可以对新的 PreparedOperation 再准入；原操作及原请求墓碑仍不可重试。

费用以货币十亿分之一的整数计量，预留按输入/缓存最高价与最大输出上界向上取整。没有用量不填零，部分或迟到用量保留预留且不能恢复决定。只有受信观察者确认最终完整用量及整个进程域已终止，才将预留换成 Provider 自报费用估计；估计不等于真实账单。读取恢复同样验证终态与终止条件。收紧预算不清零历史值并阻止旧权限继续发送，增加预算或换币种必须走后续显式授权流程，不能靠新建控制对象完成。

账本最多4096条、不淘汰墓碑；预算周期迁移/扩容需要正式维护与恢复设计，不能把容量耗尽改为无限。账户根与持久scope分配的独立组件已实现，尚未接入产品factory、官方工具调用或总BudgetLedger；预算扩容UI仍未实现。

## 进程与计量边界

自有进程桥没有默认 spawn 或回退；只能由可信监督 factory 启动。argv 固定自有入口 flag，环境仅 `OPENAI_LOG=off`，认证和上下文只通过私密 FD3/4。独立进程内再使用已验证 W 组件加载 SDK，避免主 Pi 的 Node environmentData 继承。四字节 length framing、全层重复键/Unicode/深度/closed schema 校验及逐方向8MiB总流量上限共同约束消息。单个 payload 最大512KiB；单次响应 body 最大256KiB。

首版按上限收集整个 Response body，再通过 base64 帧重建内存响应供 SDK 读取。计量/请求验证仍位于父 T 的一次 fetch 边界；这个实现会等待完整 body 才开始 SDK 的响应处理，不能写成实时跨进程流。写入最多一个在途加一个排队帧；响应/ACK 状态在真正开始写帧前迁移，合法的快速对端不会因 callback/drain 尚未返回而误拒。只排队、尚未发 ACK 的消息仍不能提前通过。

factory terminate 只有 exact true 才可标完整进程域终止；child exit、kill 成功、Writer/Worker 退出不自行证明整个 namespace。未知状态不释放产品资源或预算。真实账号、上游 SDK 在此新进程路径的验证、正式 supervisor factory、真实模型质量与启用门槛仍未完成。

## 稳定验证

进程 framing：71纯字节测试。进程桥：66 fake lifecycle/pipe 测试；三项响应/ACK时序及模型上限行为红例修复后通过。累计账本：45默认临时文件/线程测试，包含原子提交/回执丢失/重启、预算与拒绝锁；两项独立审查 P2 经行为红例修复。可信决定控制面45、原准入账本75、持久账本45合计165 passed，不累加历史子集。稳定独立复核对应源码 SHA 和日志保存在任务记录。

这些结果不等于真实 Pi/账号/上游 SDK 新进程、人工 TUI、总 namespace 终止、账单或产品 Full 通过。正式任务计数保持7/100。

## 自有新进程探针

`scripts/test-pi-reviewer-process-self.py` 的32项默认测试只使用 fake 子进程。另行执行的自有 Node 探针在断网 bwrap 中运行固定副本，五个场景为 allow、Base、off、hard deny、必须人工：只有 allow 建立一个新子进程及其中的 Worker，发出一次 fake 请求并观察到两条 raw 事件和自报用量5/3/8；其余四项均零进程、零发送。新 Worker 没有继承外层 Node 的合成账号环境变量、environmentData、NODE_OPTIONS 或 argv 秘密。该探针没有加载官方 SDK，没有访问真实账号或模型。

首次运行在启动 Node 前因本机 bwrap 不支持 `--clearenv` 而失败。父进程原本已用 `env={}` 启动 bwrap，删除多余参数后，行为回归测试及新的固定材料重跑通过。失败记录没有改写成通过；第二次运行的源码、清单、固定二进制摘要及原始观测经独立复核，保存在私有任务记录 `risk-self-process-review02`。子进程 close 和外层 bwrap 退出已观察，整个 namespace/process tree 终止仍为未独立观察，不释放产品预算或资源。

## 用户意图接线前提

现有人工文件/Shell 准入每个工具调用分配的随机 `intent` 不能当作 reviewer 的真实用户意图。公开 `input.source` 可由调用者选择，同样不能签发新意图。自动审批必须从受信用户确认通道建立私有范围，在任务结束、替换会话、取消及无法关联来源时退役，并使同一范围内的 SDK toolCallId 映射到稳定请求引用；意图拒绝锁与累计预算独立于 profile 和宿主重启保存。

公开扩展 API 的 `pi.sendUserMessage()` 是 void/fire-and-forget；随后立即 `waitForIdle()` 可能在异步输入处理完成前返回，不能据此认定任务已经开始或结束。当前替代路径是在自有宿主闭包中持有官方公开 `AgentSession`，等待其公开 `sendUserMessage()`/`prompt()` Promise，在私有 AsyncLocalStorage 中绑定明确确认过的目标。`prompt()` 在settling期间先排deferred动作再立即返回，早于input；普通streaming排队则在input handler之后。两种排队均不能续签原范围。

自有 `confirmed-intent-scope.ts` 已实现exact true确认、Base/off/noUI/busy/队列零提交、双时钟期限、输入/start因果门及submit Promise接受门；只在私有marker的原input和首次start均观察到、有效配置未变且submit返回Promise后开放工具引用。第二input/start、原settled、取消/变更/超时/退役和run退出立即撤掉引用；旧timer或queue即使继承ALS也无权复活。UI确认同时接收公开AbortSignal和timeout，范围退役会关闭该确认。正常原settled只是本次scope的观察状态，不是业务/预算产品完成。allocator错误或误返回异步Promise固定失败且观察拒绝，不泄漏原始错误。

原87项默认自有回调/异步上下文测试和稳定增量独立审查已通过，记录位于 `risk-confirmed-intent-scope`。后续增加恰选同步/异步分配器的私有接口，新增39加原87一次126通过，稳定独立审查无剩余P1/P2。同ID在callback前占唯一pending槽，退役及时null，迟到结果不复活；异步ID与持久Store的ASCII契约一致。细节见 [reviewer-async-tool-binding.md](reviewer-async-tool-binding.md)。真实持久RPC、退役墓碑和最终PreparedOperation绑定仍未接线。

这些不是官方 SDK、人工UI或持久分配证据。十场景公开 SDK 断网合成探针见 `native-intent-scope-probe.md`；原review01已准备并完成稳定审查，但新增异步接口改变其自有source pin，因此现在只保留为历史、不执行，须重新准备再核对新运行授权。静态调用链和假宿主测试不能证明官方 SDK 的异步传播、输入处理、并发提交及排队消息边界；这些必须单独验证后才接入产品。不得用修改上游方法、原型或私有字段补齐因果链。


## 账户存储与独立进程验证

账户门面在固定passwd协调根下持有累计账本，preparing/updating/ready哨兵绑定账本stat及非秘密字节摘要；missing/replaced/unknown状态不另建空账本。旧账户存储四模块155项、账户控制根保护八模块217项及五selected消费者76项是不同历史验证集合，不累加成当前总数。控制根保护从已有受信registry取得，并覆盖尚未建立的授权/预算路径。

六场景自有Python OS探针已完整通过run04：并发仅一claim和fake-dispatch，四个os._exit切点71..74与独立进程恢复拒绝/墓碑观察，以及unknown预留320和后续deny-lock。最新默认父检查器63项与稳定SHA/原始工件独立审查通过，私有证据在`risk-reviewer-account-os-run04`。前三失败保持原样，固定PWD环境问题和父120/实际最高缓存费320差异均修正；两个构造器逐一完成后才共同go进行claim。它未运行SDK/账号/HTTP/模型，未证明schema2共存OS、断电或整个namespace终止，不释放未知预留。

账户授权纯协议102项通过，拒绝未知字段/凭据字段/非法价目、bool整数、换币/提额及过期窗口，显式更新使旧live identity失效；格式校验不自证路线、价目或模型质量。授权文件私有存储与精确协调根白名单五模块257项通过；显式CLI及相关回归190项、human输出窄修后1项分别通过。纯模型路线匹配69项及协议/模型配置回归合计217项通过。这些组件各自完成稳定独立审查；宿主live scope/模型路线/费用资格与factory接线仍未完成，真实数值未授权，Full不启用，正式任务保持7/100。

账户授权与发送提交的默认组合现已通过：reserve/claim/commit在同一账户短锁内复核授权live identity/窗口，绑定态禁止另传limits，price/caps不得由profile或请求覆盖。持久commit与显式授权更新以该短锁串行化；commit后更新不证明已提交请求停止。迟到facts使用已核验持久额度；只对账重开入口不读取authority、不创建budget、无法获取新发送权。最终36项组合及原账户/存储共136项通过并完成稳定独立审查；早期239项与原OS6历史材料分别保留，不称当前授权组合的OS或完整factory证据。

私有持久session/intent/tool-request映射已通过scope-only 88项和独立scope/account组合11项，两者属于不同运行；早期219组合含重复87子集单独保留。固定私有目录、真实authority同账户短锁、原子文件/失回执幂等重读、永久退役和容量墓碑均已完成稳定独立复核；see `reviewer-persistent-scopes.md`。该表不证明确认来源或活动实例，原confirmed-intent的同步request分配和官方async hook/execute ID绑定仍待接线。DecisionControl的受信同步`scope_current(prepared_copy, scoped_refs_copy)`离线组件已验收：新增38项与原decision47项在一次运行中合计85项通过。begin仅分配一次并在私有ticket保留原始三引用，begin/commit/conclude及最终issue前复核只接受exact True；缺失、其他值或异常固定`REVIEW_SCOPE_UNQUALIFIED`。Base/off、hard deny、role/human/risk门先阻止，不调用scope检查器。拷贝不含private input；commit资格失效撤销原操作，不允许恢复资格重启attempt；迟到mark_sent和用量仍可记录，失效结论不签许可。

predicate释放账户锁后仍可能发生跨进程退役，因此它本身不是durable commit的原子证明。账户门面新增显式`scope_required=True`绑定模式，在同一账户排他flock内核验持久scope并执行reserve/claim/commit；claim/commit取原账本行中的三引用，私有检查器不再次开锁或调用公开Store方法。未来产品factory必须显式选择True，当前没有该factory。退役与commit共锁序列化，commit后退役不撤销已经提交的send；facts和settlement不需要live scope。组合在safe-error修复前一次运行新增34项加关联188项共222项通过；修复后仅泄漏单例1项和新增模块35项分别通过，222是历史运行而非修复后重跑。未知底层异常固定`Conflict`并用`from None`抑制默认traceback链渲染，不擦除内部`__context__`，边界不得序列化原异常链。以上不证明真实用户确认、官方SDK传播、OS跨进程scope竞态或产品接线；正式任务仍为7/100。

## 无界面有效ask的当前行为

2026-10-06的稳定增量补齐无UI投影：私有`human_available`默认为None，配置只接受可信同步函数；有效且仍current的ask先按原结论持久记账并保留意图锁，再检查此predicate。只有exact True返回`awaiting-human`，其余保持`blocked`；两种结果均保留reviewer来源、原reason_code及permit=None。回调仅取得准备投影深拷贝，无正文或凭据；配置为async函数固定拒绝，误返原生coroutine关闭但不执行。回调既不证明确认，也不签人工许可。

旧行为红例真实复现缺UI时返回`awaiting-human`；修复后新增UI30、原Decision47、scope gate38和authority permit20在一次默认守卫运行中135通过。稳定三文件独立审查未发现剩余P1/P2，证据归档`risk-no-ui-ask`。这一增量仅关闭T049的无UI条件：实际序列化出站请求的秘密/hash检查和T050集成竞态/动态依赖覆盖仍未完成；不把组件通过记成整项完成或产品启用。
