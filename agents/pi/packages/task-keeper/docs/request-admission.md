# 请求准入与故障域

Task Keeper 的自动恢复和受管任务在实际发送边界重新检查当前权限。配置中的 provider、model、accountBinding、quotaGroup、transportDomain、network、profile 和遥测路径仍由环境绑定，不从本机 provider 名推导策略。

`/orch doctor` 和无 job ID 的 `/orch status` 在 `effectivePolicy` 中展示当前生效的路线许可、功能开关、数值限制、预算和根验收要求。它反映用户策略与项目限制合并后的结果，不包含凭证或验证命令。

## 路线选择

恢复链按配置顺序评估候选。必需工具、上下文容量、路线自己的 thinking 映射、授权、受保护备胎要求、网络支持范围和遥测均是准入条件。更低价格或更大的其他模型指标不能抵消缺失条件。`/orch status <job>` 的 `routeAssessment` 保留候选拒绝原因与链顺序；未授权候选也有明确原因。

选择候选不等于已经预留预算和资源；SQLite 事务与实际 HTTP 发送前仍会重查。当前网络执行支持 direct，其余绑定必须通过对应适配认证才可启用。

## 长任务期间的变化

受管 child 的描述符绑定原项目目录、路线与有效配置摘要。后续工具调用与模型请求重新读取有效配置；配置改变后旧 child 不继续行使原权限。每次实际请求还重新核对额度遥测的账号、桶、来源、freshness 和余量，不能只沿用启动前的观察。

主会话自动续跑在 provider 请求开始时捕获执行身份，凭证解析后、实际 fetch 前重查 owner、epoch、会话/leaf、模型/profile、队列、未知工具状态、期限和共享冷却。自动轮次结束前发生暂停、停止或模型变化，旧请求不能通过改用另一个 endpoint 绕过检查。已经结束的受控 fetch 引用也不能重新变成普通 fetch。用户原本的正常请求不因此获得 Task Keeper 严格预算认证。

## 同父队列的公平排序

用户 Task Keeper 配置可设置 `scheduling.agingMs`（默认60000）和 `scheduling.priorities.inspect/fix`（各默认0，范围0–100）。例如 `{"scheduling":{"agingMs":1000,"priorities":{"inspect":20,"fix":10}}}`。仅已满足依赖及资源条件的步骤参与排序，持续就绪时间增加有效优先级；已运行的有界步骤不被抢占。该配置由用户层控制，项目层不能改写共享队列的排序策略。

启动或提交任务前配置这些值。非默认排序属于执行策略身份，既有任务仍按原策略身份检查；修改数值不会重置原预算或自动重开任务。公平保证限定在同父队列及持续可用资源等前提下。

## quotaGroup 与 transportDomain

临时额度错误按 `quotaGroup` 保存；网络/服务过载错误按 `transportDomain` 保存。两个维度使用不同的状态命名空间，即使配置 ID 相同也不会碰撞。一次请求遵守当前路线两类约束中较晚的 notBefore。

不同额度池遇到同一 transportDomain 故障时，共用该域的恢复许可；只有额度故障时，不会无故制造整个网络域的故障。不同网络域不因某域的网络错误被错误记为额度耗尽。网络实际重试继续受有限次数约束，额度等待不使网络重试变成无限循环。

故障可能在 child 启动后才出现。因此后续请求除了检查冷却，还需持有现有父执行的域许可，或事务性取得该执行的域许可。重复请求不会重复预留；竞争失败不会留下局部资源。许可在可证明执行已物理终止后结算；未知终态保留许可与账本，不能仅因为 lease 过期就放行另一个恢复者。

每次最终派发先在短事务内重新检查控制权并提交 `request-admissions` 记录，提交后立即调用 fetch，中间没有 await；网络与子进程 I/O 始终在事务外。该记录只证明当时取得派发授权，`provesSend=false`，不是实际发送或远端接收证明。取消先于该授权提交则拒绝发送；晚于已提交授权的取消按原请求的实际调用/终态对账。已授权但未发送不能计费，是否发出未知也不能仅凭授权记录退还预算或重放。

完整实际成功才用于更新对应故障状态；精确复用一份旧审查不会被算作新的网络恢复成功。备胎成功也不会清除需要保留的原额度事故预算。

## 证据边界

受管前台 fresh child 的真实请求预算仍以 SQLite 请求记录和实际 transport 为准。主会话目前提供同路线恢复及发送前控制，**不宣称主会话跨模型严格预算已认证**。背景/fork执行、其他协议/网络以及任意外部工具的保证仍按能力矩阵分别判断。

相关测试包括 `gap-g20-route-s.test.ts`、`workflows-recovery.test.ts` 的 fallback-skip/network 变体、`subagents.test.ts` 的 telemetry/transport 变体、`network-domains.test.ts`、`gap-g18-request-s.test.ts`、`http-transport.test.ts` 及实际 Pi RPC 回放。它们提供各自范围的证据；当前AC映射及语义审查分别记录；具体服务的实网认证不要求Qwen品牌，loopback证据不冒充实网证据。


## 受管请求的原生边界验收

两个实际 child 的最后许可竞争、SDK retry/压缩的允许与拒绝、四类流终态以及四个取消切点已有独立 loopback/SQLite 观察。测试切点在私有包副本中注入，记录源摘要，不在生产模块加入测试配置。发送前取消不能计为已发送；真实接收后取消不能退回已消耗许可。完整报告的 `matrixEvidence` 和 `expandedCoverage` 保存逐变体证据，不能由单个 SDK 主请求通过推断整个路径矩阵已认证。


## 暂停后的额度等待

已进入额度等待的受管任务会保存 quotaWaitPending。暂停或重启后，在候选未变化且执行已对账时，resume 保留原 incident、stageEnteredAt/deadline 和预算，把任务交回等待链重新选取当前合法路线。恢复控制权不会直接重跑上一次使用的备胎。候选变化仍走独立快照和验收重建流程；本字段不提高预算，也不代替请求 gate。

## 模型身份的证据来源

受管执行返回 modelIdentity，回执中的 observed 模型项注明 identitySource=client_configuration。它表示从实际 Pi 子端配置观察到的 provider/model/thinking。当前 adapter 没有读取服务端 SSE 的 model 字段，因此 responseModel=null；serverWeights=unverified 明确保留权重身份未验证。服务端返回不同 model 名称或不返回该字段，都不能用请求配置补造服务端身份。
