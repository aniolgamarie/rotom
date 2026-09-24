# 能力边界审计与当前交付范围

> 2026-09-14：当前功能设计已重订为TK-R2，见[唯一实施进度](../../../../openspec/changes/add-pi-task-keeper/implementation-progress.md)。本页旧71/76和P0–P3覆盖数字仅对应现有代码基线，不是新版完成状态。包内源码与旧测试计划尚未迁移；此设计整理不赋予新运行信用。


2026-09-14 当前状态：71/76，完整运行 822/822 通过；最低义务缺口 91，矩阵缺口 301。见 [本轮审计](testing/continuation-2026-09-14.md) 与 [当前 checkpoint](testing/runtime-progress.json)。以下 2026-09-10 内容保留为历史能力盘点，不替代当前执行证据。


审计日期：2026-09-10。后续工作的统一入口是 [OpenSpec 收口计划](../../../../openspec/changes/add-pi-task-keeper/closure-plan.md)。本文件描述当前事实，不增加功能范围，也不代替逐条验收。

## 1. 当前结论

**当前是有明确适配范围、已有大量运行证据的实现候选；还不是完整 P0–P3 验收完成的插件。**

- 最新完整运行：`2026-09-09T20-06-39-144Z`，777 passed，0 failed/cancelled/skipped，16,845条断言；摘要`925b21901eb27b7ab6bc6dff8e1b5b7eae7d3454606598c9f2d617ce0b2a7f7f`。
- 此后补充TK11重启测试、单元规则测试并修复报告入口的非法断言计数/状态校验；40项只读定向检查通过，当前源码已不同于该完整检查点。隔离运行被NETLINK_ROUTE权限拒绝；[Pi交接](../../../../openspec/changes/add-pi-task-keeper/pi-execution-handoff.md)逐项记录待实施与待运行内容。下列覆盖数字仍引用最后一次完整通过报告。
- 707项P0–P3义务中593项有最低证据、114项缺失；436项矩阵中123项有证据、313项缺失。两个视图不能相加，完整oracle/变体审计尚未完成。
- 历史任务71/76；F01–F04的实现差异现已处理并定向/全套验证，仍不能据此宣称所有规格义务关闭。
- W1首轮分流完成；详细经过、失败记录和本批能力边界见[执行记录](testing/continuation-2026-09-10.md)。

报告：[最新运行](../test-results/2026-09-09T20-06-39-144Z/report.json)、[初始审计基线](testing/closure-baseline-2026-09-10.json)。

## 2. 已实现能力及不能越过的边界

“有运行证据”均限定于下表及当前版本组合，不表示对应 Spec 的每个组合都已通过。

| 能力 | 当前实现及证据 | 明确边界 |
|---|---|---|
| 本地包与配置 | 单入口；默认禁用；用户绑定与项目收紧；隔离同步已有记录 | 本次没有部署到真实 Pi home；不维护模型账号或复制凭证 |
| 主会话长任务恢复 | 临时限流分类、Retry-After、持久等待、有限请求超时、暂停/停止、原生 continuation；真实 Pi loopback 测试 | 当前只支持同路线、非受保护主会话恢复；不是主会话跨模型调度或严格全局请求预算 |
| Qwen 相关验证 | 多服务错误 fixture、历史脱敏样本、长输入及工具修改后恢复的 Q1/Q2 证据 | 没有 Q3 实网认证；模型系列是验收对象，服务/账号/模型 ID 都是配置绑定 |
| 受管执行 | 锁定的 pi-subagents，foreground/fresh，显式 cwd，被动 reporter、模型/工具/身份检查 | 未开放 background/fork 子任务；会话 fork 继承预算不等于支持 fork 模式子执行 |
| 多 job 调度 | 持久队列、固定计划依赖、同父优先级/aging、资源原子占用 | 非任意 DAG 平台；每个父实例管理自己的会话/cwd 范围；不承诺跨父公平 |
| 跨进程协调 | 同一规范化 state root 的一个数据库，共享槽位和 quota 许可；真实十父会话测试 | 不同 root 相互独立；不是跨机器协调；owner 过期不证明 writer 已停止 |
| inspect | 固定一个受限 scout，随后独立范围审查 | 当前不会按任务动态生成零至两个调查者；parallelReaders 是执行容量，不是动态规划能力 |
| fix | 持续 worktree、基线、一个 writer、真实验证、required reviewer、回执；失败/取消现场保留 | 交付候选，不自动应用主树、push 或 merge；没有多 writer 自动合并 |
| 验证与审查 | 可信 checkId/argv；零测试/全 skip/未知计数检查；候选/验收输入失效；审查读取因果及精确复用 | 独立模型审查不是语义正确性证明；可信命令仍可能访问文件/网络 |
| 终止管理 | 受控工具、真实 PID/namespace 对账；验证命令使用 PID namespace 收尾 | bwrap 此处主要承担进程生命周期边界，不是完整文件/网络安全沙箱；不能覆盖未申明的任意外部副作用 |
| 多模型策略 | 受管任务的配置恢复链、一次质量升级、一次 critique/修订、共享原预算和 step 计数 | 无自动模型质量学习；不能推断策略比 direct 更好；没有统一预算管理任意宿主调用 |
| 请求硬上限 | 受保护 child 的实际 fetch gate、SDK retry/压缩计数、unknown reservation、重复结算 | 未计量的父端辅助生成拒绝执行；普通主会话和任意插件请求不在此硬保证内；完整请求矩阵待验 |
| 事实与呈现 | 实际Outcome/上下文/状态，固定工作流EvidencePacket和提议登记/派发复查 | 提议不等于执行成功；不能把库测试替代产品层证据 |
| 共享目录与writer上限 | 声明目录的canonical资源与原子争用；0禁止受管writer，正值单writer | 只管理同state root中的已声明共同根，不推断任意外部文件访问 |
| 诊断重规划 | 可选受限scout诊断插入下一writer之前，原job持久限值/计数 | 默认关闭；仅诊断后修复模板，不含通用DAG/在线Advisor |
| 维护与报告 | 迁移/回退保留业务事实；失败运行留档；报告区分设计、最低证据及矩阵 | 不自动清理数据库/候选；报告通过不自动完成部署或全部阶段认证 |
| 效用评估 | 全部启动项、失败/等待/取消/unknown 成本的离线报告格式与校验 | `evaluation-report.ts` 读取数据生成报告，不执行评测任务；11.6 尚未完成 |

