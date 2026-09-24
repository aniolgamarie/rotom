# Implementation decisions

The implementation follows OpenSpec `add-pi-task-keeper`, the user's Task Keeper v6 bundle,
ADR 001–019 and reference identities S1–S26. The test plan was reviewed before implementation:
56 requirements, 126 scenarios and 102 fault obligations, with independently observed results.
Runtime support must not be inferred from these counts.

## I01 — Runtime and storage

Use Node's bundled `node:sqlite` DatabaseSync with short synchronous transactions; no network
or asynchronous callbacks inside a transaction. Initial supported Node major is 24, minimum
24.1.0; test and record the actual Node/SQLite versions. There is no hidden native npm driver.
The initial probe on Node 24.1.0 reports SQLite 3.49.1. This is a storage availability probe,
not a claim that crash recovery, concurrency or a Pi adapter is certified.

Reason: ADR 011 / design D3-D4 need local cross-process atomic resource ownership, without a
daemon. Built-in SQLite reduces installation coupling. The package's runtime range is an
explicit dependency contract; provider, account, transport and model remain configuration.
Alternative: an external native SQLite driver requires its own ABI/build and packaging matrix.
Revisit if the supported runtime range changes. Reference: Node SQLite API and v6 ADR 011.

## I02 — Test evidence before certification

Tests register assertions using stable scenario/fault IDs and levels U/S/A/P/E/L/V. A test
result never certifies a level it did not run. Required scopes with no implementation or live
binding remain pending. U/S expectations use hand-authored facts and independent action logs.
Real SQLite, process barriers and transport receiver counts are required for stronger claims.

## I03 — Pi dependency boundary

The parent extension is the only automatic entry. Core TypeScript imports no Pi APIs.
Pi 0.84.4 is the initial development SDK candidate, not an automatic compatibility certification.
pi-subagents is not a startup dependency for interactive recovery. Its adapter will be loaded
only for an enabled and certified managed workflow. No other local plugins are required.

P1 must establish a durable continuation identity and termination coverage. Public request
payload hooks are not treated as hard request gates (v6 §12, S5). Unsupported controls stay
disabled until their actual calling paths have passed the required tests.

## I04 — Differences from the reference runtime

The source bundle cites pi-subagents 0.66.0. The installed candidate used here is 0.63.0,
so public event delegation, preflight, fresh context, explicit tools/extensions and result
envelopes were checked against that version and exercised by actual Pi parent/child processes.
The original source index is retained verbatim in `reference-sources.json`; its historical
verification notes are not statements of compatibility for this implementation.

Three narrowly scoped compatibility changes are reproducible with `prepare-subagents.mjs`:

1. Missing required tools must abort the child before a model request. Pi catches lifecycle
   callback exceptions, so throwing alone was insufficient. A broken-reporter test records zero HTTP sends.
2. External recovery ownership bypasses native 24-hour model exclusion only inside its
   AsyncLocalStorage scope. Ordinary concurrent calls keep their original exclusion policy.
   The owner scope also refuses unbudgeted parent helper POSTs. The shared scope is anchored
   by a global Symbol because Pi's loader and native imports can instantiate the module separately.
3. An event probe identifies the actual loaded delegation listener. Matching a different
   installed package on disk is not proof that the listener receiving a request uses that package.

The patch is confined to this package's local dependency tree; it never patches a global Pi
installation automatically. Reviewed files and the active entry are checked against a hash lock.
Bundled guarded agents disable the native heuristic completion guard and declare custom mutation
tools. Task Keeper's snapshot, actual checks and independent review determine acceptance.
This avoids an extra LLM intent arbiter and prevents heuristic assumptions about custom tool names.

## I05 — ADR implementation map

| Original ADR | Implementation and evidence |
|---|---|
| 001, 002 | One `index.ts`; independent interactive adapter and conditional subagents adapter. |
| 003, 010, 011 | SQLite owner epochs, durable intents and process reconciliation; real C0–C5 kill tests and shared quota contention. |
| 004, 014 | Native execution result and TaskReceipt are separate. Backend errors survive in artifacts and grouped parent-visible facts. |
| 005 | Initial TaskSpec retained; candidate snapshot changes invalidate checks. Explicit acceptance-input approval increments the version without resetting counters. General root-goal/policy replacement remains a release gap. |
| 006, 007 | Fixed workflows and programmatic projections; no online Advisor or additional model reporter. |
| 008 | One guarded writer per workspace; private Git snapshot object store retains baseline and patch without changing user refs. |
| 009 | Gate at actual fetch attempts, durable request reservations and unknown accounting. Unsupported main-session strict paths remain disabled. |
| 012 | `evaluation.ts` keeps all starts, unknown outcomes/costs and grouped holdouts separate. Live efficacy is not established by fixtures. |
| 013, 019 | Strict schema and monotonic project restrictions; no project-owned executable/account/network expansion or switch to disable invariants. |
| 015, 016 | Pure RecipePolicy; one dispatcher; finite semantic repair, one upgrade and one critique/revision under the same counters. |
| 017 | Optional critic may be skipped for required reserve; acceptance reviewer still reads the final candidate and check artifacts. |
| 018 | Progress projection cannot modify TaskReceipt; status rechecks the current candidate before showing a receipt as current. |

S1–S5 guide runtime contracts and were compared with the pinned local sources. S6–S9 are not
treated as universally compatible service APIs: the first telemetry adapter reads an explicitly
bound, private normalized observation file and validates its account/bucket/source/freshness.
Its producer is environment-specific. No credentials or remote usage API are hardcoded.

S10–S26 inform bounded escalation, evidence handling, coordination and evaluation. This code
does not import unpublished research implementations or claim to reproduce paper-level gains.
L1 controlled contracts, L2 replay and L3 live grouped evaluations remain distinct in reporting.

## I06 — Storage and verification limits

Config schema version 6 and database schema version 2 are separate domains. Schema 1 requires explicit
offline maintenance; the registered 1→2 migration adds maintenance history while preserving all business
tables. A durable maintenance fence, hash-bound backup and business-fact digest protect interrupted
upgrade/rollback. Active owners, new business facts and corrupt backups block maintenance. See
[state-maintenance.md](state-maintenance.md). Unsupported future schemas and corrupt/missing initialized
databases remain errors rather than new stores.

Pinned acceptance artifacts are independent of native transcript cleanup and are currently retained
indefinitely. No automatic workspace or database deletion is implemented. VerifyRunner now uses an independently checked PID namespace for the verifier and its descendants;
see I12 for the explicit Linux dependency and scope. Verification commands, environment, script
inputs and test count conventions are user bindings. Unknown termination or test counts still
prevent acceptance; filesystem/network access of trusted commands is not sandboxed by this runner.

## I07 — Sync integration finding

Isolated Pi generation exposed a pre-existing formatter defect: JSON null decoded to `vim.NIL`
was serialized as the invalid token `vim.NIL`. The focused fix serializes it as `null`, with a
round-trip regression and full isolated package sync. Runtime test reports are excluded from
resource sync; user binding/auth/state sentinels are checked byte-for-byte.

The older cross-tool `contract_spec.lua` also revealed a separate test isolation defect: it called
real sync targets with `allow_in_tests=true`. Its return-contract case now uses a fake target,
and the Claude writer refuses real-home writes whenever `ai_test_mode` is enabled. This is a
test safety repair, not a Task Keeper provider/config feature. The incident and recovery status
are reported separately to the user; no claim is made that the pre-incident Claude file was restored.

## I08 — Test isolation and assertion provenance

All package test commands now enter verified bubblewrap filesystem/process/network namespaces. Real home is hidden, the repository is read-only, and test results are copied out after the sandbox exits. There is no unsandboxed fallback. Report discovery and per-ID assertions distinguish executed evidence from shared test-title labels; old aggregate records no longer certify every named ID.

## I09 — Current service error evidence

The original v6 references are unchanged. [Qwen fixture provenance](qwen-classifier-fixtures.md) records current official error semantics and their difference from the historical usage-pressure interpretation. Service-specific rules remain configuration. The real Pi multi-service fixture exposed SDK loss of top-level error codes; bounded redacted HTTP error lookahead preserves these facts while forwarding the original bytes to the SDK.

## I10 — 长任务准入与独立故障域（2026-09-08）

补测发现启动前遥测不覆盖后续请求、transportDomain尚未进入等待协调、可选检查旧成功可掩盖新失败，以及错误分组缺完整ID索引。修复这些实际行为；保留环境参数化、unknown占用、必需验收和事实/claim区分。主会话自动请求增加凭证解析后守卫，受管/交互执行共享网络域许可；字段与出处见 `request-admission.md`。这落实原ADR003/004/009/010/017/018与D5/D8/D9，不扩大未认证的协议、后台执行或主会话严格预算范围。

## I11 — 效用报告需要独立启动清单（2026-09-08）

仅接收结果列表无法发现调用者在输入前过滤失败，因此离线报告命令要求独立 `startedRunIds` 并核对全量集合。library未提供清单时明确 `startInventoryVerified=false`。issue/snapshot与family共同检查留出污染，等待、基础设施失败和unknown成本单列；shadow不能被填成已验收结果。真实效用仍需11.6的固定绑定试验，合成报表只证明统计与声明边界。


## I12 — 覆盖脱离进程组的验证后代（2026-09-08）

普通 process-group kill 不能覆盖 setsid 后的孙进程，已通过真实持续写入者复现。可信验证和工作区辅助操作改由 Linux bubblewrap 的独立 PID 命名空间执行。父端核对命名空间、祖先链、PID 启动身份及控制通道 nonce 后，在最终 owner/取消检查通过时放行命令；命令不继承控制通道。命令留下活跃后代时结果失败，命名空间终止覆盖后代；缺 OS 证据仍为 unknown。此依赖只用于实际需要外部验证/工作区操作的功能，provider/本地插件无新增绑定。bwrap 路径可配置，二进制及监督器源码摘要进入验收输入身份。文件与网络副作用仍由可信 check binding 约束，不宣称此 PID 监督是文件/网络沙箱。

保留的工作流失败暴露另一竞态：对同一 `/proc/pid/stat` 分别读取身份和状态，进程在两次读取间被回收，已观察的 zombie 被回退成未终止。修复为一次内核记录读取，并在监督器内锁定第一次可靠终止事实。`process-identity.test.ts` 重放 Z→ENOENT，`cases-g13-p.test.ts` 覆盖普通/脱离后代及最终准入取消，实际 Pi 重复验证和完整工作流继续验证。依据原 ADR003/008/010 与 T16/T41/T42/T52，不用退出码代替外部工作覆盖。

