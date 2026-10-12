# Reviewer 私有作用域 RPC 接线

日期：2026-10-06。此页冻结 T051–T053 接线的局部接口与恢复语义。现有 manager 能力通道、共享 Supervisor mutex 和 ReviewerScopeStore 可复用；该组件尚未由 Host factory 构造，未启用产品自动审核，也不证明用户来源或 SDK 传播。模型工具/MCP 不增加作用域方法或 refs 参数。

## 身份与方法

控制器只接受已认证 manager 对原活动 host lease 的调用，复核 kind/running/generation、OWNER_KEYS 与构造时的 owner 快照、原 process alive。能力正文不能选择角色、activation、后端或人类来源。当前普通 RPC 的前缀转发并非 allowlist，组件必须精确分派下面六种方法。关闭阶段只允许退役，不开放新引用或核验资格。

| 私有方法后缀 | 封闭参数 | 结果 |
| --- | --- | --- |
| open | control_id、session_id | control_id、session_id、session_scope、state=open |
| allocate_intent | control_id、confirmation_ref | session_scope、intent_ref |
| allocate_request | control_id、confirmation_ref、tool_call_id | session_scope、intent_ref、request_ref |
| verify | allocate_request 的字段及 request_ref | current=true 及原三引用 |
| retire_intent | control_id、confirmation_ref | control_id、confirmation_ref、state=retired |
| retire_session | control_id、session_id | control_id、state=retired |

完整方法名前缀为 `ordinary_reviewer_scope_`。control_id 与 confirmation_ref 是可信适配器持有的32位小写hex随机幂等 nonce；SDK session_id 与实际 execute tool_call_id 为 ASCII `[!-~]{1,512}`。调用者不指定 session_scope/intent_ref，verify 必须同时匹配原控制、确认、tool ID 和该 ID 已取得的 request_ref，再核验持久表。引用通过私有通道传输，不进入普通摘要或异常。

activation_ref 从 domain=`reviewer-scope-session-v1`、manager_activation_id、host lease_id、grant_generation、control_id 的稳定摘要取32位；intent nonce 从 domain=`reviewer-scope-intent-v1`、activation_ref、confirmation_ref 的稳定摘要取32位。它们只是绑定私有幂等键，不自行证明确认来源。owner_nonce、账号、认证或秘密不参与摘要。不同 activation 不重用旧权限，公开 SDK session ID 不能替代私有 activation nonce。

## 分配与永久退役

服务 mutex 内先为原 control/intent 占槽，再取得账户短锁分配。控制最多128、意图/请求各4096，并受持久表总4096条限制；reserved/open/retired 及映射保留至 activation 结束，不淘汰后重新开放旧请求。调用结果未知时保持原 nonce 和待确认状态，重读只允许同参幂等重读，不换控制或 nonce 掩盖失败。同一 tool ID 得到稳定 request_ref，但下游仍须把最终捕获输入与它绑定到同一 PreparedOperation，防止重复 execute 生成新操作。

退役先不可逆改变内存资格，再按原 nonce 写持久墓碑。retire_session 可先于 open；retire_intent 可先于意图分配，但要求控制已取得原 session_scope。失回执后没有 refs 仍可退役原 nonce。持久退役失败不得返回 durable 成功，可按同 nonce 重试确认；任何迟到成功均不恢复内存资格。

为这个边界，Store 新增 `retire_session_activation(activation_ref)` 与 `retire_intent_confirmation(session_scope, confirmation_ref)`。它们在原账户排他锁内复用已分配行或创建仅 retired 的行，文件/目录持久确认后返回计数，不返回新增权限或 request。退役不依赖仍有效的 authority，但要求完整已初始化 scope 表与原账户根；缺失/损坏/容量或写入未知按现有错误保留，不自动 bootstrap。另一 session 的确认 nonce 冲突仍拒绝。

lock 顺序固定 Supervisor mutex → account 短锁；账户临界区不反调服务、SDK、网络或 Admission。后续 reviewer reserve/claim/commit 仍必须显式选择 scope_required=True，以同账户锁串行化 scope 退役与发送提交。commit 已持久成功后退役不撤销历史发送，也不释放未知预算。

## 当前证据与待完成项

Store nonce 退役新增22项加原 scope88与账户/scope35在一次默认运行中145通过。测试覆盖写后失回执、分配前退役、authority 不可用时退役、同 nonce 重读、跨 session 冲突、缺失根不初始化与容量墓碑。测试只使用临时账户、自有存储和假进程；两文件稳定独立审查未发现剩余P1/P2。

私有服务控制器已完成局部实现：`ReviewerScopeControl`、普通操作默认None的精确分派与closing窄增量，新增45项加原ordinary/admission/supervisor85项在一次运行中130通过，稳定四文件独立审查未发现剩余P1/P2。此新组件未采集前实现行为红，记录中如实保留，未用stub或collection失败代替。Host尚未构造它，activation结束时的自动持久退役尚未接线；传输超时仍不证明服务端未提交。

私有JS `createPrivateReviewerScopeAttempt` 已完成独立组件：每个attempt自己捕获一组control/confirmation nonce，construct零RPC，open/intent仅一次Promise，同工具ID在callback前占pending槽；同ID返回原request_ref，verify必须该ID已取得的原绑定。返回refs不含两个私有nonce。所有回复只接受闭合data属性，call返回非Proxy native Promise；超时、退役与迟到结果均不能取得新权限。isCurrent只有本地同步资格，不替代服务端authority核验。

retire同步撤本地能力并唤醒pending，已touch时仅自动排一次原control/session退役。清理失败首个drain固定拒绝，后续显式drain才可按同nonce再确认；并发drain共享一轮，没有后台重试或重新分配。drain只等本组件有界观察器和清理回执，不证明底层RPC或进程已物理停止；实际owner退役后再drain收集清理结果。新增59项与confirmed-intent126项在同一次默认运行185通过，稳定两文件独立审查无剩余P1/P2。初轮实际六项失败涉及退役后cached intent引用复活，修复为先核验资格再查memo，失败日志保留；此组件仍只调用fake RPC，尚未与Python服务组合运行。

真实 SDK 因果绑定、JS适配器与Python私有RPC的组合、scope/PreparedOperation 精确消费、Host factory、输入 token 资格、账号路线、发送承诺与终止证据仍须分别验收。关闭自动审核不代表这些目标已经完成；正式任务仍7/100。