可追溯代码：[入口](../index.ts)、[固定工作流](../src/orchestration/workflow-plan.ts)、[任务服务](../src/orchestration/service.ts)、[主会话恢复](../src/reliability/recovery.ts)、[受管 adapter](../src/adapters/subagents.ts)、[验证执行器](../src/verification/runner.ts)。运行证据的实际 file/name/层级见 [runtime-case-evidence.csv](testing/runtime-case-evidence.csv)，不由本表新增信用。

## 3. 初始审计差异与后续处理

### F01：通用提议准入未接入产品执行路径（初始发现）

**现状：已接通并验证。** 真实`decisions/propose`入口、Packet、Ledger及原step intent关联见[F01记录](testing/w2-f01-design-2026-09-10.md)。以下保留初始发现，不能继续当作当前未实现项。

- 原依据：设计 D2/D3，evidence spec 的 Two stage authorization and freshness，原任务 2.4/9.1/12.1。
- 事实：`DecisionLedger` 注释为未来 Advisor 准入；生产入口和 TaskService 没有消费它。`kernel_task` 只有 inspect/fix/status/pause/resume/stop，不接受 advance/verify/request_finish 提议。`/orch decisions` 当前走通用状态查询，不能视作完整决策账本查询。
- 现有的模型工具权限、固定流程、最终验收确实运行；**缺的是通用 StepProposal → 双重准入 → 同一 dispatcher 的接通**。
- 后续：先确定固定工作流内的最小连接，禁止再造 dispatcher、在线 Advisor 或任意 DAG。若选择只保留库，必须显式处理原 Spec 的未完成要求，不能直接归入 P4、标 E 通过。
- 代码：[decision-ledger.ts](../src/evidence/decision-ledger.ts)、[commands.ts](../src/contracts/commands.ts)、[index.ts](../index.ts)。G10 的12项 E 缺口先处理这个边界，不能靠夹具调用独立 ledger 冒充产品入口。

### F02：共享可变构建目录没有完整声明/执行连接（初始发现）

**现状：已接通并验证。** `verificationBindings.*.sharedMutableDirectories`及实际争用/漂移拒绝见[F02记录](testing/w2-f02-design-2026-09-10.md)。只协调声明的共同真实根；未声明/不同state root/插件外程序不在保证内。

- 原依据：设计 D4、Shared write resource exclusion，原任务 8.4，SCH-009/TK05/TK06。
- 事实：canonical repository/worktree 身份和该 workspace 的 writer/验证排他已实现；配置没有共享可变目录声明，固定计划也没有把这种声明转换为 resource demands。
- 后续：在用户可信绑定中定义需要保护的共享目录，规范化后交给现有原子资源系统。只管理显式声明的资源，不扩展为文件系统访问推断或分布式锁。
- 不能声称任意外部构建缓存、输出目录已被协调；默认单 verifier 或单 active job 也不能代替这项声明。
- 代码：[config.ts](../src/config.ts)、[workflow-plan.ts](../src/orchestration/workflow-plan.ts)、[child-reporter.ts](../src/adapters/child-reporter.ts)、[worktree.ts](../src/workspace/worktree.ts)。

### F03：writersPerJob 接受了值，却未参与运行时容量控制（初始发现）

**现状：已修复并验证。** 0禁止受管writer，正值有效容量为1；计划、adapter和child检查及doctor语义见[F03记录](testing/w2-f03-2026-09-10.md)。下述无消费者结论仅属于初始版本。

