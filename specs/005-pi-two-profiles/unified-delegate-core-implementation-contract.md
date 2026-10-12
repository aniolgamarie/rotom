# 统一 delegate core 首个完整实现包

2026-10-11 Root。与 unified-delegate-integration-decisions.md 一起执行；不修改上游SDK/私有对象，不新增队列。实际旧v2 `DelegateController.prepare` 已有 idempotency_key→intent→physical request 映射，丢回执保留不完整状态，不需要另创物理ID分配器。

## 所有权与落点

唯一 executor 负责共享Python core、原Supervisor入口、实际Pi/Codex sender与现代Full自有extension/TK adapter。允许修改原 `model_delegate*.py`、`pi_delegate*.py`、相关schema/CLI/Skill、`official-delegate-{agent,stream}.ts`及新增现代worker/modern-owned package；共享recipe/manifest只由同一writer处理。Base普通权限/工具流程保持原逻辑；旧v2读取/已安装恢复资产保留。Root负责下述事务、授权和异常取舍。

## 状态记录与事务

保持已有v3 intent及其pending恢复格式不变。每逻辑run增加一个私有 `execution-v3/<run_id>.json`，在同一 `DelegationRuns._transaction` 的原Tree/instance锁内读取/修改。它是动作与原physical attempt的关联/累计预算记录，不调度任务。单文件原子replace保存一轮完整postimage，不添加第二多文件事务日志。

闭合顶层：schema_version=3、kind=logical-execution、run_id、origin、binding、budget、cancel_requested、actions、active_attempt_id、next_sequence。origin/binding沿原capture；预算来自可信控制面，模型动作不携预算授权。预算至少保存scope/account、calls/turns/input/output/cost的显式上限和累计known/estimated/unknown/reserved分量、原截止时间。金额采用固定整数单位或规范整数字符串，不用float；没有可核验来源的计费是unknown。

每action闭合保存action_key、request_digest、kind、sequence、state、reservation、physical_run_id、attempt_id、lease_id、native_action_id、receipt_ref、failure_code。状态prepared→sending→acknowledged/completed或unknown/rejected；未创建physical关联时ID为null。动作正文保留在已有私有intent，不放进status/log；正文摘要及resume token不输出公开DTO。physical请求/receipt仍由原v2和ExecutionStore拥有，core仅保存其原身份与引用。

执行顺序：原v3登记并核origin/binding → 同一core锁内核当前动作/预算/旧attempt状态并原子保存sending+预留 → 释放core锁 → 原DelegateController.prepare(idempotency_key=action_key)与start/steer/continue/cancel → 原关联结果持久化 → 通知。动作sending既包括可能发生的原prepare/Writer预留，不以尚未model-send断言所有副作用未发生。原prepare同key只能关联原intent，不完整原request必须unknown/blocked，不能创建第二allocation。

任何sender异常/ACK丢失：在原record内保持unknown/预留；查询原idempotency_key/physical事实作只读对账，禁止自动重做sender或退款。若core在写sending前持久失败，零sender；写后故障即便没看到start也保守unknown。已有完整terminal/receipt只能在原验证链通过后归并，同动作重复查询不发送。status/result/poll不修复注册pending、不打开后端、不刷新账号。

cancel先在core原子写cancel_requested、撤销尚未用动作，再调用原stop；terminate/资源释放依原lease证据。continue核原v2终止/回收/私有resume token和当前兼容授权，保逻辑ID，新的idempotency_key→新physical attempt，累计预算不清零。profile或source变化不自动迁移旧绑定；不兼容明确stale/recovery-required。

## 授权和模型发送

新入口只有真实Full-selected控制面创建。origin和binding由原host/可信UI/CLI/TK task scope产生，不采用模型自报host/task/role。worker只能报本lease的事件/结果/使用量，不能创建逻辑run或调整预算；status用户能力不能换成writer/initializer。每模型发送及每受管工具仍复用原当前grant、policy/cancel generation、scope、预算和WorkspaceLeases检查。

公开模型审查严格上限和AUTO OFF不变。普通委派请求的用量/计费缺失如实unknown；预算不足/缺必需授权字段失败关闭，不填默认无限额。不要凭物理回执将模型请求费用置0。