## I13 — workScope 累计额度与运行时内容身份（2026-09-08）

仅保留 request 预算仍允许模型通过新 job 重新取得语义尝试和 step。新增有限 jobs/semanticAttempts/dispatchedSteps workScope 上限，事务内检查，取消和 fork 不退回计数。沿用原 ADR009/015/016 与 T30/T72/T80，独立用户新会话仍建立独立责任范围。真实 kernel_task 连续提交验证了拒绝信息、仅一个持久 job 和一次 writer。

Pi 0.84.4 的 CLI 是导入 stub，单独哈希不足以固定执行逻辑。运行时认证现在同时哈希 bundle 下全部普通文件及相对路径，拒绝缺失、增加、修改或软链的 chunk。范围仍是该候选分发物；不将其扩展为其他版本、协议或插件集合已认证。`runtime-identity.test.ts` 保持 CLI 字节不变而修改 chunk，确认旧认证失效。


原生工具复核发现 Pi `find` 的 abort 分支在 `fd` close 之前就拒绝 Promise；受控 `fd` 忽略 SIGTERM 的测试证明返回错误后进程仍活着。InteractiveAdapter 将该错误保留为外部生命周期 unknown。child reporter 记录进行中的 grep/find 外部工作，find 失败不清除；父端和恢复入口即便看到 reporter 已退出，也不能仅据此释放占用。缺少这一覆盖字段的历史观察同样不能证明终止。`native-tool-termination.test.ts` 与实际 pi-subagents `cancel-find` 变体覆盖该边界；普通完整工具结束继续按正常路径处理。这是保守保留事实，不宣称已取得未观测 fd 的终止凭据。


## I14 — 分类来源与 Q1/Q2 实现边界（2026-09-08）

恢复 spec 要求保存 notBefore 来源和不确定性，原有分类结果只有最终 retryAt。补上类别判断来源、配置规则索引及两个独立服务时间；未知类别、未知执行和缺可信 reset 的窗口保持不确定，旧记录不补造新字段。分类器同时对原始错误 code 脱敏。实际 Pi 回放核对有/无窗口时间、认证、上下文和未识别错误，后者阻塞且 resume 不增加请求。

test-plan.md §6 明确 Q1/Q2 不需真实账号，Q3 才验证当前服务绑定。因此 6.1 的分类契约和带来源多配置 fixture 完成，与 7.4/13.5 的实际环境认证分别登记；没有把文档来源/loopback 响应标成 service-origin，也不因尚无第二条实测路线阻塞通用实现。原 v6 与冻结设计基线未改写。


## I15 — 原生并发请求与可复现发送切点（2026-09-08）

两个实际 Pi child 共享最后一个 workScope 许可，在环境绑定的凭证命令屏障之后共同竞争。独立接收端只看到获胜者，SQLite 仅一条已发送 request、used=1/reserved=0，失败者保留 BUDGET_DENIED。该测试揭示 Pi TypeScript loader 的并发动态导入会给另一调用者未完成的模块；adapter 现在先共享进行中的导入 Promise，再调用 loader，所有 await 后仍校验原 owner。

真实 SDK 的 before-gate/after-reserve/after-recheck/after-receiver 取消测试，在一次性包副本的精确位置注入屏障并调用原生 ctx.abort。测试保存原始/注入源码摘要，生产 reporter 没有测试后门。前三类接收端为零，已预留且未发送的请求结算 not_sent；接收后取消保留 sent/used。完整、流内 error、截断和超时另用实际 HTTP200 流测试，HTTP 状态不能充当成功终态。SDK retry 与压缩同时有允许/预算拒绝对照，均核对请求级账本。这些证据限定于受管 foreground/fresh/direct chat-completions 路径；其他请求路径和完整矩阵仍分别验收。


## I16 — 迟到事实不能继承旧 owner 的控制权（2026-09-08）

新增的接管时序测试在 worker 结果返回前撤销旧 owner，并建立新 owner；原实现的迟到回调更新 job 后才碰到 CONTROL_REVOKED，产生未处理错误。TaskService 在外部等待后先核对 owner，旧回调只固定 `late-execution-results` 及工件，不更新新 owner 的 job/plan、不推进下一步；旧控制器 dispose 同样不能暂停新 owner。scheduler 的完成/对账更新在结算事务内核对 owner。迟到记录在 status 的 `lateExecutionResults` 可查询，保留原 epoch、intent 和工件，不自动变成验收。未对账的 step 占用仍保留，不能因为有迟到返回就假定它已安全接管。


## I17 — 审查复用同时绑定 Task Keeper 自身实现（2026-09-08）

只比较 Pi/执行器版本仍可能复用旧版 Task Keeper 审查器产生的结果。新增自身源码身份，覆盖入口、src、agent 定义、包清单与配置 schema；文档和测试不进入运行身份。父端描述符与 child 实际身份必须一致，每次 child 准入及主会话恢复快照核对已加载源码未被热改；发生变化要求重载。ReviewCache 的 runtimeDigest 纳入该身份，因此更新报告器或审查校验逻辑使旧缓存失效。单独的 P1 包不因缺少 managed agent 文件或 pi-subagents 而被此检查阻塞，实际 managed preflight 仍核对其所需文件。


## I18 — 当前验收必须仍有完整工件与输入（2026-09-08）

真实工作流回归先取得 COMPLETED，再删除必需测试工件；旧 status 仍返回 receiptCurrent=true，已保留失败运行。查询现在核对必需通过项的工件身份、内容摘要和来源，并比较当前验收输入；丢失或篡改时展示 BLOCKED/receiptCurrent=false，历史回执不改写。测试恢复原始字节后同一事实重新可查，期间零新增模型请求。已失败的回执仍保留原阻塞原因，不误改成“通过证据丢失”。

验收输入全局包含 Task Keeper 自身源码身份，检查应用于每种受管步骤的起点；校验前修改输入通过已有 approve-checks 流程重新授权，worker 运行中产生的候选仍先按原顺序固定。另一个实际 Pi 测试完成任务后重启到源码身份不同的包，确认旧工件仍在、候选未变，却不能宣称旧回执适用于新验收实现。热改源码同样阻止旧控制器新增派发/快照操作。


## I19 — 当前 owner 核验迟到验证，避免重复副作用（2026-09-08）

对照 T71，同一验证已完整执行而 owner 在回执前被替换时，不能因为计划仍为 running 就盲目重复执行。显式 resume 现在核对迟到工件的 intent/job/epoch/snapshot、原始内容摘要、验证项身份、PID 命名空间与物理退出；再在新 owner 下捕获候选，重查控制 epoch、输入、binding 与实际环境摘要。仍匹配的通过结果由当前 owner 重新固定并结算原步骤，计数不重置、不增加一次验证执行；其他必需步骤保持 pending。已确认结束但输入失配的结果只保留为待重新验证，不能成为通过证据。缺失/损坏/外来进程身份继续保持 unknown。

`late-verifier.test.ts` 在真实受监督构建屏障期间接管，独立检查进程退出和副作用文件，覆盖工件缺失、错误 epoch、恢复后采纳及已耗尽模型额度时的本地继续。job 保存现在把 owner 校验与写入放在同一 SQLite 事务中。此处只扩展迟到验证的对账；迟到 native worker 与工作区创建的其他采纳分支仍按其各自证据条件处理。


## I20 — 主会话恢复与受管工作流共享同一实例（2026-09-08）

同时启用两项功能的真实 Pi 验收暴露：P1 仅允许自身扩展，P2 又以 global fetch 指针相等判断父 helper gate；因此组合配置分别发生恢复不启动和 PARENT_HELPER_GATE_CHANGED。P1 现在额外认证受控启动器的顺序“锁定 pi-subagents → Task Keeper”，逐文件核对必要依赖；额外扩展和未测试顺序仍拒绝。runtime profile 在后续快照重新核对。

HTTP observer 维护仅由自身包装器登记的 delegate 链，确认原父 helper guard 仍覆盖转发；未知包装器不给信用。处于受管 helper scope 的请求先进入该已确认的内层 guard，不污染主会话 lastResponse/请求观测。实际模块/接收器测试确认 helper 零发送、主会话观测零污染，正常请求仍可完成。新增 with-subagents Q2 和 combined-features 工作流均从失败变为通过，未修改全局 Pi 或其他本地插件。


## I21 — 模型工具回复继承真实用户轮次的控制权（2026-09-08）

状态回归证明：用户通过命令暂停后，旧模型回复仍可调用 kernel_task resume。现在把真实用户轮次授权绑定到原生 assistant tool-call ID；用户暂停/停止、终端人工输入及会话生命周期变化撤销旧授权，写控制调用消费一次性身份。新真实用户指令、明确的主会话 resume 或已验证的持久等待恢复可建立新授权；内部消息不会自我授权。只读 status 继续可用。规则不依赖模型自述来源，也不增加用户重复确认。

P1 另支持明确绑定本包 kernel_task 的父 profile，实际同实例验收覆盖“模型提交一个 job → 父请求限流 → 原 continuation 恢复 → 原 job 独立验收”，确认不重复提交/写入。为保持工作树写入由调度器控制，父 profile 中 kernel_task 不能与直接 write/edit 混用；额外只读文件工具仍按原规则判断，错误来源的同名工具不取得覆盖。


## I22 — 实际模型回复与验证完成的双向控制竞态（2026-09-08）

model-control-race 用独立 HTTP 屏障保留旧父模型回复，真实 /orch pause 生效后才交付 resume tool call；验证拒绝旧调用、job 仍暂停，随后真实用户 resume 可以完成原 job。中断或长度截断的 assistant 结果不会产生写控制授权。

R10.stop 两个顺序分别在真实验证运行中停止，以及验证物理结束后、父端处理回执前停止。后一个切点仅在私有包副本注入有来源摘要的 await 屏障。两种顺序均保留候选和实际验证事实，取消结果为 CANCELLED，后续 reviewer 零调用且资源释放；晚到的 passing verification 不会逆转取消。逐变体断言已登记到 expandedCoverage。


## I23 — 自动恢复的原生工具也需要当前授权（2026-09-08）

