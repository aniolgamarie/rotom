# 作用域与原 PreparedOperation 绑定

日期：2026-10-06。当前真实文件/Shell execute 已传递原 SDK tool ID、最终 params、signal 与 ctx；人工 admission 仍使用随机 request/intent，不应把它们视为 reviewer 意图。以下冻结接线目标；独立绑定核心已完成，私有scoped prepare与产品factory仍未接线，未启用自动许可。

## 原输入与一次请求

自有 execute 先有限捕获最终输入，再在同一私有 confirmed scope 中等待原 tool ID 的持久 request_ref。任何 await 后都复核原 scope/current/取消和期限。前置 tool_call 事件的 input 可被后续扩展修改，不能用事件中的早期参数替代 execute 捕获值。

同一 request_ref 只绑定一个 PreparedOperation。其 request_id 必须原样使用 request_ref，context.user_intent_ref 必须等于原 intent_ref；原 SDK session_id、manager activation、角色、cwd、配置/限制/策略身份与取消 epoch 仍由可信宿主捕获。scope allocation 的幂等不允许重复 execute 创建第二个 operation_id；同 tool ID 而输入或 context 不同应永久冲突，不能新随机 ID 避开原墓碑。

scope 元数据只走原 manager 私有控制通道，不新增模型工具参数。业务 input 中的同名字段永远只是待解析业务参数，不参与权限绑定。Base、off、未安装私有 scope provider 的路径保持原人工 admission；提交 scoped 元数据而 provider 缺失必须失败，不能静默退回随机 refs。

## 服务端核验

后续 admission 的私有 scoped prepare 接缝应核验原 scope control、confirmation nonce、tool_call_id 与其实际取得的 request_ref，核对 scope control 捕获的 SDK session_id 与准备 context，再从服务端返回原三引用。调用者不能自行提交 session_scope/intent_ref 或声称 current=true。

FileAdmissionControl 的原请求槽在 bridge.prepare 前保留这个精确 binding。回复丢失后的同参重读必须得到原 prepared 投影；换 control、确认、tool ID、request_ref、context 或捕获输入均不得重建许可。操作投影的 operation_digest 继续绑定原 request_id/context/resolution/private_input_ref；不将正文或认证 hash 写入公开投影。

当前 FileOperationAdmissions 与 ShellOperationAdmissions 的 resolution 仍固定 requires_human=true。持久 scope 绑定本身不应降低它；只有后续可信风险资格与硬策略配置明确允许时，才进入 reviewer 分支。服务端私有 source 始终由明确决定者选择，客户端或模型不能把人工准备对象升级为 reviewer allow。

## 锁与生命周期

外层 Supervisor mutex 统一控制 session/admission/scope 内存状态；准备分配和持久 verify 按 service→account 进入短锁，实际 execute 不持锁等待 SDK/网络。准备是可撤销的元数据，不是执行权限；issue/consume、预算 reserve/claim/commit 和实际 Writer/后端消费保留各自已决定的核验点。

reviewer_current hook 在 Admission 非重入Lock内，不能反调同一 Admission，不能等待 RPC/SDK，也不能从没有持有 service mutex 的入口反向取得它。最终 Host factory 必须统一串行入口和限定同步 predicate；这个 callback/借锁契约仍需实现审查，不能只因一次 prepare 的 verify 成功而缓存永久资格。

scope 退役、session 替换/dispose、新确认、任务原 settled、取消、期限及配置变更均撤本地能力并写原 nonce 墓碑。物理执行已消费或发送已持久提交之后的退役，不应改写成“从未执行/发送”；后续终止和账本事实按原 unknown/恢复约束保留。

## 目标测试

默认集必须同时观察 scope allocator 次数、原 request/operation/permit 数及实际执行计数：同 ID 并发只有一分配和一准备对象；最终参数变更/捕获后变更/不同 tool ID 借引用失败；跨 session/activation/intent 不可复用；等待期间取消、配置变更、provider 缺失、持久写或回执未知全部零执行；human fallback 显式签原一次许可，不伪造 reviewer 来源。业务 input 伪造 scope 字段不能取得权限。真实 SDK 的 ID/ALS 传播由另行授权的13场景探针验证，不能用默认自有回调测试替代。

## 当前核心与验证范围

`ReviewerOperationScopeBindings`先校验闭合7字段/schema/digest，再读取实际Admission的原pending投影并精确比较，才保留有限槽。私有metadata固定control_id/confirmation_ref/tool_call_id/request_ref四项；ScopeControl新增非RPC的`operation_binding`与借锁helper，原六种RPC不变。原pi-full/manager activation/SDK session/request_id/intent逐项绑定；同参重读仍fresh核验持久scope与authority，返回独立copy。

可信原操作的metadata漂移、未知核验与请求复用永久退役本地槽并撤原pending/permitted操作；首次伪造投影不撤未经核验的原能力。容量耗尽与失败槽均不淘汰。`scopes_for_prepared`仅给本地映射，不是authority资格；给Decision的`scope_current`取得服务锁，给Admission的`reviewer_current_borrowed`要求外层已持服务锁，仅读原映射及账户短锁，绝不反调Admission或获取服务锁。资格失效后恢复scope也不能复活旧binding。

新增58项加指定scope control/Admission/authority permit140项在同一次默认守卫运行中198通过，稳定三文件独立审查未发现剩余P1/P2。新组件没有改前行为，不伪造stub红例。临时真实scope/authority与fake process覆盖issue/consume锁内callback、永久墓碑和一次许可；锁spy不证明OS跨进程锁或SDK来源。证据归档`risk-operation-scope-binding`。

唯一性目前仅覆盖单Admission加单binder。现有File/Shell各有独立账本，未来factory必须共用同一账本/binder或另行审查跨bridge registry；不能各造一份map声称activation全局唯一。原桥requires_human=true未降低，绑定不签许可、不取得Writer、不执行。真人确认、实际execute到scoped prepare、JS/Python RPC组合、完整route/quality/input资格和Host lifecycle仍分别待验收，正式任务仍7/100。

## 可信共享账本注入

后续窄增量已给File/Shell bridge增加`admissions=None`可信构造参数；显式对象必须exact OperationAdmissions且activation匹配，Shell的限额也必须与该对象一致。FileAdmissionControl的`shared_admissions`仅在非None时把同一对象传给两桥并核验工厂返回身份，默认None保留原人工工厂签名。RPC或业务input不能注入此对象；没有复制、reset或重建账本，也没有安装reviewer hook或Host factory。

实际两桥的跨kind/捕获输入冲突、共同槽/bytes限额和一次许可由原同一账本约束。新增41项与指定关联176项在一次运行中217通过，四文件稳定独立审查无P1/P2；两桥改前不共享的真实红例和工厂异常边界两项红例均保留。证据归档`risk-shared-admission`。这是可信构造接缝，不代表整个Host已共用binder。构造仍先绑定File bridge，再调用Shell工厂；失败assembly没有rollback/重试保证，必须丢弃，不当成功Host使用。