## 现代Pi worker

新增真正的固定现代worker入口，旧 `delegate-pi-main.ts` 的0.84.4及SDK实例方法改写不用于现代Full。复用公开Agent facade、原ModelRuntime initializer/受限scope和公开SessionManager；不覆盖SDK实例stream/active-tools等方法，不导入私有SDK模块。

允许给自有Agent facade增加显式受控initial messages；来自验证过的原public SessionManager上下文，模型不能选会话路径。用公开SessionManager写入Agent公开消息事件，串行完成持久保存后再发完成回执；resume token始终保留原私有owner处。新attempt公开恢复原兼容session后重新绑定原model/tool/系统约束，不沿用旧权限对象。

固定监督live-channel帧只含schema_version/request_id/action_key/expected_physical_run_id与已获准动作的私有输入引用。通过原child stdin/专用私有通道发送，不暴露任意程序/路径/信号目标。有界frame、严格请求匹配、单flight消息及固定事件序号；active steer调用原busy Agent，idle/unknown zero send。public API不能证明ACK时保留unknown，不用超时重发获取答案。

## Codex与TK

Codex基于现固定0.154.0公开app-server：原supervisor创建固定child、private native home/selectedmodel/权限参数，严格stdio请求/响应/事件限额与thread/turn/request匹配。初始化及thread/resume/turn/start/steer/interrupt由现公共编码器扩接真实transport；未知外部状态由原进程/lease与public事件对账，不解析TUI或调用私有guardian，不自动Pi fallback。

现代Full自有factory装配core并注册原选定工具，CLI/Skill用同一入口。TK adapter保留workflow/phase/evidence journal，只存core逻辑run/attempt/receipt引用，不另allocate/dispatch。Git worktree provisioner经过原maintenance/workspace准入，ordinary文件IO权威不替代这项Git写入准入。

## 验收与升级

一包完成生产接线与受影响默认测试，包括同ID冲突/一次发送、准备/发送/ACK各崩溃窗口、累计预算/unknown占用、role/单Writer、active steer与idle0、verified continue、query0、cancel迟到、原receipt终止核对、CLI/Pi/TK同core。只读fake sender不能作为产品完成；随后原Host/socket/SDK/Pi worker及固定Codex进程合成验证分层执行。

实际公共API不足、原producer/锁/顺序前提推翻、需改变上述schema/权限或两有效修复仍失败时升级Root；其余实现/检查/常规修复自行继续，不让用户逐步发继续。不得把不完整sender/新DTO注册模块单独当作此包完成，不发布candidate高级能力为current。

## Root 精确接口补充（2026-10-11）

1. 唯一可信预算配置为 `manifest.options.model_delegate.budget`，仅原管理配置/UI可信控制面能写；Pi模型工具/RPC action不接预算或origin/binding字段。闭合配置keys：`scope_id, currency, max_calls, max_turns, max_input_tokens, max_output_tokens, max_cost_microunits, per_call_input_tokens, per_call_output_tokens, per_call_cost_microunits, wall_seconds`。scope_id为原safe ID；currency只`CNY|USD`；金额整数微单位（1 unit=0.000001相应币种），其它限额exact integer正数，per-call不得超过总量。缺配置失败关闭，无无限/自行估价默认。此初期没有给Full启用预算默认值。

   `per_call_cost_microunits` 是用户配置的授权预留额度，不称provider实际账单上界。生产没有已验证计价上界时，每次发送保守占用整个尚可用金额预算；单次费用未知不释放该占用，因此后续自动付费发送blocked，除非原账单/已验证计量对账或新的明确授权。不能用usage乘未验证价格推退款。合成已固定零费用provider的测试可以由可信fixture明确提供计量oracle，不能将其混入真实provider资格。calls/output cap等仍核原provider/SDK发送参数；AUTO OFF和reviewer严格input gate保持。这是正确性边界，不以未完成计量假造多轮可用。

   execution的budget闭合keys：`scope_id, account_scope_id, currency, limits, totals, reservations, deadline_ms, cost_state`；limits用上述配置的有限amount字段（不含scope/currency/wall）；totals闭合calls/turns/input_tokens/output_tokens/known_cost_microunits/estimated_cost_microunits；reservations闭合calls/turns/input_tokens/output_tokens/cost_microunits；cost_state=`known|estimated|unknown|reserved`。费用未知保留原预留且单独状态，不填known0。原deadline首次登记固定，重连/continue不刷新。