- 原依据：项目策略只能收紧、资源上限，原任务 4.2/8.4。
- 静态检查发现该字段只在 schema/default/合并中出现；实际 writer 容量固定为1。只读计划探针确认 `writersPerJob=0` 被接受，生成的计划仍含 implement writer。探针没有执行命令、创建 job 或写入候选。
- 这不否定已有的单 writer 排他，但**不能把 writersPerJob=0 当作有效的禁写开关**。
- 后续：明确并落实零值行为；不支持的取值应明确拒绝或显示实际收紧结果，不能接受后无声忽略。不因此实现多个 writer。
- 代码：[config.ts](../src/config.ts)、[workflow-plan.ts](../src/orchestration/workflow-plan.ts)、[child-reporter.ts](../src/adapters/child-reporter.ts)。

### F04：semanticReplansPerTask 不是已经接通的重规划能力（初始发现）

**现状：已实现有界模板并验证。** 可选`features.semanticReplanning`默认关闭；启用后诊断→修复实际改图，TaskSpec封存上限且原计划持久计数，见[F04记录](testing/w2-f04-design-2026-09-10.md)。不是通用规划器。

- 原依据：设计 D7、原任务9.7；v6 保留一次重规划上限。
- 事实：配置接受该字段，但生产代码没有读取它来计数或执行重规划。现有 semantic repair/critique/cascade 使用固定流程重试和已有计数，不能因此称为完整的“重规划”。
- 后续：先给出一次重规划的触发、合法输出和计数契约，再在原范围内选择最小实现；或显式校正原任务的交付声明。不能为了这个字段引入通用规划器。

F01–F04 是**原需求的实现/对齐工作**，不是四项新产品需求。详细整改纳入 W2。保持原历史任务登记可追溯；当前能力是否完成以本审计和收口结果为准。

## 4. 哪些不能由现有测试直接推断

`compilePacket`/`DecisionLedger`已通过F01连接产品路径。`chooseRoute`、`projectProgress`、`capabilityStatus`仍有独立模块/测试，不能为其它生产消费者直接借用运行信用。生产确实通过 `advanceWait/routeRequirements`、`describe/contextEvidence/StatusPublisher`、`inspectRuntimeProfile/preflight` 实现对应的一部分行为。

因此，库的 U/S 通过不能为另一条实际实现自动提供 A/P/E 信用；同样也不能因未调用这个库就断言整个路由/呈现没有实现。W1 必须逐项核对真实调用链。这里不要求为复用库而无目的重构。

两个尤其需要澄清的矩阵边界：

- `parent-helper.allowed` 的**原计划**已明确：没有预算接口时应拒绝该受管 helper，并验证独立普通请求可用。无需为了名字里的 allowed 自动增加 helper 支持。
- 当前 telemetry 是同步的用户文件读取。R02 的异步 telemetry 边界应先映射实际可达路径；不能在测试中虚构一个 await，再将其当作产品认证。如果原要求确实需要新的接口，记录实现依赖。

## 5. 固定支持组合与本轮不扩展项

当前基线：Pi 0.84.4、Node 24.1/Linux；受管模式使用本包锁定补丁的 pi-subagents 0.63.0。生产 workspace/VerifyRunner 的进程收尾和隔离测试需要可用的 bwrap/user/PID namespace。普通主会话恢复不以 pi-subagents 为启动必需依赖。

Provider/model/account、endpoint、profile、检查命令、quota/transport 归属及目录仍为配置；版本/补丁是需要实测的兼容性依赖，不是任意改一个环境参数就能获得的保证。

默认不开展：background/fork 子执行支持、主会话跨模型严格总预算、HTTP/HTTPS/SOCKS 新 transport、在线 Advisor/学习路由/narrator、任意 DAG/多 writer/daemon、跨主机协调、新模型后端或无关本地插件适配。已有明确不支持场景仍测试拒绝；原 Spec 要求成功而尚未实现的路径仍保持未完成。

## 6. 实网与独立遗留

不能把“非 L 层”全部称为离线工作：VAL-005/VAL-007 各自的 A/E/L 共6项都涉及绑定的真实服务语义；其中 V 报告规则可以离线审查。另有11.6的固定任务策略对照，没有包含在“2项 L”这个数字里。

真实 Qwen 验收需要显式 profile、路由/模型/账号引用、总请求上限和 deadline、固定合成任务与受控注入点；不得主动耗尽真实额度或用其它模型成功替代。效用评测应预先冻结任务清单/样本分组和成本记录，不能不断换样本追求好结果。

另列而不混入功能扩展：旧广域 Lua `pi_spec.lua` 未全绿；此前真实 Claude 配置误写尚无可靠原始副本可恢复。相关经过见[实现状态](implementation-status.md)。本次未运行同步、未改真实配置，也未把这些历史问题标记解决。

当前W2原15项最低证据缺口已补齐，但不等于所有领域变体审核完成。T85的E证据是原分阶段设计允许的安全契约夹具：合成费用结算输入＋真实Pi消费者；不是在线Advisor调用/计费路径的认证。





最新W3进展：生命周期/重启/deadline第一批通过，并修复确认终止后ACK等待未结束导致后续额度恢复卡住的问题；完整记录见执行记录末尾和I82。