真实 Pi 在自动恢复请求被 HTTP 屏障保留时收到用户 pause；旧响应随后请求原生 write，旧实现仍落盘。新增 tool_call 准入，自动轮次必须具有当前真实用户授权及当前恢复 owner/intent/profile；原生助手结果中完整 toolUse 才产生授权。被拒绝的后续模型请求标记为 controlRevoked，原始拒绝仍进 native-errors，但不会替代原额度故障、误阻塞后续明确 resume。确认同 session 的原执行终止后，记录实际 leaf 供用户安全恢复；异 session 的 idle 不能证明原执行终止。

pause-late-write 回归确认暂停窗口零写入、零额外 HTTP；用户明确恢复后只执行一次写入且保留原 incident 责任。另有异 session 终态的状态测试，保留 unknown intent 与占用。

## I24 — 恢复控制器的迟到写入也受 owner fence 约束（2026-09-08）

canary 回调可在旧 owner 撤销、新 owner 建立后返回。恢复主记录的保存现在在事务中核对 owner；迟到记录独立保存在 late-recovery-records，不更新新 owner 状态或旧 UI。真实执行的 ack/termination 事实仍保留。状态测试覆盖接管后迟到 canary，status/audit 展示迟到记录摘要，不能把它们当作当前继续权。


## I25 — 身份标记在 WAL 就绪之后发布（2026-09-08）

443 项全量运行保留了一次 database is locked 失败：独立观察连接看到身份标记时，初始化连接尚在切换 journal_mode。现在先确认/建立 WAL、设置同步级别，再发布身份标记；已处于 WAL 的连接不再请求模式切换。首次并发切换只对 SQLite BUSY/LOCKED 作有界等待，其余错误原样失败，不重建数据库。

真实进程测试在身份 link 发布点暂停初始化器，由另一个数据库连接核对 WAL 已就绪；十个同时首次打开者也必须得到同一 store identity 且全部成功。旧失败保留，不用重跑次数掩盖初始化竞态。


## I26 — 原生自动压缩是受控轮次的组成部分（2026-09-08）

真实恢复测试触发了 Pi 的 threshold compaction；原实现把它当人工压缩撤权，导致摘要请求被自己拒绝。自动压缩现在保留当前恢复 owner，并用仅允许 context_transformation_in_progress 的专用请求守卫；账号/模型/会话/队列/未知工具/控制权等其他条件仍必须满足。人工压缩仍撤销旧模型控制权。每次压缩有独立 context-operations 记录；失败进入 native-errors 并暂停，不能被前一个成功 assistant 结果覆盖。

验收使用真实 split-turn 路径，独立接收端核对历史摘要和轮次前缀摘要两个调用，完整压缩后才到 agent_settled/DONE；总计五个请求、一个 outer continuation、一次文件写入。失败对照在摘要请求返回429，保留操作/错误和 PAUSED。摘要自身的长期自动重试与更广请求路径仍属于未完成的完整认证，不把本次通过扩大到该范围。

恢复保存的 fence 区分“本 controller 已撤销且 epoch 加一”与“新 token 的接管者”：前者必须持久保存暂停，后者只能写迟到记录。实际 pause-late-write 回归和专门的状态断言覆盖这一差异。


## I27 — 运行账本与路线事实进入最终验收（2026-09-08）

状态补测覆盖旧检查通过但计划仍 running/unknown、必需测试/审查缺失、可选失败与已恢复工具失败。finalize 显式拒绝未对账执行，不能从“本进程没有 active promise”推断全部执行结束，资源继续保留。

Receipt 和详细状态增加 routes：区分配置路线、实际选择、恢复 incident，以及每个 descriptor 的 requested 和原生 observed provider/model/thinking/stopReason。无观察时保留 null，不由配置填造实际模型；失败尝试与成功备胎同时保留。状态测试与实际 fallback 工作流已核对这些事实。

452 项全量运行还发现测试哨兵在文件创建但 JSON 尚未写完时被读取。相关进程/凭证/原生 fd 哨兵统一改为临时文件完成后 rename 发布；失败记录保留，监控器不靠忽略 JSON 错误或反复重跑取得通过。


## I28 — 故障子进程不能污染测试进程的覆盖采集（2026-09-08）

457 项测试全部通过的运行仍以 exit 1 结束，因为被故障测试终止的子进程留下半写入 V8 JSON。Node 会向显式环境白名单的子进程补传 NODE_V8_COVERAGE；单靠进程环境白名单不能避免。记录测试模块在当前 worker profiler 启动后移除该变量，保留本 worker 的产品代码采集，阻止后续被 kill 的夹具继承覆盖目录。

定向覆盖运行核对产品模块仍出现，预算结算表覆盖完整分支。真实 reporter 负向控制重新注入变量并生成符合 Node 文件名规则的损坏 JSON，验证测试本体可通过而整体命令必须失败、releaseReady=false。历史失败运行保留。


## I29 — 被阻塞的工作流也必须留下验收回执（2026-09-08）

新增真实 Pi 验收依次运行 exit0/零测试、全部 skip、无法解析计数，并通过 /orch status、kernel_task status 和父模型下一次真实 HTTP 输入交叉核对。测试发现必需验证失败后只保存 BLOCKED job，没有 TaskReceipt，五层证据中的回执层为空。

阻塞路径现在持久生成明确为 BLOCKED 的回执和工件，保留必需项、失败历史、实际路线、工作流阻塞原因；未对账执行仍标 unknown，不能因旧检查通过而生成成功回执或释放资源。生成工件在 owner fence 的事务内，旧 owner 无权发布；工件写入失败时仍在数据库保存不可接受的回执和存储缺口，恢复工件存储不会消除原 unknown。重新查询不会重复调度。

验证结果判定和依赖满足规则另提取为纯函数，分别验证足量真实通过计数、超时/终止/截断优先级，以及只有通过证据或事先允许的 optional skip 可以解锁下游。真实进程与 SQLite 回归仍覆盖这些函数的集成。T10 的“details 错误而 content 宣称 Done”并未由上述正例触发，故没有借此消除其独立缺口。


## I30 — 回执的新鲜度包含根 TaskSpec 版本（2026-09-08）

独立副本状态回归复现两项失效：approveChecks 升级根 TaskSpec 后没有清除旧回执；inspect 只比源码/模型/配置，没有检查回执的 specVersion。批准新的验收输入现在撤下当前回执，保留历史工件并把必需检查恢复为待运行。查询先核对根 TaskSpec 的版本、快照和策略身份，失配时标 receiptCurrent=false；旧回执和历史事实不被改写。该核对不重新执行模型或验证。


## I31 — 有效策略展示与配置加载失败的状态隔离（2026-09-08）

/orch doctor/status 增加 effectivePolicy，展示已合并的路线许可、功能开关、数值限额、预算与根验收要求，不包含账号凭证或可执行命令。真实 Pi 测试核对项目提高预算/reader 限制或删除 required 时仍受用户策略约束，合法收紧生效；关闭正确性不变量、注入验证命令和非法数字在初始化前拒绝，零模型请求且配置/auth 字节保留。

同一扩展实例重复收到 session_start 时，加载失败必须清除上一份 config；状态层负向控制移除清理后复现 enabled=true 的旧策略残留。真实 RPC new_session 会重建实例，其正向测试也通过，但该路径不作为同实例残留缺陷的复现证据。重新加载合法配置仍可恢复正常状态。

恢复链新增状态补测：主力提前恢复仍等待旧执行已对账与服务器冷却；已消费或 unknown 的第四个备胎许可使链回到主力尾段，事故/workScope 预算不变；重新读取阶段记录和后续 tick 不刷新 stageEnteredAt/deadline。这些是 S 层，未声明真实服务或进程重启认证。


## I32 — 父上下文必须重新投影全部硬状态，超限必须阻止发送（2026-09-08）

状态回归复现：原 context hook 只保留最近20个 job，且存在 managed job 时提前 return，隐藏主会话失败汇总。现在由 TaskService 从当前账本生成所有 job 的根 TaskSpec、快照、历史回执身份、分组失败完整 ID 索引与实际路线；主会话故障类别/计数和可由 /orch audit 查询的 native 记录索引同时进入上下文。历史回执的当前候选未重新检查时明确标 not_revalidated，不把历史通过宣称为当前通过。

增加用户配置 evidence.packetByteBudget，默认65536、项目只能收紧；计量为序列化 UTF-8 字节，不冒充各 provider 的精确 tokenizer 预算。v6 示例的 packetTokenBudget 思路在当前适配中落实为可确定验证的传输字节上限；模型本身上下文容量与路线准入仍独立检查。超限返回 PACKET_TOO_LARGE，不截掉 job 或必需失败。

本机锁定 Pi 的 emitContext 会捕获扩展异常后沿用消息，故仅抛错不够。父端主会话与 managed-only 模式都安装发送前检查；证据读取失败或超限时 abort 并保持 fetch gate 关闭。原生 SDK 将拒绝包装成 Connection error 时，明确的内部 context-limit 来源仍归 context_contract，不误入网络重试。

真实 Pi 用例覆盖实际手工压缩，其摘要故意遗漏必需验证失败；父模型下一实际请求、SQLite/回执、UI仍保留该失败与回执身份，成功运行保留 context-observers 工件。另一用例使宿主 abort 无效，仍观察到零父请求；隔离副本再移除发送 guard 时，独立接收器发现多出的请求并使测试失败。既有写后限流、同实例两功能及自动压缩回归继续通过。

上下文字节预算是展示容量，不是执行授权。新增字段不进入原有授权配置摘要，保持旧 schema6 job/continuation 的配置身份；真实请求/事故额度、角色、路线和验收政策仍参与授权摘要。这样提高证据容量不会使已有 TaskSpec 无法恢复或重置账本。父上下文与最终发送边界重新读取当前用户/项目字节上限，变小后已编译 packet 也会在发送前拒绝；合法提高后重新投影可恢复，无需丢弃 job 或改写旧回执。状态/单元回归同时验证旧摘要兼容和执行预算变更仍会使旧验收失效。


## I33 — 等待状态显示由独立的展示调度器维护（2026-09-09）