2. Host从本次原Full manifest、store.owner、当前runtime/config/policy/workspace与真实principal构造origin/binding/budget。普通Pi模型工具的source固定`host=pi`、source_id取原真实SessionManager session ID；host activation只校验临时source_ref有效性，不作持久来源身份。CLI使用真实受管启动caller登记的CLI scope，不信任action里的host标签。TK使用控制面已有task/step注册引用，从原已验证descriptor/job中解析task/step/model/范围，模型不能新提交task_id/step_id。新RPC只接原schema3 `action`及不透明`source_ref`；source_ref须由同一manager私有表/lease generation/current validator登记，模型给随机/历史字符串失败。worker/user查询能力不能注册source或改预算。CLI caller registration使用单独内部原入口，不公开成模型tool/任意JSON可调用方法。

   binding沿原v3闭合字段；account_scope_id只根据实际已选择backend/provider/认证owner及原credential引用类别派生，不读/散列凭据值。逻辑预算始终绑原scope/原私有执行记录；切profile/source不清原账本，也不自动借新instance继续；不兼容显式stale/需要新授权，不建立一个看似同run的新零累计记录。

3. Pi resume使用server-owned随机opaque `resume_ref`映射到原session path、原native session ID及原attempt/来源/授权。不允许model/RPC指定路径。已核同一physical结束后，公开`SessionManager.forkFrom(oldPath, sameCwd, newPrivateSessionsDir)`保存完整历史到新attempt，保留旧文件和关联；新physical/native ID与逻辑run ID分开，不称native ID不变。正式1.0.1 d.ts公开forkFrom(sourcePath,targetCwd,sessionDir,options)、open(path,sessionDir,cwdOverride)与appendMessage；不调用其私有_persist等。不能以新实例open旧文件直接写回原结束attempt。若实际source/session格式不符拒绝，不自行重建相似历史。

4. 原physical prepare只用于submit/verified continue。message仅原active attempt steer，cancel仅原active stop，status/poll/result零prepare/发送。v3 intent存在但execution缺失时，查询返回`registered-not-started`且零写/发送；只有原授权动作入口在重新验证相同绑定/预算后创建第一execution postimage并持久sending，再进入原physical prepare。相同动作已有sending/unknown不得补发；不把不存在的关联解释成可退款或任意未发送证明。

补充：source_id不能采用会重启变化的manager activation作为持久幂等命名空间。首次submit的Pi来源取原真实SessionManager session ID；CLI由原受管CLI入口登记稳定的用户来源ID（保存在原私有来源记录，不接受模型自报）；TK取原受信task/step注册。activation/lease generation属于当前私有source_ref有效性校验。follow-up的origin保持原run记录，当前caller须通过同账号/原实例归属及原授权scope验证，不能靠传回旧origin JSON取得权利。只读查询不新注册/签发source_ref。重连需要真实原caller重新验证并绑定已有私有来源记录，不自动变成新预算scope。

现代source_ref的私有注册记录还需source_kind=`model-tool|cli|task-keeper`与原授权范围。model-tool即使连接principal旧role=user也仅review/investigate只读；implement、allow_workspace_write、worktree_root请求一律在原physical prepare/预留之前拒绝，零Writer。CLI/TK implement必须为真实可信注册scope并经原工作区/维护授权、role ceiling及policy验证；JSON bool或旧role=user不授权。原v2兼容语义不全局改写；现代入口在调用旧prepare前独立收窄范围，不向任意user能力公开写批准注册。

Codex公开app-server的turn事件不等于逐模型请求的发送前门控。实际stdio生命周期可实现和验证，但生产严格calls/input/output预算在逐发送计量未证明前明确unavailable；不以turn计数或事后usage冒充发送前约束。已有受管Responses转发入口仅在证明实际生产caller、当前授权、完整覆盖和原预算原子预留之后可复用；验收fixture或新增未审查proxy不构成支持证据。