宿主 setStatus 由 StatusPublisher 合并相同更新，默认每秒更新等待倒计时；关键状态变化立即显示。主恢复明确区分服务器许可的最早时间与“等待重新准入”，job 同时显示当前路线冷却和阶段期限，不把主力冷却当作整个恢复链的最早行动时间。完成状态带已验收快照缩写。展示层不触碰 job 状态、TaskReceipt、预算或派发。

真实 Pi 首轮测试发现 production performance.now 的小数毫秒使整数定时器接口拒绝注册，导致只有首次状态。延迟现向上取整，从实际显示尝试结束后计算刷新间隔，并补小数时钟回归。重复更新、关键变化、无可用 UI 的重试和 dispose 清理均有状态验证；实际 RPC 测试观察倒计时、暂停停止刷新、禁用后新会话清除旧状态。会话清理先退役旧展示实例，旧回调不能写入新状态区。


## I34 — workScope 的多来源身份必须一致（2026-09-09）

旧规则在已有会话文件关联、但运行时 ID 改变且分支标记未提供时，会选择新的 workScope；独立反例已保留。现在同时核对 session ID、当前规范化会话文件、header parent、可信 fork 事件的 previousSessionFile 和分支标记。引用不一致或已知引用损坏时拒绝，不把空值过滤成新任务；已知 fork 却无可恢复身份同样阻塞。既有 owner/预算账本缺失不能伪装首次运行。

纯规则与状态测试覆盖文件别名、重开、坏 JSON/空引用、已知标记缺 ID、可信 fork 来源与 header 冲突。实际 Pi 用例载入早于 Task Keeper 标记的历史，再通过原生 fork 回到该历史位置；新会话仍继承原 workScope，模型新建替代 job 被原语义次数上限拒绝，原候选和计数保留。该修改不提供新预算重置入口。


## I35 — 审查读取要证明早于结论，且内容实际进入模型请求（2026-09-09）

真实 Pi 反例在同一 assistant 回复中发出 tk_read 和 structured_output PASS。旧逻辑只核对工具曾读取，最终错误生成 COMPLETED，失败运行已保留。现在读取记录带调用 ID、返回文本摘要和模型请求序号；只对实际 HTTP payload 中一致的 tool result，在成功模型回复后记录已送达。成功 structured_output 另绑定报告摘要及生成它的请求序号。验收要求读取先完成、结果已送入不晚于对应结论的模型请求，不能以结论之后的读取补票。

同响应提前下结论、读后发送前内容被替换、引用/报告错配和缺少旧版因果记录均拒绝；正常先读后审、critique 修订和精确复用仍通过。额外 HTTP helper 不会替主模型请求取得读取信用，失败或被阻止的发送不提供信用。仅保存摘要与序号，不复制新的完整 transcript。实际 HTTP payload 观察覆盖了只看 before_provider_request 仍会漏掉的后续变更。


## I36 — 可选步骤跳过的原因进入回执与上下文（2026-09-09）

实际 protected 工作流配置6次总请求额度、4次必需审查预留。实现消耗2次后，调度器正确跳过可选 critic，必需验证和独立审查继续并完成；但原回执没有显示跳过原因，专门回归失败。现 TaskReceipt.skippedSteps、状态查询、文本回执和父上下文都携带已持久化的 stepId/reason/time；未知原因保留null，不由模型补造。根 required 与计数不变，策略跳过不等同降低验收。

真实用例核对critic零调用、必需review通过、账本守恒及UI/父模型下一请求可见required_reserve。状态测试覆盖恰在预留边界跳过、增加一个许可后选择critic，以及必需审查因独立资源占用仍保持pending而非被降级。


## I37 — step 耗尽的 resume 不能伪装成重新运行（2026-09-09）

真实工作流先经历实现失败与修复，在第5个 step 后留下正确候选但尚未重新验证。旧 resume 把已耗尽的 BLOCKED job 改成 RUNNING，随后无可派发步骤；反例保留。现 resume 在必要的既有执行对账之后，检查需要新增工作时的 job/workScope step 上限，耗尽则拒绝并保留原状态、控制版本和计数，尚有额度的正例继续可运行。该检查不把模型额度用于本地对账，也不跳过未知执行的处理。状态边界、实际Pi step-cap 和迟到验证对账均通过。


## I38 — 请求超时先撤权，迟到结果只参与对账（2026-09-09）

确定性状态反例发现，单次恢复请求超时后，迟到的 canary 成功或主请求限流结果可能把 BLOCKED 重新变成 WAITING_QUOTA/RUNNING。请求 timeout 现在先保存 unknown 并撤销原 owner，再调用 abort；同步取消回调也不能抢在撤权前恢复派发。迟到的真实 ack/终止仍能结算原 intent，未知执行仍保留资源，确认结束后显式 resume 才取得新的控制权，原计数与事故不清零。

六个状态用例覆盖 canary/continuation × 成功/限流/终止未知；旧实现四项失败，修正后全部通过，既有恢复与凭证等待边界回归通过。canary 状态替身允许提供明确的迟到终止证明；这不等同当前 Pi adapter 能在 abort 后取得该证明。真实 adapter 的终止不确定性须独立验证，不能由状态测试授予认证。

事件重复/冲突与序列缺口规则同步提取为 Store 实际调用的纯契约，保留 append 事务、原始 payload 和相关 scope 的冲突阻塞。U/S/P 联合回归通过；在隔离副本移除 payload 摘要比对后，冲突用例失败，普通相同内容重放仍通过。

真实 Pi loopback 验证确认主请求和 canary 在有限 requestTimeout 后关闭连接且不追加请求。主请求取得原生 settled 证明后释放占用，可由显式 resume 完成；当前 canary adapter 在 abort 后报告终止不确定，仍保留原 intent/资源并拒绝 resume。测试用显式终止观察作 barrier，不在 abort 的中间状态提前断言。主路径另发现本地 Request aborted 被当成新的未知服务错误而阻塞 resume；现只在当前自动请求身份/epoch 与超时原因一致且原生 stopReason=aborted 时标 controlRevoked，原始错误诊断仍保留，恢复历史继续指向原额度事故。


## I39 — 异步快照完成后重新读取验收查询事实（2026-09-09）

状态反例复现：inspect 在 await capture 之前读取回执、TaskSpec 和必需工件，等待期间的验收版本修改、工件丢失或回执替换未被发现，仍返回 COMPLETED。现快照采集后重新读取当前 job/回执、根验收版本、工件与可信检查身份，再生成查询结果；工作区身份变化同样拒绝复用旧采集。无变化的正例通过，三个反例在旧版失败、修改后通过；真实 Pi 的工件丢失、runtime 升级和 check approval 回归通过。历史回执不因只读查询而改写。

R08 原生上下文尾部结束与 input/stop/switch 的六个双向状态轨迹单独登记 matrixCase；换会话先到时，旧执行保持 unknown 与资源占用。此处只认证 S 层，不能推导 A/E。错误全文完全脱敏后，独立 U 用例仍验证分类、次数、必需 blocker 与索引保留。

复核 scheduler/recovery 旧文件后，将使用实际 SQLite/控制器的隐式 U/S 标记收紧为 S；队列持续有高优先级新任务时的老任务等待用例补充了独立 TK03 断言。消除错误层级的历史信用可能增加缺口，不能为保持数字单调下降继续借用。


## I40 — 资源申请按完整观察生成纯规则计划（2026-09-09）

资源容量判定提取为 resourceClaimPlan，由 Store.prepare 在原事务内读取全部相关容量/占用后调用，再写入资源和 intent。任何一个资源不足、重复 ID、缺少观察或非法数值都不会返回部分可用计划。既有更严格容量保持，边界计算用剩余容量比较避免加法精度丢失。资源实体的事务性和多进程竞争仍由 Store 保证，纯函数不宣称完成外部派发。

U 反向资源序列及边界测试、S 实际资源申请和别名互斥测试均通过；隔离副本去掉容量检查后五个 U/S 用例全部失败，恢复后通过。真实十进程许可竞争和 C0–C5 原有进程回归通过。Store/DecisionLedger/workScope 等状态测试、真实进程 verifier 和文件 telemetry adapter 的旧标记同步按实际层级收紧；错误 U 信用由真正纯规则测试补充，不由其他层借用。


## I41 — 原生 SDK 重试取消窗口按真实 HTTP 次序注入（2026-09-09）

私有 child reporter 测试副本可指定第几次真实 HTTP 回调作为切点。新增四个 native-retry 取消窗口实际先收到首个429，再于第二次 HTTP 回调的 gate 前、reserve 后、recheck 后或接收后取消。独立 loopback、SQLite 和 model_input 事件证明它是同一模型输入的 SDK 重试，非另起 continuation。原 child 四个窗口同时回归通过。

SDK retry 不重发 before_provider_request，所以 gate 前切点使用实际 HTTP before 回调。该回调已开始时取消可能仍建立一次预留，但最终信号检查在实际发送前终止，并结算 not_sent；审计要求 used 不增加、reserved 归零，而不是用请求记录行数冒充网络发送次数。接收后的取消保留 sent/used。该批仅增加 native-retry 的 A/P 矩阵证据，不推导未测的 compaction/helper/canary 切点。


## I42 — 最终派发授权提交后，在事务外调用 fetch（2026-09-09）

真实压缩取消反例先澄清两个边界：固定运行时的第二次 HTTP 仍是主模型请求，压缩从第三次开始；单独 ctx.abort 不等同公开 adapter 的完整取消。改为父 adapter 的 AbortSignal 取消、等待其 child grant 持久撤销后释放 child barrier，仍在 after-recheck 窗口观察到多出的压缩 HTTP。旧失败工件保留，不能以原生任务结束解释为已满足取消语义。

早期修复候选曾把 fetch 的同步调用放进短事务。对照 v6 §13/§16 和 OpenSpec D3 后，按“短事务，网络/子进程 I/O 在事务外”的原原则纠正：事务内重新检查 owner/grant、冷却、遥测和许可，并持久化最终 request-admission；提交后立即在事务外调用 fetch，其间没有 await。网络 Promise 始终在事务外等待。该事务确定最终派发授权与撤权的顺序，不声称把 SQLite 与外部网络变成原子事务。

取消先于最终授权提交时，不会取得新的发送授权。授权已经提交时仍属于原已派发动作，之后的取消按原请求的实际调用/终态对账。request-admissions 明确标 provesSend=false；授权不等于调用，更不等于远端接收。已提交授权但发送前被本地信号取消的实际 HTTP 测试仍观察到0请求，并结算 not_sent。调用后终态未知时保留 unknown，不依靠授权记录推断已发送或未发送。

域许可和请求预算先持久化，实际外部动作只在提交之后开始。新增同步 invokeWithin 接口限制当前调用范围内只调用一次 invoke；关闭范围后的重复调用、异步或遗漏调用均拒绝。控制错误在事务退出后记录，避免嵌套事务。主会话恢复、canary 与受管 child 使用同一最终授权原语。

独立 HTTP 验证覆盖允许、recheck 后撤权、授权后取消、延期/异步与重复 invoke；主会话/canary 的8个实际 Pi 回归、child/native-retry/compaction 的12个取消窗口，以及3个回退/协同工作流通过。发送位置另观察真实 SQLite isTransaction 值；gate-observers 保留 receiver、预算、请求/授权账本、事件、nativeResult 与私有 reporter/harness 源摘要。其余矩阵位置和主会话严格跨模型预算仍按原验收待办处理。


## I43 — 成功主执行不能掩盖后续辅助 HTTP 的限流（2026-09-09）

真实工作流先成功修改候选并完成 worker 主回复，然后自动压缩收到429/Retry-After。旧实现已把压缩错误保留为非必需失败，但仍按主执行 ended 关闭路线状态，后续独立审查在服务器冷却到期前发送；独立接收器反例失败工件已保留。

现对新执行的最新已观察 HTTP 错误单独判断：符合既有临时额度/网络恢复分类且具有所需时间证据时，更新对应 quotaGroup/transportDomain 事故；不会再用该主执行的 ended 清掉最新压力。已完成的实现步骤仍通过，候选和语义次数保留，本地验证照常运行，后续模型请求由共享冷却准入控制。精确复用旧审查不被当作新的 HTTP 失败或成功。未知 reset 的窗口错误仍不据此获得自动重试认证。

新的真实 400 压缩失败和429压缩限流工作流都核对原始 child 观察、job failure、TaskReceipt、命令 UI、kernel_task content/details 与下一实际父模型输入；必需独立检查/审查照常满足时可以完成任务，辅助失败历史仍披露。429用例另核对审查接收时的 OPEN 事故与 notBefore，writer 只执行一次、语义次数保持1。

canary 误判用例同时加强为真实业务请求超过2万字符、探测请求低于1000字符且不带工具；在接收器端核对两次探测成功都不关闭原事故，真实业务再次限流继续同一事故并累计次数。把 canary 成功改成关闭事故的隔离负向控制会失败。此处均为受控 loopback 验证，不替代 live Qwen 或效益评测。


## I44 — 公平排序具有用户配置入口和独立纯规则验证（2026-09-09）

OpenSpec scheduling 要求可配置的有界基础优先级与持续 ready aging。原 Scheduler 构造参数可调，但 TaskService 固定 aging=60000、priority=0，用户配置没有入口。现增加用户层 scheduling.agingMs 与 scheduling.priorities.inspect/fix；优先级仍为0–100，aging 为正整数毫秒。项目不能替换同父队列的公平策略。doctor 显示生效配置，真实多任务工作流验证排入队列的 inspect/fix 优先级来自用户配置。

排序提取为实际 Scheduler.next 调用的纯函数，原依赖/资源准入、readyAt 持久化与不抢占执行中的步骤保持由调度器控制。U 用例验证旧的持续就绪任务能超过不断到达的有界高优先级任务、整数时间边界、稳定 ID 平局与输入不变；移除 aging 的隔离负向控制会失败。保证仅适用于同父队列以及资源持续可用等既有前提。

默认 scheduling 在授权摘要中规范化为原版本的缺省语义，保留旧 schema6 的策略身份；非默认排序进入执行策略摘要。配置变更不会清空预算，也不为进行中任务自动授予新策略权限。原有策略摘要、验收修订和主恢复回归通过。

## I45 — 定向运行必须完整匹配请求的测试文件（2026-09-09）

实际复现 Node 在“一个存在的测试文件＋一个不存在的文件”时只运行前者并返回成功。隔离 launcher 现逐个验证显式目标，缺失或越出包/快照范围则在导入测试之前失败；包内绝对路径和软链规范化为隔离快照路径，不能跑原工作副本。零匹配过滤器原有失败规则保留。report/typecheck/plan 模式不再静默忽略多余的文件参数。

真实 mini-package V 用例验证混合缺失、正常选择、绝对路径快照、包外路径/软链与模式参数；旧版本在混合缺失用例失败，修复后全部通过。该校验防止定向验证缺项，不代替完整 spec 义务与变体报告。


## I46 — 默认未绑定与未实现能力给出明确诊断（2026-09-09）

新增实际 Pi 用例发现：默认禁用时 doctor 没有分功能的绑定缺口，Advisor on-demand 仅返回 JSON schema const 错误。现 doctor.bindingGaps 分别列出 interactiveRecovery、inspect 和 fix 的静态配置引用缺口，不解析凭证、不发模型请求，也不作为运行时认证。固定工作流必需的 reviewer/build/focused-tests 与额外可信检查保持与实现一致。

已知但未实现的 on-demand/shadow/always Advisor 模式明确返回 ADVISOR_NOT_IMPLEMENTED；类型错误和未知拼写仍是 INVALID_CONFIG。禁用默认配置、启用未绑定恢复、各未实现模式与 off 正例均通过真实 Pi/loopback 零请求验证，配置和认证字节保持。原项目限制与纯配置回归通过。


## I47 — 固定工作流计划与诊断共享根验收规则（2026-09-09）

原 TaskService 中的固定计划构造提取为实际调用的 fixedWorkflowPlan；静态绑定诊断共享 workflowRequirements，避免两处根验收清单漂移。fix 总是保留 build、focused-tests 与 independent-review；inspect 保留 scout 和独立范围审查。可选 critic 的显式跳过仅供已声明的依赖使用，不能连带跳过必需检查。排序、资源准入和实际派发仍由现有调度器负责。

纯规则测试验证 direct 不因用户省略默认检查而降级、inspect 不新增 writer、可选 critic 跳过与必需验证的边界。移除强制根检查补全的隔离负向控制会失败。另有实际 Pi 模型预算耗尽场景与实际 Service 本地验证状态测试：模型额度耗尽或费用未知时，本地检查继续，原预算保持；必需审查没完成则回执仍 BLOCKED，不把本地测试通过等同于任务完成。


## I48 — 离线运行不能靠 L 标签取得 live 认证（2026-09-09）

实际 reporter 负向用例复现：只有 assert(true) 的离线用例标成 L/VAL-007，即可被登记为 live 证据。离线报告现拒绝 L 层信用，并在 rejectedEvidence 中记录 LIVE_EVIDENCE_UNAVAILABLE_IN_OFFLINE_REPORT；原始执行仍保留，但 live 义务保持缺证。该入口只处理离线运行，真实服务验收仍需要独立绑定、来源与请求上限。

report.exitCode 同时反映记录完整性、无断言及证据校验失败，nativeExitCode 单独保留 Node 子进程状态；不能因为测试体通过就把报告校验失败当成成功。release 模式的退出状态也进入报告。真实 reporter 的伪 live 标签负向控制与合法离线正例验证这一边界。

## I49 — 长测试进度与跨进程资源对账证据（2026-09-09）

635 项全量运行已经结束，但报告器直到结束才输出汇总，使正常耗时难以区别于卡住。报告器改为每 30 秒向 stderr 输出已完成、已发现、失败数及耗时；已发现数只是当前发现数，不冒充最终总数。TAP 随输出写入，等待 child close 后再形成最终报告，避免 exit 先于管道读完。进度不是验收证据，发布判定继续读取最终记录。隔离 reporter 回归验证完成前有进度和末尾输出完整保留。

依据 D4、D6 与 G25，新增两个真实父进程同时通过生产 Scheduler 派发的反序资源、canonical 目录别名和最后活动槽测试。独立连接与真实文件效果证明整组单赢家、无局部新 claim、unknown 时拒绝竞争者；supervisor 确认本次 worker 实际退出后，先撤销旧 owner，再通过 Scheduler.reconcileStopped 结算，竞争者方可继续。每个场景独立归属断言并保留资源、IPC、退出和文件观察数据。这些测试只取得 P 层，不替代 Pi 公共入口或真实 VerifyRunner 冻结测试。

## I50 — 恢复时间规则与多父许可的独立验证（2026-09-09）

依据 D5/D6、G15/G17/G18，RecoveryController.tick 的总期限优先、墙钟回退补偿与共享 notBefore 合并提取为生产实际调用的纯 recoveryTiming；保持原定时器、所有权和事务准入边界。纯规则用例覆盖精确期限、冷却临界点、墙钟后退、单调钟不连续、分数毫秒与长休眠，只返回一次 ready 决定，不凭纯函数声称真实请求已执行。移除回退补偿的隔离变异使对应测试失败。真实 Pi RPC 另证实：5 秒 Retry-After 遇到 500 毫秒总期限，原请求已 settled 后禁止恢复；显式 resume 保留原期限、incident、history 与冷却。

跨进程恢复用例启动十个独立生产 RecoveryController，人工推进测试时钟并通过 IPC 同时触发 tick；独立 loopback 接收器核对真实请求，独立 SQLite 连接核对 quota claim。一个执行结算后才逐个放行；全部暂停时零发送，恢复一名只允许该实例。此层使用测试 InteractiveAdapter，因此仅取得 P 层，不借用 A/E 或 live 认证。

原 owner 丢失用例补充逐 ID 断言与观察工件：父进程死亡但独立 writer 仍能写时，新 epoch 仍不能拿走 unknown 占用；确认该 writer 原始进程身份已终止后才能释放。请求预算用例只登记实际证明的 RTB-011/T30/T31，移除未直接证明的第四次额度、SDK gate 和独立重试标签。

## I51 — 成功回执与真实验证结果的逐层对照（2026-09-09）

fix 和 repair 的真实公共入口测试补充了原生 worker 结果、生产 PID namespace VerifyRunner 输出、独立数据库读取、持久 TaskReceipt、/orch status、kernel_task content/details 以及父模型下一次实际 HTTP 输入的逐层断言。核对任务身份、根规格版本、候选快照、三个必需检查、主树和 refs；修复后成功仍保留此前验证失败与已解决标记。展示接口按现有设计使用 failureGroups 摘要，完整回执保留 failureHistory，不要求把完整失败列表复制到每层。副作用和预算在查询后不增加。

实际验证命令的零测试、全 skip、计数矛盾和未知计数用例补充真实 exit0、stdout、终止覆盖与 notSent 观察，并逐 ID 关联 WFL-004/T44。修复只涉及测试证据，不降低验收条件；P/E 标签分别依赖真实进程及公共入口观察。

R06 的 owner-loss 再增加相反顺序：原生结果先返回并被生产 runStep 接受时保留已结算实施，随后新 owner 接管不得再派发；撤权先到时保留原有 late-result 证据与占用。两者用显式 barrier、原 owner/新 owner 与队列快照核对，只计 S 层。

## I52 — state 目录唯一数据库与可配置文件名（2026-09-09）

复核 D4、G25 与 SCH-011/SCH-012 发现：Store 允许同一个规范化目录使用多个配置文件名，各自 SQLite 发放最后一个 host slot；维护工具却固定打开 runtime.db。两个原实现反例分别出现未拒绝第二数据库和维护 ENOENT。

保留 storage.path 的文件名可配置；新增目录私有 .task-keeper-database.json，在建立 SQLite 前用完整临时文件、fsync 与原子 link 绑定唯一文件名。并发同名共享账本，异名仅一个能完成绑定，另一个 STATE_DATABASE_CONFLICT 且不新建数据库。无目录绑定的旧状态仅在唯一现存主库时采用其名称；多个旧主库要求人工对账，不自动删除、合并或清零。维护快照不能被选为主库；已有逐库 identity、schema、维护 fence 和文件身份检查保持。

维护命令使用目录实际绑定，默认名与自定义名均执行五个真实进程中断/恢复切点。doctor 展示规范化目录、实际数据库和不同目录独立的协调范围，不承诺跨父公平。此修复补全原同目录保证，不引入跨目录全宿主计数。双进程负向控制去掉绑定会再次出现两名赢家。旧预算采用、冲突/损坏/权限、同/异名首次竞争、真实 Pi doctor 与正常任务均纳入回归。

## I53 — 完成请求、人工输入与遥测状态门槛（2026-09-09）

补齐 S 层独立观察：原生步骤均已结束时，独立 gate 的失败仍经生产 finalizer 形成 BLOCKED；DecisionLedger 接受 request_finish 提议只保存提议，不改变失败的必需测试、预算、派发次数或最终完成条件。独立全合法正例仍可完成，此用例不声称实现了在线 Advisor。

真实注册的 index 终端输入 handler 在测试时钟和已声明认证的 adapter 状态夹具中，与 canary 返回按两种先后顺序执行。按键返回 undefined（不消费输入），原 owner 撤权，已确认 canary 仅结算原 intent，不追加 continuation。此证明为 S 层，实际 PTY/HTTP 范围保持单独认证。

Service.advanceWait 的受保护候选另覆盖账号、桶、来源错配和过期遥测；错误观察不放行备用路线、不创建请求预算，合法私有新鲜观察可选中该路线。状态夹具同步配置身份，观察文件不被改写，不借用实际请求层级。

## I54 — 多控制者与 reporter 通道失效的实际协议证据（2026-09-09）

真实 Pi owner-probe 通道注入第二份同版本、同 probe ID 的 owner-ready 回复。独立观察确认两份回复，生产 preflight 必须返回 ACTIVE_SUBAGENTS_RUNTIME_NOT_CERTIFIED，child、HTTP、请求账本和资源占用均不产生；单 owner 正例保持可执行。隔离变异移除回复数量检查后，该用例因执行实际完成而失败。S 层另验证同 workScope 的第二 TaskService 遇到 OWNER_CONFLICT 且原任务/计划/owner 保持；原控制器明确释放后，后继者以更高 epoch 接管已有任务。覆盖范围是已参与 owner 探测协议或 workScope 所有权协议的控制路径。

已有真实 reporter 通道丢失用例补充故障前 ready/producer/lease 观察，以及删除通道后的独立事件账本检查。即使 native 返回 completed/exit0，adapter 仍为 unknown、termination 未确认并保留占用；不能用历史 ready 替代当前完整事件证据。工件保存原生返回、故障前 reporter、当前结果和 claims，不增加 A/P 之外的层级声明。

## I55 — 独立审查拒绝必须进入失败历史（2026-09-09）

加强 T03 公共入口检查发现：REVIEW_EVIDENCE_NOT_DELIVERED 仅保存在当前 reason / receipt.reasons，failureHistory 为空。生产 validateReview 的 ContractError 现在按原 intent 与 descriptor 写入一次 verification 失败事实，保存原 code、脱敏 message、必需性和未解决状态，再按原逻辑阻塞或处理可选步骤。它不把原生 completed 改造成验证通过，也不通过错误原因字符串推测已解决。

后续合法审查必须在其已验证报告中显式列出该失败 ID，原有 resolvedFailures 机制才将其关联至当前审查工件。真实 premature-review 用例先核对原生 ended/PASS 与独立拒绝、五层失败展示，再显式 resume 进行正确读证据的审查；只重跑审查、不重写候选，历史失败仍在并带 resolvedBy。

可选 critique 的同类拒绝另有真实回归：保留 required=false 的历史，跳过可选步骤，必需独立审查仍通过；根回执可完成且不新增 writer。

## I56 — 改低验收阈值不得沿用原授权（2026-09-09）

新增实际 P/E 用例：worker 将候选答案改为 0，并把可信检查声明输入中的最低阈值由 2 改为 0。该候选满足被改低的阈值但违反原阈值；生产流程在新检查开始前以 ACCEPTANCE_INPUTS_CHANGED_REQUIRE_APPROVAL 阻塞。保留 checkInputChange 工件、原规格版本、主树/refs，并通过 UI、kernel_task content/details 与父模型后续输入展示需审批的变化。隔离变异跳过输入摘要检查后错误候选实际得到 COMPLETED，使此测试失败；原守卫已恢复。

模型工具的现有参数 schema 提取为生产注册实际调用的纯 factory，保持相同动作/字段/长度限制，未增加环境参数或执行权限。SCH-002 的 U 用例逐一注入 workScope、scopeId、reset、budget、route/provider/model、storagePath 与 policyDigest，确认每个额外字段单独被拒绝；合法动作仍接受。真实工具和同 workScope 上限回归独立验证宿主执行边界。

T45 另增加实际候选修改回归：先确认当前回执有效，再外部修改已验收候选，UI/tool 和父模型后续输入得到 receiptCurrent=false/BLOCKED；历史回执保留。恢复原候选字节后，同快照证据重新适用，未重跑 writer、未改变主树/refs 或预算。

## I57 — 模型责任范围与 writer 释放的分层契约（2026-09-09）

补充真实 E 入口：受控模型请求 kernel_task 时单独携带伪造 workScope，宿主返回参数错误并传入下一模型请求，未建立 job、intent、请求预算或工作区写入。它验证生产宿主实际使用参数契约，而非仅依赖独立 schema 验证器。

childPhysicallyStopped 的既有三项判断提取为生产调用的 childTerminationConfirmed 纯规则：存在原始进程身份、OS 观察明确终止、显式 externalWork 为空；任何缺失/未知/仍存活或外部工具未结束都保留占用。U 使用手写真值表，不从被测函数生成 expected；原生工具、实际进程与子代理回归继续验证物理观察来源。移除进程终止条件的隔离变异会失败；没有用原生 completed 或 lease 过期替代进程事实。

静默构建的 U 用例直接调用生产 evaluateVerification，分别输入活动且无输出、已有进度但未结束、超时尚未确认终止、超时后终止以及正常静默完成的事实。活动状态保留 unknown，正常 build 的空 stdout 不构成失败；同样空输出若是计数型 tests 则保持计数未知。此层不将状态输入当成真实进程观察。

## I58 — 原生测试超时与状态测试的无关启动依赖（2026-09-09）

671 项全量 run 2026-09-09T02-30-29-230Z 未通过：late-owner 的 revoke-first 用例被 Node 以 testTimeoutFailure 取消。其 S 测试原先经真实工作区/本地 verifier 准备后才等待替身 adapter；前置失败时不会触发 started，而测试仍等该 barrier。改用已声明的 ready 状态，直接驱动生产 runStep、真实账本与 owner 交接，捕获快照作为 S 层夹具；若 runStep 在派发前结束会立即输出原因。保留原 15 秒 watchdog，不靠延长超时掩盖问题；真实启动和终止仍由独立 P/E 测试负责。

还复现了记录器缺陷：测试先执行一个断言再被原生超时取消，after hook 仍记 status=passed，可能借用该断言获得覆盖信用。依据当前 Node 24 测试运行器的取消顺序，记录器在 cleanup 前后检查原生 TestContext.signal，已中止则记 failed。正常完成的 signal 在 after 之后才关闭；正例、skip、cleanup failure、coverage error 和原生 timeout 均通过真实 reporter 子进程回归。671 失败运行保留，不更新为完成证据。

必需工具启动屏障补充实际 A/P 证据：丢失 reporter 上下文后，原生子进程明确报告缺少 tk_read/tk_grep/tk_find/tk_ls/tk_write/tk_edit 并以 failed/exit1 返回；adapter 保留非成功结果，接收器为零请求。仅登记 EXE-003/T06，不据此泛化其他启动故障。

## I59 — 中断状态与 exit0 的来源保留（2026-09-09）

通过锁定 pi-subagents 的真实 ToolResult 投影注入 interrupted=true/exitCode=0，原生转换正确返回 interrupted，Task Keeper 也会阻塞，但原 adapter 丢失 nativeStatus/nativeExitCode 且 error 为 null，界面只剩 execution_failed。新 adapter 保留原生状态与退出码；当非 completed 的原生终态没有更具体错误时，提供 native_delegation_<status> 原因。原有 reporter/工具/后端详细错误仍优先，不覆盖 stream stopReason 或捏造进程事实。

真实 A/P/E 场景分别保存原生正常返回、带中断的 ToolResult、实际转换结果和 adapter 工件，再核对 BLOCKED 回执、UI、工具 content/details 与父模型下一请求。候选保留、writer 一次、必需验证不被跳过。正常完成、错误流、取消、原有 details-only-error 与完整 fix 回归通过。

## I60 — 静默 verifier 的实际进程与用户状态

真实 Pi 工作流的 baseline verifier 在私有 PID namespace 启动，先写入独立 PID/namespace 就绪标记，保持无 stdout 并等待测试释放。测试通过 namespace/NSpid 解析实际进程并核对非 zombie 状态，再用 /orch status 确认 RUNNING、回执为空、原执行 intent=sent 且尚无模型请求。显式释放后，基线和最终 build 的真实空 stdout 均可合法通过，整项任务完成、writer 一次、主树不变。此用例验证静默活动；超时后的终止规则由独立超时与进程测试覆盖，不把就绪标记本身当作终止证明。

## I61 — HTTP200 与四类流终态的 S/E 对照

stream-terminals 的 complete/error/truncated/timeout 四个状态用例逐项登记 S：声明的 adapter 头部状态不充当流完成，生产 RecoveryController 仅按完整终态、错误/截断或有限 timeout 处理原 intent；超时未知保留资源，错误不清除原事故。将 HTTP200 错当完成的隔离变异使 error/truncated 两例失败。

实际 Pi RPC 新增 HTTP200 流内错误、缺 finish_reason 的截断，以及已收到部分文本后的请求超时；原有完整恢复正例也逐项登记。接收器、SDK 终态、独立账本和 UI 分别核对，错误/截断在下一实际模型输入中保留诊断。timeout 捕获已收到部分流、连接关闭、自动 owner 撤权和无立即重发；确认原生 settled 后才允许显式 resume。普通 P1 不产生 managed TaskReceipt，结果由 recovery 记录与原生事件表达，不冒充 managed 任务验收或 live Qwen。

## I62 — 固定计划在创建工作区前验证

实际配置可以把自定义检查命名为 implement，从而与固定 writer 重名并形成自依赖。原 submit 接受该任务，直到工作区准备后才在 Scheduler.submit 失败。新 submit 先用实际 workflow、goal、scope 和 policy 构造只用于校验的固定计划，验证 TaskSpec 与依赖图，拒绝后不写 job 或发起工作区操作；准备后的实际快照/资源计划仍照常验证。预检标识不作为运行快照或资源许可使用。

S 反例证明原实现未抛错，新实现保持原 job/intent；真实 Pi 入口验证 DUPLICATE_STEP、零新 job/intent/资源/worktree/HTTP。合法计划、inspect、步骤上限及 workScope 上限回归通过。此修复不开放任意模型图或修改固定工作流的验收要求。

## I63 — 正常执行身份与未支持参数的入口证据

真实 fix 的 E 证据补充 nativeRunId、nativeStatus/exitCode、descriptor job/step、reporter ready/settled、实际 provider/model/thinking、配置/运行时摘要及 producer 事件的关联，再沿用已有独立验收、回执、UI、工具和下一模型输入对照。没有把请求配置当作未知的服务端权重身份。

同一真实模型回合分别尝试 workScope、context=fork 和 background=true，每个调用只含一个额外字段；宿主全部返回参数错误且无 job/intent/子执行，doctor 仅声明 foreground/fresh 范围。此验证支持范围的明确拒绝，不取得未实现后台/fork 的正例认证，也不替代相应 P 层执行组合测试。

## I64 — 网络重试计数的纯契约

主请求与 canary 的既有网络失败递增/上限判断提取为共同调用的 networkFailureBudget，保留现有计数与 transport-wait 排除位置。U 以固定边界表确认 maxNetworkAttempts=0/1/2 的行为，不受 maxWaitMs=null 的长期 quota 等待配置放宽。移除耗尽判断会使负向控制失败；恢复状态、超时权限、真实普通网络恢复和 managed 网络预算耗尽回归通过。此调整不把网络失败改为临时配额，不重置已有计数。

## I65 — requested high 与实际 off 的原生启动校验

测试绑定使用支持 thinking 的模型，合法 high 经真实 pi-subagents/child 执行成功。另一隔离副本在 child 已加载 descriptor 后、生产模型契约检查前调用实际 pi.setThinkingLevel(off)，记录 requested=high、初始 high 与实际 off。生产屏障以 CHILD_MODEL_CONTRACT_MISMATCH 拒绝，配置仍为 high，独立接收器零请求。

隔离负向控制移除 child thinking 守卫后，实际收到两次请求，测试失败；原守卫恢复。该用例证明 Pi 生效配置差异及启动屏障，不把服务端权重或推理质量当作已验证事实。

## I66 — 恢复与派发规则的独立反例

依据 D5/D6、ADR003/009/010 和 T18/T19/T23/T35/T37–T41/T71，将既有恢复 eligible、原生流成功、owner 精确身份和 intent 首次派发条件提取为生产共同调用的纯规则。定时恢复、发送前复查和 Store 仍在原位置使用这些判断；事务、I/O 顺序、预算、自动恢复范围均未改变。owner 比对同时要求 scope/token/epoch 与 active=true，不以迟到成功或配额恢复恢复权限。

新增 U 采用明确的合法输入及每个独立拒绝条件；V 在私有包副本逐一移除九个 eligible 守卫，实际执行对应测试，确认全部变异被检出并恢复后通过。V 工件保留变异源码行与子进程结果，不改生产源码，也不将此规则测试当作真实 HTTP、进程终止或 live Qwen 认证。原生 retry、流 error/incomplete、会话变化、未知 writer、重复 dispatch 均有各自断言。

## I67 — 剩余持久状态与续跑切点

依据 D3/D4/D5、ADR008/010/011、T40/T42/T76、TK07/T09/T14，补充原 owner 失联后的时间推进、显式撤权与新 owner 争用、迁移中断与预算/intent 丢失反例。跨连接逐字段比较已用与 unknown 请求、资源占用和原 native identity；没有原执行终止证据时仍拒绝替代 writer。升级及恢复不能通过清零预算或删除记录自动消除维护 fence。

新增 continuation.C0–C5 状态轨迹在生产 RecoveryController/Store 方法边界注入中断，分别覆盖提交前、派发前、生效无 ack、ack 未落盘、终态未提交以及已提交未通知。S 明确以声明的 adapter 动作模拟外部效果，保留状态与动作序列；不借此认领 A/P/E 的原生崩溃矩阵。非受保护 P1 不凭空生成严格请求计费记录。长上下文完成工具后的 continuation 状态用例保留原 leaf、上下文前缀、工具完成状态和 incident。

## I68 — 定向测试参数顺序

实际定向命令把 --test-name-pattern 放在测试文件后时，Node 将其视为文件参数后的参数，过滤条件被忽略，运行了整个文件。隔离反例以本应被过滤的失败用例复现了 FILTER_WAS_IGNORED。test-isolated.mjs 现在保留选项相对顺序，将所有已验证目标统一放到运行时选项后，并使用 -- 分隔。前置/后置/等号形式过滤均验证；缺失文件、越界路径、软链逃逸、空筛选拒绝仍保留。

这修复了定向验证的错误执行范围，不能据此推断历史所有长运行均由该问题导致。完整套件的逐 30 秒进度和原始 TAP 继续保留。

## I69 — 真实基线环境失败与结构报告

依据 D7/D10、T79 和 VAL-002/016/019，新增实际 Pi /orch fix 的基线构建环境失败：真实 VerifyRunner 非零退出、环境分类、PID namespace 终止证据、零 writer/升级/critic 请求、原任务 BLOCKED。初始分配的 semanticAttempts=1 保持不变，没有额外语义修复；这不是宣称该计数等于已执行 writer 数。

失败沿实际账本/回执、命令展示、kernel_task 内容与 details、父模型下一请求逐层核对。命令展示采用 failureGroups，不要求其重复完整失败正文。所有模型请求仅用于随后询问状态，主树和引用不变。绑定仍为临时 loopback，不认领服务端模型质量。

另以实际报告脚本执行仅结构检查的测试文件，验证 T01–T88 仍全部缺运行证据、releaseReady=false、规范代码覆盖 unavailable；单个真实 U 执行仅获得自身层级证据。历史计划的 passed 字段或检查成功不产生运行认证。

## I70 — 十个真实 Pi 父会话共享恢复许可

依据 D4/D5、ADR008/010、REC-013/014 和 T24，新增十个实际 Pi RPC 进程、各自独立 home/会话/工作区、同一状态目录与 quotaGroup 的 loopback 验收。接收器同步制造初次限流并扣住恢复响应；十个会话仅一个 RUNNING/一个恢复请求，随后逐一释放，最终每个原会话恰好两次接收（初次失败+一次恢复）。实际 /throttle status、原生事件、接收器 payload、独立 Store 连接及持久 intent 共同核对；原用户任务只出现一次，历史限流保留。

取消持有者后，只有原生终态和原 intent 结算后其他会话才得到许可；父进程 SIGKILL 导致 socket 关闭但终态未落盘时，其他九个真实调度器反复检查仍不能得到第二许可。该未知分支不把进程退出或 socket 关闭当作远端请求未发生的证明。确认未发送的其他适配切点仍按原矩阵单独审核，不能由本用例推断。

私有副本将 quota 许可容量从 1 改为 10 后，接收器在首轮恢复观察时记录20次请求（10初次+10同时恢复），期望11的断言失败；恢复原代码后通过。未调用任何真实服务，没有把非受保护 P1 伪装为严格请求预算或 Q3 live 认证。

## I71 — 剩余状态层诊断与规则序列

T84 状态投影通过真实 Store/TaskService 验证完全脱敏后仍保留失败类别、未解决身份、configured/selected/requested/observed 路线差异和 BLOCKED 回执。TK08 使用实际扩展注册的 doctor handler 分别读取两个独立状态目录，确认各自同名资源可单独占用，并明确 otherStateDirectories=independent、crossParentFairness=false。

RTB-006/T34 的网络状态用例把所有已授权路线配置为不支持的 SOCKS 绑定，生产恢复选择器保留 network_not_certified 拒绝原因，不修改为直连、不发请求、不增加既有配额事故次数；正常 direct 配置及显式第二路线仍有正例。这是未认证网络路径的明确拒绝，不是 SOCKS 支持认证。RTB-017/T88 追加 critique/upgrade 状态序列中的选择器副作用反例，任一后续状态尝试 timer/spawn/write 均被架构夹具检出；普通规则序列仍只产生决策。

## I72 — 已接收委派后的真实 OS 启动失败

依据 D6、ADR004、S3、EXE-005/T01，私有 Pi 测试扩展在实际 child spawn 边界把可执行文件替换为不存在路径，调用原生 Node spawn 并观察真实 ENOENT、pid=null、未触发 spawn 事件。锁定的 pi-subagents 源码不变。原生 failed/exit1/runId 与父 adapter 的 descriptorId 对齐，真实接收器零请求。实际 /orch fix 进一步保留错误到 BLOCKED 记录、回执、命令、kernel_task 及下一父模型输入。

测试观测器的 OS 事实不是生产认证接口：生产 adapter 在缺少 reporter/终止证明时仍保留 terminationConfirmed=false 和协调 unknown，不依据一段 ENOENT 文本释放写入归属。notSent=false 表示委派已交给后端，不表示 HTTP 已发出；两种事实独立断言。

## I73 — 运行配置与服务端模型身份分开披露

依据 v6模型 provenance、ADR004/014、T17，新增 modelIdentity，并在回执的 observed 项标记 identitySource=client_configuration、responseModel=null、serverWeights=unverified。当前 reporter 读取实际 Pi 子端 ctx.model 与 thinking；此来源不能证明服务端使用何种权重。

真实 loopback 流分别返回不同 model 名称和省略 model。服务器实际写出的 SSE 帧、真实请求、descriptor 和原生子端观察分开保存。两个变体均不会用请求配置补造服务端身份；普通 fix 的数据库回执、命令、工具和下一输入仍验证客户端来源标记。这里没有增加成功流解析器，也没有把响应字符串当作权重证明。

## I74 — 工作区创建失败与修改后的取消

依据 D7、ADR008/010、WFL-003/011、T43：以实际文件占用 worktrees 目录，真实 workspace worker 在 PID namespace 内失败并确认退出；保留 staged/unstaged/untracked 文件、引用和阻挡文件。删除测试阻挡后真实创建成功为正例。实际 /orch fix 失败后无 child grant、零模型请求、cwd=null，显示 BLOCKED；准备阶段没有生成成功回执。

另一真实 Pi 场景在候选已被工具修改、第二个请求已到接收器后暂停响应并发送 stop。观察到原进程终止、intent结算、CANCELLED 和释放的资源，候选文件仍保留部分修改，主树不变；没有生成完成补丁或伪称回滚。命令/工具/下一父请求继续能定位保留目录。

## I75 — 真实 SDK 重试的重复结算与缺 gate 拒绝

依据 D8、ADR009、RTB-013/T33：在私有 reporter 副本的真实 transport 回调重放 unknown 和 sent 事实，独立接收器确认一次429与一次200、同请求内容但两个 requestAttempt ID。unknown 重放不退还 reservation；sent 重放不重复扣费，最终两次真实尝试计数2、reserved=0。保留原始/注入源码摘要及逐回调前后账本。

真实未知 fetch 包装器破坏受管 gate 的可认证调用链时，adapter 在派发前拒绝，零 child/grant/预算行。独立普通 SDK 请求仍可执行；该正例只证明普通请求可用，不替代 P1 自动恢复的独立认证。

## I76 — quota resume 重新进入等待链

真实四次备胎请求全部限流后，任务正确进入 primary-tail；原实现的 pause→resume 却把状态改回 RUNNING 并沿最后选中的备胎启动无效子执行。底层预算 gate 仍能阻止第五次 HTTP，但多余执行绕过了等待链的阶段选择。负向运行保留在失败目录，不能当作通过。

新增持久 quotaWaitPending：park设定，合法路线重新准入后清除，等待态重启时保留。候选未变化的 resume 在物理执行对账和授权复查后回到 WAITING_QUOTA，由 advanceWait 处理原 incident、stageEnteredAt/deadline、notBefore 和预算，不直接 retry 旧路线。源码变化仍走原独立快照/验收重建流程。

修复后真实四次备胎测试核对原生退出、接收端计数、事故/workScope账本、pause/resume前后stage和child grant数、UI/工具/父输入；没有新增子执行或请求。S覆盖等待、暂停和恢复记录三种入口，解除服务器时间限制后仍可选取合法路线，不将等待实现为永久拒绝。

## I77 — 真实入口的覆盖归属与回归分组

T18、T23、TK09 的原生 retry/流内错误/长上下文工具后恢复场景补充独立的原生事件、实际接收序列、持久 intent、命令展示及下一父请求断言，逐ID登记。Retry-After和canary场景补充跨进程账本、已结算动作身份与服务器端计时断言后才登记P层。T87通过真实session reload尝试关闭保护，非法配置拒绝且保留已用/unknown预算和写占用，合法配置恢复为正例。

完整运行的长尾原来主要是同一文件内68个真实工作流顺序执行。测试体移动到 fixtures/workflow-cases.ts，四个入口分别注册17/16/18/17个独立场景；机械核对集合相等且无重复，场景名/ID/断言保持。包内完整报告发现全部入口。此调整不提高产品并发限制，也不把测试并行当作跨父公平性认证。

## I78 — 工作流场景在宿主就绪后开始计时

分组后的完整运行2026-09-09T07-44-52-460Z实际执行741项，740通过、1失败。scope-forged-input作为策略组首个场景，15秒窗口耗尽时stdout/stderr/接收端输入均为空，尚未进入参数拒绝动作；失败和原始TAP保留。其它740项没有失败。

工作流驱动现在先发送无模型调用的get_state并等待明确成功响应，再发用户输入。宿主冷启动单独有30秒上限，原90秒整体上限、场景窗口及所有业务断言保持。这样测的是已就绪宿主中的场景行为，不将启动耗时误判为保护失效。没有用删除用例或直接标记通过处理失败。

## I79 — 派发前 SQLite 争用保留等待和错误来源

2026-09-09T07-53-23-044Z完整运行740/741通过，十父失联场景有一个等待者变成通用recovery_dispatch_failed。旧分支没有保存底层错误，所以不能事后断言该次失败的精确异常类型。现在lastDispatchError保留脱敏message、code和SQLite数值错误码。

进一步通过真实外部SQLite写锁超过5秒busy_timeout，确定性复现同一中断路径：修复前九个等待者均BLOCKED且sqliteCode=5；修复后九个仍WAITING_QUOTA且记录sqliteCode=5，原失联持有者的许可仍占用，接收端仍只有十次初始请求加一次恢复请求。原版本对照保存在review-store-contention的独立运行中。

仅对ERR_SQLITE_ERROR的BUSY/LOCKED类别，在WAITING_QUOTA、无本次intent且连接不在事务中时延后重查。此分支不反复抢写锁来保存等待，不增加attempt，不释放资源或重置服务器时间；下一次调用仍重新核对owner、deadline和准入。其它数据库错误继续BLOCKED。已提交intent后的状态写失败也继续BLOCKED，不重新执行。真实SQLite错误的五个S反例/正例覆盖暂停、deadline、非争用错误及提交后的失败。

该处理限定于派发前等待，不将所有数据库故障变成无限重试。临时争用尚未能落盘时，诊断保留在内存状态并可展示；下一次可用事务才持久化，原有intent/owner账本仍是重启对账依据。

## I80 — 按冻结范围接通四项实现差异

2026-09-10的收口先完成707义务/436矩阵/171领域检查的分流，再处理能力审计F01–F04。StepProposal通过真实decisions/propose入口进入原Scheduler/Store事务；共享目录通过可信check绑定产生canonical资源；writersPerJob=0禁止受管writer、正值保持单writer；可选诊断重规划实际插入只读依赖并保留原预算/验收。

详细入口、兼容语义、正反例和原设计依据见docs/testing/w2-f01-design-2026-09-10.md、w2-f02-design-2026-09-10.md、w2-f03-2026-09-10.md、w2-f04-design-2026-09-10.md。没有增加原707/436分母；最低证据补齐不替代完整oracle与矩阵审核。

## I81 — 提议拒绝是审计事实，过期pending不能永久阻挡恢复

非法JSON、越权字段和重复提议记录到proposal-rejections，命令、状态及父模型可读到拒绝索引。拒绝不进入任务语义revision，也不降低required或创造默认advance。过期pending被拒绝后保留契约/拒绝历史并退出等待表，后续显式resume可重新按原规则准入。候选变化时，尚未成功的baseline先重跑，不能留下失败祖先造成永久阻塞。

T85仍是分阶段设计允许的安全契约夹具：上游已结算费用观察是明确标注的合成输入，消费者和最终派发为实际Pi。不能从该检查声称P4在线Advisor已启用或其原生调用已认证。

## I82 — 可信执行终态也要结束未送达的continuation ACK等待

T40状态反例复现：native执行已完成并释放intent，但ACK promise未送达，旧tick永久占用ticking，下一次额度事故不能发起恢复。正常成功不能掩盖这个等待泄漏。

在宿主认证的settled边界，若ACK未登记，Pi adapter按持久custom_message中的完整intent/scope/epoch/leaf元组查找唯一原生entry，补记其nativeId；确认终止后结算原intent，并结束旧ACK listener。这里取消的是ACK等待，不是用户的文件工具。未能找到唯一身份、身份冲突或终止未知仍保留unknown/占用，不能据idle猜测成功。

真实Pi夹具只阻断ACK交付，保留原生入队、HTTP、文件工具、持久消息和终态对账：第一次恢复写入一次，随后同会话的第二次额度事故也能恢复。缺失/冲突身份的反例保持阻塞。独立负向控制仅去掉终态后的ACK清理，真实测试停在4个请求、第二次恢复不能进展，按预期失败。该检查不冒充C0–C5的操作系统崩溃矩阵。

## I83 — 报告入口拒绝非法执行证据，隔离受阻不产生认证

依据D6、ADR004/012/019与VAL-018/G30的诚实报告要求，coverageReport显式验证assertions为非负安全整数、status为passed/failed/skipped。原入口允许非整数/Infinity通过正数条件；cases-evidence-validity-u的反例先失败，修复后通过。零断言仍合法记录为未覆盖，不把它改成通过或丢弃记录；历史失败仍保留。

当前sandbox拒绝bwrap的NETLINK_ROUTE socket。只读Node权限下的单元/报告规则检查可执行，但不赋予A/P/E/L信用，也不替代原隔离完整报告。原707/436分母保持不变；新增测试针对既有义务，已运行、待运行、需接口/observer实施及实网输入分别记入OpenSpec的pi-execution-handoff.md，不把交接当作验收完成。
