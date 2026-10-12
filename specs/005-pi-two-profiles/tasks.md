# Tasks: Pi 双 Profile 与可替换能力

**Input**: [spec.md](spec.md)、[plan.md](plan.md)、[research.md](research.md)、[data-model.md](data-model.md)、[执行契约](contracts/execution.md)、[提供者契约](contracts/capability-providers.md)、[服务契约](contracts/durable-service.md)。

**日期/状态**：2026-10-11，实施进行中；逐任务状态以下方勾选及plan.md执行记录为准，产品gate仍未通过。100项替换旧74任务的编排，完整目标保留，编号迁移表见本文末。R01–R37、63验收项与8不变量保持不变。

**Prerequisites**：规格、计划及上述设计文档已完成；使用已准备的仓库Python/Node工具链，不隐式安装。

**Tests**：用户和spec明确要求故障、安全、恢复、质量与真实运行验证，因此列出相应测试任务。先建立正/负控制及可解释的失败，再实现；只测常量/镜像实现不能算验证。

## 格式、路径与执行规则

- 任务统一 `- [ ] Tnnn [P?] [USn?] 描述与路径`；US1、US2、US7为P1，其余为P2。计划中的P0–P9是工作流代号，不是用户故事优先级。
- 每任务输入包含上述设计、对应前置产物和代码；可写范围是列出的文件/模块及其相关测试，公共schema/锁/CLI由同一集成者写入。新文件为拟议落点，能复用既有模块就复用并同步记录；不创建通用插件平台。
- 最多两个子任务，默认一写一读。`[P]`只用于同阶段前置已满足且文件独立的测试包；实现与只读证据调查也可并行，共享文件不可多写。executor/scout使用实际角色配置，主代理决定权限、事务、锁和恢复语义；子代理不再派生。
- 任务完成需diff、确切命令/层级/计数、非秘密证据引用与剩余未知。运行记录分已完成、进行中、失败待决策、环境不足未验证；后两类保持未勾选。产品代码完成不等于native/live验收通过。
- 默认只在仓库/临时HOME、XDG运行，禁网络、假模型和子进程；不启动第三方宿主或读取真实认证。OS合成进程、native宿主、live账号和人工终端分层；真实步骤先核对会话已有授权，缺授权只阻塞依赖路径。
- 禁改上游宿主/vendor/缓存/二进制，禁私有API及全局monkey patch。第三方ProcessManager只通过公开接口复用，否则改用仓库监督；不会为实现任务而放宽此约束。
- 两种有效尝试无进展、事务/锁/发送顺序不明、前提被推翻或范围扩大时交主代理重决策。未知副作用先对账，不能自动重发、释放Writer或终止用户实例取得锁。
- 故事测试可以使用公共边界的替身独立进行，支持声明必须绑定实际组合。US1与US2先分别实现，集成检查与Base适用维护项完成后独立闭合Base，避免互相等待。Base是中间交付，Full其余目标仍必需。
- 2026-10-11 用户授权主代理自行判断真实场景测试风险。固定只读候选、自有临时目录、合成账号/模型且无外部副作用的测试和同边界必要修复重跑直接执行；无需按历史记录逐批再问。存在实质外部副作用的步骤核对相应已有授权。
- 执行条件按文末依赖表；编号是默认选择顺序而不是越过依赖的许可。先做最低编号且前置/授权满足的任务；被阻塞时继续独立工作。

## Phase 1：Setup — 范围、来源与验证准备

**目标**：固定范围、方法和候选，保护当前环境；不为规划或盘点启动真实宿主。

**独立验收**：当前 Linux x86_64 必需，账号/传输授权逐路线可核对；63 检查和原46项不丢失；Q1正式接口有验证计划及明确阻断。

**验证入口/前置**：V0；Q1 真实宿主探测须对应授权，未授权先完成包静态检查。性能和审批真实结果采集前必须完成冻结。

- [X] T001 盘点工作区、活动实例、部署身份和既有用户改动，将非秘密事实及私密运行记录位置登记 `specs/005-pi-two-profiles/plan.md`，保护旧任务与账号。
- [X] T002 审计 `agents/pi/runtime/`、`agents/pi/packages/`、`locks/pi/manifest.json` 的宿主/扩展来源与公开接口，在 `specs/005-pi-two-profiles/research.md` 按能力列当前提供者、保留/升级/替换/退出决定及证据；登记兼容条件、配置/状态所有权、冲突能力、迁移/卸载/回退和历史偏离，当前锁不能冒充未来选型。以 research.md D12 的逐包清单为候选基线，退出旧权限、独立subagents、smart-compact、旧MCP、session-yolo和全局fetch包装；只保留有活动/恢复引用的旧资产。按D16复用 `agents/pi/migration/resource-manifest.json`、`agents/pi/migration/capabilities.toml` 及关联来源清单，逐项记录配置同步、skills、本地扩展/包、远程包、prompts/themes/agents及其他资源在两profile的保留/替代/排除与理由，并注明旧字段合并、删除、备份、安装行为是否改变；未变项引用基线，变更项固定新来源/目标/身份与验收任务，不改写001历史或重新迁移starter。
- [X] T003 固定当前Linux内核/运行时、Pi主会话和Full Codex后端的必需账号/模型路线、源码传输范围与授权，在 `specs/005-pi-two-profiles/acceptance.md` 登记范围revision；Mac等保持可选。
- [X] T004 在 `src/agentcfg/pi_scope.py`、`src/agentcfg/pi_acceptance.py` 扩展本任务scope与R01–R37/63检查/8不变量映射，在 `tests/test_pi_validation_fixture.py` 验证原46项不丢失；逐项区分结果、执行、证据有效性，未知字段失败，旧scope不能冒充新scope。
- [ ] T005 在 `specs/005-pi-two-profiles/acceptance.md` 和 `tests/fixtures/pi/risk-review/manifest.json`（新增）冻结纯Pi/Base/Full idle/active测量方法、六项审批质量指标、开发/保留集身份及阈值生成程序；获准后先测纯Pi基线，在任何候选性能/质量结果采集前冻结数值预算revision。缺授权只阻塞依赖测量，不阻塞离线实施。
- [X] T006 在 `specs/005-pi-two-profiles/research.md` 执行Q1：核对官方Pi v1.0.1正式发行物、bin/exports、完整依赖、peer/engines、许可证和安装脚本；在隔离候选验证工具及嵌套事件、RPC无UI、reload/cancel和信任加载。固定候选内容身份，尚不更新正式锁；接口不足重选公开方案，不强装或打补丁。

T006阶段验收（2026-10-08）：当前官方隔离Base候选的发行／依赖／peer／engines／许可／脚本材料，以及SDK6、RPC5、trust reload2真实证据已完整绑定。Q1 receipt `6b474761df16cd0a4b467ec873705769fb9f7870dc8d746eadf6e6b9c60db5be`，当前正式8/100；无正式锁／seal／activation／产品gate提升，AUTO OFF。旧记录中的7/100为当时状态保留。

## Phase 2：Foundational — 共享身份、部署与执行契约

**目标**：建立两个profile共有的安装、策略对象、证据与Writer基础；Q4/Q5留在各自故事，不阻塞Base。

**独立验收**：两profile清单可独立解析；私密状态和所有权可核对；准备对象/租约契约通过离线检查；Git及已登记非Git根的独立进程竞争始终仅一个Writer。

**验证入口/前置**：V1、V2；本阶段离线及本地合成进程检查完成后开放故事开发。Q1真实层缺口阻止相应支持声明，不阻塞可独立实现的替身契约。

- [X] T007 [P] 先在 `tests/test_pi_dependencies.py`、`tests/test_pi_capability_manifest.py` 增加两profile独立安装/关闭Full/未知字段/混入依赖的正反用例。
- [X] T008 [P] 在 `tests/test_pi_provider_bindings.py`（新增）先覆盖未知提供者/字段、不兼容、重复单owner、配置越权和current/candidate/accepted混淆；断言安装树与加载集合分别核对，Base无Full包。
- [ ] T009 在 `profiles/pi-base.toml`、`profiles/pi-full.toml`（新增）、`agents/pi/plugins.toml`、`agents/pi/dependencies-modern.json`、`agents/pi/build/recipes-modern.json` 和 `src/agentcfg/pi_vendor.py` 实现共享基础/Full差异及最小能力绑定；旧profile保留`agents/pi/dependencies.json`及`locks/pi/`，现代profile使用独立`locks/pi-modern/`，缺失/错家族不得回退；原样遵守“Base 的定义中不存在 Full 专属包、工具、受管流程 Skill 和服务探测。”；选择声明、完整锁、resource manifest、安装树与加载集合一致，原生能力不强加通用包装。 在 `src/agentcfg/pi.py` 及 `agents/pi/schemas/options.schema.json`、`agents/pi/schemas/agent.schema.json`、`agents/pi/schemas/managed-descriptor.schema.json` 同步profile/manifest校验，不留旧plugin requires。
- [X] T010 在 `src/agentcfg/pi_capabilities.py`（新增适配）、`schemas/pi-lock.schema.json`、`src/agentcfg/pi_lock_layout.py` 和 `src/agentcfg/pi_dependencies.py` 固定CapabilityBinding/ProviderSelection及RuntimeIdentity/ConfigIdentity；记录来源/契约/兼容/归属/冲突/迁移，遵守“同一单owner能力拒绝多个提供者，替换不能在运行时自动换源。”及“账号、OAuth token、API key 内容及其散列都不进入身份、日志或通用摘要。”，保持错误码2–6。 RuntimeIdentity原样约束：“一次执行和证据固定一个身份。运行包变化使依赖其行为的旧证据失效；摘要不包含秘密。”；CapabilityBinding原样约束：“旧执行保留原绑定，不假定不同提供者的会话/状态格式互通。”。

2026-10-11 T010 固定契约与已有生产身份接线完成：能力/提供者闭合形状、单owner、配置所有权、兼容、source/resource身份及旧绑定冻结均覆盖；现代锁读取/运行包收据绑定RuntimeIdentity，Node生产会话从非秘密配置投影生成ConfigIdentity，文件准入消费当前身份。独立只读复核确认请求头、token/key正文与其散列不进入模型身份投影；Python等价helper不需跨进程调用。当前三模块默认158通过、exit0，root收据位于 `t010-root-completion-review01`。Full profile/current锁发布仍由T009，替换激活/恢复由T044，真实整体支持仍未验；不以本任务替代这些目标。正式14/100，产品gate仍false。
- [X] T011 在 `src/agentcfg/pi_diagnostics.py`、`src/agentcfg/pi_resource_reads.py` 提供有效profile、来源、加载集合、权限/隔离维度与未覆盖入口诊断；检查全局/项目/祖先/包注入，查询零模型、零认证刷新、零服务启动及Full探测。

T011验收（2026-10-11）：认证manager的真实SDK加载快照经原通道发布/退役/关闭，由离线doctor标历史/stale；global/project/ancestor/package有限注入正反及Full私有显式项目正控均核实际快照，四CLI与四doctor全0，原Host verified回收/protected0。默认129Node/126Python/最后JSON15及注入54Python/54Node按独立范围分列，不累加。Root收据`0923b68882f1655fb24f07d7f7d6ab61ef39aa8a2199b536340e5c1a4661a2a6`，此前历史观察组件`da5da7b0439db0368ed50181a8ea77da798a8c9db81a8d31380b244c814ddde1`；全文件系统扫描未执行，隔离未验证，不提升产品gate。
2026-10-09 T011 安装描述诊断子包：doctor 仅从已校验 current lock/实际 runtime root 产生六字段上下文；固定只读 runtime/profile.json，四身份及完整资源行匹配后输出有界公开 ID/计数，matched 仅为已保存描述核对。受影响默认测试一次 81 passed，稳定五文件经独立复核；未执行 SDK/宿主/账号查询，不升级加载、发现、权限隔离或 SourceHold 证据。现代实际加载观测接线与正式运行资格仍待完成，T011 保持未勾选，正式 8/100、AUTO OFF。

2026-10-09 T011 内存加载观测子包：自有工厂每次以官方公共 getter 重验四类实际加载集合，输出深冻结且有界的非秘密 ID/scope；roles 明示 selection-only。单 flight reload 避免并发结果复用；新 session resourceSnapshot 绑定固定 profile/lock/slice/runtime 与当前 config，缺完整身份只拒绝新诊断接口。两组默认 fake 测试149/149，稳定四文件经独立复核与root验收，receipt `06568b59aab50e478b79ffdff06e29218ab4586c85a36cb53b8fc4f4bbdd6c40`。实际 Rotom Runtime 外观接线正在实施，真实SDK行为、持久doctor消费和生产支持仍未验；不完成整体T011，正式8/100、AUTO OFF。

2026-10-09 T011 Runtime 观测接线子包：仓库自有外观从本次工厂捕获原 session/snapshot，查询 await 成功和失败后均核对 active 原对象及 native 公开 session 引用；切换/关闭/退役不得发布旧结果，原生命周期顺序保持。近上限场景证明观测本身合规而完整 session 封套超限时固定拒绝。green01 有109个通过计数但exit1异步断言失败，明确非通过；修复后同单模块green02 109/109、exit0，稳定两文件独立复核与root验收，receipt `4dbd43c11dfebd94be3f35f8735052c71f19b19faffd928d1e7161df6ebab481`。默认自有Runtime内存查询接线完成；新SDK生命周期四场仅准备false-guard材料，未执行，实际SDK/持久doctor/正式支持仍另验。T011保持未勾选，正式8/100、AUTO OFF。

2026-10-09 Base SDK生命周期子包默认准备完成并经修复后稳定独立复核。公共原runtime/实际callbackctx、专用事件、合成UI及临时SM公开重开材料四场已固定；root P2旧代Todo definition/共享runtime已改为每代原定义及子会话独立公共loader/runtime/UI/core。阶段driver11/runner11与新有效RED后受影响1/1分开保存，无虚构单轮12/12。新false计划SHA 48b3dffce5fab29f0746008d22d2e2c45e83f301e84a32426008053dac99234f；具体说明 native-base-provider-sdk-lifecycle-probe.md。新原生尚未授权执行，旧SDK4授权已闭合不沿用；全部guardfalse、正式8/100、AUTO OFF。

2026-10-09 Full中立依赖基础：backend/worker-main两处直接文件helper import改为现有private-files，全部其余字节不变、默认backend2/2；worker闭合输入validator/toolsAllowed原文提取为managed-worker-contract，旧export保持同一ESM binding，全部执行body字节不变，默认worker/backend7/7。root稳定验收receipt 300128e639bdd263645bc7634a1a30e08be2f0451e0b06b27120500d6430ae81。只移除已观察的依赖循环和SDK执行模块对数据validator的耦合，不把旧0.84.4 worker称为现代兼容，不构建历史patchedhost，不开放Full或SourceHold；正式8/100、AUTO OFF。

2026-10-09 Base公开SDK生命周期四场用户已授权实际执行：Footer/Todo/Combined原材料均通过；Loop首次SDK业务观察成立但wrapper witness计数oracle失败保留，同边界明确requests4/witness2后仅Loop02重跑通过。每场首末完整树/固定工具/材料一致，child/wrapper0、stderr0、EOF/groupempty，actualfile/stdout当时相等但rawstdout未保存，独立不冒称重取。两材料版本分别固定，根验收receipt 56fba8c372c96982e688ef3e572f38d34b6c7f1c335323e104436dfd10848a20；grant已满足，无新SDK调用计划。Full中立private-file import与输入contract默认基础另完成；真实TTY/mode/认证/正式支持及SourceHold/Full产品仍未验，T009/T010/T011/T012等不据此整体完成，正式8/100、AUTO OFF。

2026-10-09 来源latch默认底层：新primitive固定instance/source.lock、nonblockingSH/EX、yieldNone/noFDhandoff、owner/mode/named/根对象端点核对、close-only一次。Root目录元数据P2后newmodule34项通过；body+endpoint/close异常priority有效RED后受影响3项通过，历史轮次分别存、不伪合37/37。稳定小差量独立复核及root验收receipt 1941970e4b5b6eeb4be2e9972d9a74ed4a83e28dc79fd6365cab169100f78264；此时不接任何caller/不具SourceHold/initializer资格。实际现代Pi管理入口接线另行source-latch-cli-integration-contract.md冻结，stop/recovery不得变为sourceEX死锁，正式8/100/AUTO OFF。

2026-10-09 现代Pi来源caller接线默认完成：mutation/apply/rollback/sync EX、run SH，source→原life→state，bounded marker在anchor前校验且原guard重复check，candidate前置拒绝不产生新文件；legacy/recover/stop仍原guard，不以sourceEX阻断停止。默认19与activity1分轮通过，独立稳定复核，rootreceipt 03601d7364b4de75f6269a942ac708b78e4a5b5bfcb72ac99c2303bff8b893f5。SH允许账号/会话附属目录准备，部署source投影及原lifeEX保留；sourcefd不转交、仅foregroundscope，不SourceHold/FullSourceView或CrossPID资格。后续长期holder/initializer principal与真实参与者组合另验，正式8/100、AUTO OFF。

- [X] T012 在 `src/agentcfg/pi_runtime_packages.py` 及 `tests/test_pi_validation_runtime.py` 实现隔离候选、两套可写状态、稳定原生home和三方部署；失败/漂移/活动实例不得覆盖用户数据，目录0700/私密文件0600并复核所有权与链接。基础运行包按Q1正式组合落锁，Full高级包由各故事另行固定。

2026-10-09 Base 子包进展：T009/T010 的受控 current 锁生成接口已完成默认实现与稳定独立复核，相关两模块一次 92 passed；默认只接受 candidate，只有显式 `current_profiles` 允许已声明 current 且具 verified host/engine 的 profile，accepted 始终不能由生成器发布，current 许可证在发布前严格检查。新声明使旧 recipe 过期时仍拒绝回读，失败不改旧锁字节。此子包未修改真实 provider 支持声明或发布正式 manifest，T009/T010/T012 不据此完成。三个本地扩展的四场 SDK 加载/注册材料已固定并完成独立复核，见 `native-base-provider-sdk-admission-probe.md`；原生未授权，生命周期/UI/业务支持仍未验证。默认功能测试正在补充，正式 8/100、AUTO OFF。

2026-10-09 后续实测：用户另行授权上述 SDK4，footer01/loop01/todo01/combined01 一次实际运行均加载正确、errors0、child/wrapper/tool0，无修复重跑；独立复核保存文件无差异，授权已满足并闭合，有限 receipt `4732056b3c26cb95f16052691e43b5c53d858e7d9aeb19eb8089c945877a8767`。默认真实本地入口的八项 callback/重放/会话/计时器功能测试通过；固定四文件首轮15/16，旧只读拒写 oracle 修复后仅受影响模块2/2，共16个不同测试跨两轮覆盖，独立差量0P1/0P2，receipt `77cf343170861649fcbf2053b78b997bc4481244b7f7a7cd6b4a5527879b1704`。这些结果不证明官方 callback 时序、真实 UI 或 session 持久化，三个 provider 的完整支持声明仍待对应验收；正式8/100、AUTO OFF。

- [X] T013 在 `src/agentcfg/pi_operations.py`、`agents/pi/runtime/permission-access.ts` 和 `tests/test_pi_operations.py` 固定OperationIntent/PreparedOperation/PermissionPolicySnapshot/ExecutionPermit共享契约；“相同 ID 携带不同请求必须报幂等冲突。”；最终argv、根、cwd、session、策略、运行身份、真实用户来源、deadline及cancel epoch均绑定，未知/无法规范化失败，模型字段不能自授身份。 补全资源类别、可执行文件身份、operationDigest、网络/服务能力和后端；“审批审查的是这个对象；执行也只能消费同一个对象。”，未知后端或deny不可表示不得产生可执行对象。 “operationId 不可由模型自报取得权限。”；至少含operationId/requestId、profile/会话/角色/cwd/工具入口、最终参数或规范argv的私有绑定、用户来源/有效限制、policy generation/运行身份/上下文、时限/cancel epoch/资源类别；最终参数由同一控制面完整私有记录持有，对外DTO仅随机private_input_ref（不包含正文或正文散列），幂等/审批/执行须绑定并比较原参数，见data-model与execution契约；digest仅变化检测，不是权限令牌。
- [X] T014 [P] 在 `tests/test_pi_workspace_leases.py`、`tests/test_pi_registered_roots.py`（后者新增）先写Git/非Git根、跨profile HOME、路径别名、根替换、未登记、双独立进程同时取得及崩溃切点正反例；观察实际占用数而非只检查mock锁。独立OS场景用 `tests/conftest.py` 的明确opt-in与 `tests/fixtures/pi/workspace-lease-worker.py`（新增合成子进程）驱动，默认不运行真实子进程；只开放固定测试子进程、临时根与无秘密环境，禁止任意argv、宿主启动或整体撤销网络/进程保护。
- [X] T015 在 `src/agentcfg/workspace_leases.py`、`src/agentcfg/pi_registered_roots.py`（新增）、`src/agentcfg/cli.py` 接显式登记/查询受管根入口；RegisteredRoot遵守“非Git根必须登记且跨profile指向同一协调锚，不以profile HOME派生各自独立锁。”和“根被替换或身份未知拒绝写入；不自动git init。”；共享锚所有权与恢复边界写入 `docs/pi-permissions.md`。 通用调用接 `src/agentcfg/pi_operations.py`、`src/agentcfg/pi_commands.py`、`src/agentcfg/pi_host.py`；核对 `src/agentcfg/pi_delegate.py`、`src/agentcfg/pi_git_status.py`、`src/agentcfg/pi_native_roots.py`、`src/agentcfg/pi_pid_namespace.py`、`src/agentcfg/pi_git_review.py`、`src/agentcfg/pi_checkpoints.py` 的Git假设，Git专属功能在非Git根明确unsupported，通用文件/命令不因此失败。 同时核对 `src/agentcfg/pi_supervisor.py`、`src/agentcfg/pi_delegate_spawn.py`、`src/agentcfg/pi_delegate_commands.py`、`src/agentcfg/pi_auxiliary.py`、`src/agentcfg/pi_readseek_select.py`、`src/agentcfg/pi.py` 的Git身份使用；只适配所选组合及共用入口，未选readseek等记排除，不扩大产品范围。
- [ ] T016 在 `src/agentcfg/workspace_leases.py`、`src/agentcfg/activity.py` 接WorkspaceIdentity/WorkspaceLease，覆盖所有受管入口；Git/非Git各验compare-and-acquire恰一成功、别名一致、提交未回执/owner崩溃/忙锁/PID重用，unknown不释放Writer；外部编辑使相关快照stale。通过真实双进程门槛前不开放任何受管写入。 WorkspaceIdentity原样约束：“同一物理工作区在不同受管 profile、进程和任务中映射为同一写资源；路径别名和符号链接不能为受管入口创建第二个 Writer。”；只读任务不能经产物别名写业务根。

## Phase 3：US1 — 单主 Agent 日常开发（P1）

**目标**：独立Base完成工程任务，保持原生交互和会话；最小完整Base还需US2。

**独立验收**：无Full安装/服务下完成C++复现→最小修复→相关测试→diff及Shell/Neovim；认证、手动切换、会话恢复分别验证。S03–S07、S09–S14、B01–B06。

**验证入口/前置**：V1、V3；授权native/live从实际Rotom入口验证，离线层不得冒充真实账号。

- [X] T017 [P] [US1] 在 `tests/test_pi_optional_capabilities.py`、`tests/test_pi_operations.py` 构造无Full包/服务的日常任务基线，以及读写搜索/edit错误传播回归。
2026-10-10 T017 默认基线完整验收：真实 Base 配置解析/渲染、Full 包与服务缺失、默认拒绝及显式自有项目策略正控；原 FileOperationAdmissions/WorkspaceLease 完成真实临时文件读写与受保护错误传播。Python 最终受影响 27 passed；独立 Base 普通工具 fake SDK 模块 17 passed，覆盖 read/ls/find/grep 成功及错误、edit 错误与七工具拒绝零 IO。Root 针对写入完成后的两个稳定差量审查，无未决严重问题；证据 `base-ordinary-baseline-executor-review01` 与 `base-ordinary-baseline-review01`。这些是本任务要求的默认基线，真实 SDK/安装/日常产品验收由 T019/T027/T028 继续，不据此签发 Base gate。正式任务 10/100。
- [X] T018 [P] [US1] 在 `tests/test_pi_native_mcp.py`（新增）先写原生MCP配置优先级、按需连接/认证、资源、取消、Code Mode嵌套权限和isError/非零/并行失败传播契约；测试中禁用真实服务器与模型。

2026-10-11 T018 默认契约完成：冻结显式配置、无 ambient 加载、默认关闭/按需传输、资源/取消与内层失败、并发根隔离均有断言。Python36、Node79分轮通过；独立审查指出 bearer 认证缺口后，新增实际自有 fetch 的合成请求检查，两模块13通过，确认选定私有 slot 注入、缺 token/外源/未绑定服务零发送。稳定差量复核无剩余P1/P2，root receipt `3b1336fdafe6c9a24878ceb48d7fdf1d2c57ad211ce2b0462f893ab3b18a32b9`。OAuth/经典SSE仍显式拒绝；不将默认契约当真实SDK/服务/安装资格，T024继续开放。正式13/100，产品gate仍false。
- [X] T019 [US1] 在 `agents/pi/runtime/tool-operations.ts`（拟新增自有工具适配）与 `src/agentcfg/pi_operations.py` 对接正式Pi公开搜索/读取/edit路径、共享策略及Writer租约；保留原生工具语义和错误，不用TK/额外子代理处理普通操作；隔离由US2提供，未就绪时受保护执行明确不可用。

2026-10-11 T019 完成：复用现有 `ordinary-operations.ts`、`official-file-runtime.ts` 与官方 read/write/edit/ls/find/grep definitions，接原共享准入、Python监督者和Writer。明确确定性子树无界面可执行，潜在更严格后代/未知别名提高审批；实际IO逐项检查已消费source上限与当前权限快照，迟到升级失败、不发布局部结果、不退款或重放。最终默认306通过，独立稳定审查无剩余P1/P2。真实 stage3-headless-native02 原Host constructor/run→Unix socket→官方SDK完成12工具，13合成sender、零人工确认，harddeny/外根保持哨兵，两个Writer reserved/active/released、三租约original verified回收、protected0。Root receipt `4bbb91446fc9e9f6e99eadb6f36ab84593c220d78725d548698d807ccd86561d`；临时manifest/合成Provider/分离来源布局不构成正式安装、账号或整个Base资格。正式15/100，产品gate仍false。
- [X] T020 [US1] 在 `src/agentcfg/pi_commands.py`、`src/agentcfg/pi_supervisor.py`、`src/agentcfg/pi_checks.py` 和 `agents/pi/runtime/process-tools.ts`（新增自有bridge）接长命令日志/退出/超时/取消/截断；核对ProcessManager公开可拆分边界，第三方源码只读，所有执行接同一监督/策略/隔离，禁裸spawn；无法公开接入时复用仓库监督实现行为，不仅删除catalog依赖，不退为逐条注册Shell组合。

2026-10-11 T020 完成：固定SDK未公开ProcessManager，采用公开BashDefinition→自有 `official-shell-tool.ts`/`shell-operation-executor.ts`→原Supervisor/ExecutionStore/ShellStart，而不是选择旧裸执行插件。同一策略/隔离处理完整Bash组合；R06不承诺跨宿主持久。native09已有正常、exit7和公开abort；最新native03另验真实timeout及bulk/fragmented两种1.5MiB输出，三外部Writer与Host均verified回收、protected0。观察到命令exit0却因全live队列排空误报timeout后，保留deadline/终止证明/完整capture核验，终止快路径验证已显示前缀SHA并显式标截断；最终119默认、共享MCP stdio受影响12默认分开通过，原碎片失败和旧大块成功保留。新三场sender7/exit0，timeout先running再exit137；输出真实exit0、保留1MiB且SDKtruncated/terminationConfirmed。稳定独立复核无范围内缺口；Root receipt `48052d38bcd4f65acbfe42d9b8b5a6320dcf307f83ea63135e564a2c311c0270`。合成账号/UI及只读guest镜像仍不签正式安装、实际宿主系统树/TTY或Base gate。正式16/100。
- [X] T021 [US1] 在 `src/agentcfg/pi_login.py`、`src/agentcfg/pi_host.py` 与 `tests/test_pi_login.py` 验主会话原生登录、私密文件key、工具调用及手动模型切换；缺失/空/不可读分别诊断，秘密不入参数/通用日志/快照或未获准环境；Base不依赖Codex安装或认证，不复制OAuth token。 新增 `tests/test_pi_main_auth.py` 覆盖Pi主会话认证/文件key/模型选择；现有test_pi_login.py是Codex委派认证回归，不能替代这些新用例。

2026-10-11 T021 实现/公开ABI验收完成：共享SecretStore required缺失/空分别安全reason、exit3及opaque定位，optional仍None；不可读保留脱敏所有权错误。原 `cli --profile pi-base model status --verbose` 两个真实配置视图例确认所选行未填写/为空，父key环境不回退、原私密auth与secret文件不变。默认92/5deselected、DSH/Pi路由12/38deselected、locator1、inert Node8和新CLI2/5deselected分别exit0。原宽回归92pass/5fail仍未通过：五个OMP用例因已存在shared领域Skill资源锁漂移，在本轮auth逻辑前拒绝，不修改旧锁或算pass。官方SDK新三场native05 exit0：合法public setModel实际alternate sender1，越界sender0；原scope→public ModelRuntime.login/OAuth callback/原InMemoryCredentialStore→getAuth→sender1，refresh0、无关native记录不变，无token复制。独立无P1/P2，Root另补审直接CLI证据；receipt `b74a53b72bdc36729ff724a18db7d1545be5e1c4b4e262e40e7b7db3e9aad19e`。合成登录ABI不证明真实OAuth供应商、持久auth/TUI或真人账号；真实路线/体验继续T094、跨agent锁继续T095。正式17/100，产品gatefalse。
- [X] T022 [US1] 在 `agents/pi/runtime/providers.ts`（拟新增公开Provider适配）、`src/agentcfg/pi_host.py` 和 `tests/test_pi_provider_routes.py`（新增）以正式原生配置/公开Provider承接已选国内路线，退出 `agents/pi/packages/openai-proxy/` 的全局fetch/dispatcher包装；禁止跨账号fallback，秘密仅按获准路线注入，保留无海外代理的实际验证目标。
- [ ] T023 [US1] 在 `agents/pi/runtime/resource-loader.ts`、`agents/pi/plugins.toml` 与 `tests/test_pi_session_profiles.py`（新增）选原生唯一压缩owner，退出smart-compact重复入口；验会话查找/恢复/分支/交接保留用户限制、失败证据和未完成任务引用，实际压缩/恢复另验native。
- [X] T024 [US1] 在 `src/agentcfg/pi_mcp.py`、`src/agentcfg/pi_mcp_script.py`、`agents/pi/runtime/mcp-tools.ts` 将旧MCP包切换为正式Pi原生MCP/Code Mode公开接口；实现T018契约中的按需连接、认证/资源、嵌套权限、取消、内层失败传播，不携带subagents依赖；适配中无私有导入或第二MCP执行权威。 同步 `src/agentcfg/pi.py`、`agents/pi/schemas/options.schema.json`、`agents/pi/runtime/launch.ts`、`agents/pi/runtime/resource-loader.ts` 的manifest到正式公开SDK配置链，退出旧包加载。
2026-10-11 T024生产实现已完成：正常现代manifest→原公开SDK MCP/Code Mode→唯一准入与stdio/HTTP传输；按需公开Enable、none/bearer私有slot、资源、嵌套/取消/内层失败/丢ACK不重发已有稳定默认与实际CLI/Host/socket/SDK合成服务证据。旧MCP/subagents包在现代选择中排除；OAuth/classic SSE明确拒绝，未声称支持。T018已接受契约并不要求打开这些不支持模式；当前任务按实现范围关闭，最新Full/账号/外部服务/广故障矩阵与产品资格仍分开验收。Root交叉验收receipt `4839d48e919e6ff91f3d2dd2b7048459421c7eb401d719365623e0378b1076fd`，正式23/100，产品gatefalse。
- [X] T025 [US1] 在 `shared/skills/`、`shared/rules/`、`agents/pi/prompts/` 与 `agents/pi/plugins.toml` 清点/迁移完整领域Skill包，保留数据库锁/MVCC/生命周期/恢复/兼容/最小修改/验证知识、相对脚本与资源；公共短规则+原生项目规则，Full调度知识单列，移除全局superpowers/openspec整套注入；不执行迁入脚本、不删除用户项目工作流。核对共享prompts中现有model_delegate/kernel_task条件分支，按实际能力选择或给出不可用说明，Base不引导调用不存在的Full入口；T028/T095核实际加载。

T025验收（2026-10-12）：完整Base领域目录、相对参考/许可证/执行位、短规则及普通模板已按既有组件收据验收；现代Full调度Skill独立两包/实际API，Base不加载。正常producer、两local Full seed/远程150和Base145不变、新实例SDK加载及原只读工具正文消费验证；最终current receipt slice/profile路径绑定P2及schema等价派生修复、119/27默认分轮和新真实read/Host回收稳定独审无P1P2。227输入Root `6bffca96caf0f449c407724280a1a4729beff4d489645682e1498ebc2826cfa9`，失败旧身份保留；不签整包/Full工作流/正式锁资格。
- [ ] T026 [US1] 在 `agents/pi/packages/colorful-footer/`、`agents/pi/plugins.toml` 和 `docs/pi.md` 配置低干扰中文CLI/SSH体验，todo/footer/loop-guard只显示真实状态与无推理提醒；短规则、领域Skill、项目自选流程与Full调度Skill分离，不后台启动模型/服务；终端模式以实测确定。
- [ ] T027 [US1] 在 `tests/fixtures/pi/two-profiles/main.cpp`、`tests/fixtures/pi/two-profiles/editor-task.sh`（新增）构造合成C++ bug及Shell/Neovim任务，记录 `docs/acceptance/pi-two-profiles/daily-work.md`；分层验复现→最小修复→相关检查→diff及会话恢复，默认fake模型，native/live先核对授权。
- [ ] T028 [US1] 通过 `src/agentcfg/pi_cold_rebuild.py` 的适配路径执行Base独立冷安装/重复部署/Full缺失场景，记录 `docs/acceptance/pi-two-profiles/`；真实认证和国内路线仍单列，不冒充完成。固定Base正式锁/入口/加载集合，按T002差量清单逐项核对Base声明资源与宿主实际发现、排除项无残留；Q1实际接口未验不得记通过，旧迁移证据不能代替本次验收；US2未闭合时仅报日常能力阶段通过。

## Phase 4：US2 — 可解释的权限与执行隔离（P1）

**目标**：独立权限扩展与Linux日常执行隔离；权限不依赖TK、Durable或subagents。

**独立验收**：允许根内编辑/构建成功，直接/脚本/符号链接越界实际被挡；不可用零宿主回退；Q3有真实支持/限制结论。S08、P01–P07适用项。

**验证入口/前置**：V2、V4；OS正反由父侧观察哨兵/连接/后代事实，native与Q3独立授权。

- [X] T029 [P] [US2] 在 `tests/test_pi_guarded_files.py`、`tests/test_pi_commands.py` 建立允许根成功/越界失败、脚本间接访问、符号链接、策略自改和秘密哨兵的成对用例。

2026-10-11 T029 默认正反对照完整验收：允许源IO与外根/链接/秘密/权威配置哨兵，原绑定脚本保持文件deny命名空间、策略变化stale、无法表示的链接遮罩固定失败。五模块一次198 passed/exit0，稳定差量独立复核无P1/P2；Root receipt `18398fd1b3399bbe8f8520a0a00570558a2125d32e1ad243232cf1e62c54b800`。命令进程仍为替身，不以argv证明真实脚本隔离；OS/native产品边界继续由T033/T040验收。正式18/100、产品gate仍false。
- [X] T030 [P] [US2] 在 `agents/pi/runtime/tests/permissions.test.ts`（新增）用隔离runner覆盖无subagents加载、同一策略、公开嵌套事件、无UI、权限失败传播及正常编辑无需一律人工；测试模型自报来源不生效。
2026-10-10 T030 默认权限测试完整验收：新增三项真实自有 controller→factory→admission 组合，Base 不探测 Full global，确定策略无 UI 一次准入，人工项无 UI 不能自报来源放行，内层失败保留原 content/details 并使 outer isError，取消后迟到许可零消费/执行。已覆盖条款映射原文件准入、MCP、Base 工具和会话测试，稳定一次 232 passed，Root 写入完成后的差量审查通过；证据 `base-permission-contract-review01`。这些为默认 fake SDK/监督者测试，真实 SDK 嵌套协议、OS 与产品资格仍由后续任务完成。正式任务 11/100。
- [X] T031 [US2] 在 `src/agentcfg/pi_rules.py`、`src/agentcfg/pi_operations.py` 投影单一权限来源到文件、命令、工具和角色；原样遵守“单一权威来源，默认拒绝。hard deny、必须人工项和角色上限不能被模型、项目或子任务放宽。”；不能表达deny或未注册入口失败关闭。
- [X] T032 [US2] 通过 `agents/pi/runtime/official-session.ts`、`official-file-runtime.ts`、`official-file-admission.ts` 及 `resource-loader.ts` 的公开SDK工具/inline扩展组合实现独立权限接线，接仓库策略/监督核心；替换旧permission-system/session-yolo，不依赖SubagentDetection事件、不导入旧包私有模块，不修改宿主；已授权正常编辑/测试按策略直行。现代 `official-launch.ts` 和正常producer排除旧权限包，`noTools: "all"`关闭裸默认工具后只装显式受管工具；保留旧 `launch.ts` 作为不可新增构建发布的历史恢复资产，不增加第二层permission authority或为文件名创建重复扩展。覆盖内置/原生/嵌套工具加载正反例。
- [ ] T033 [US2] 完成Q2，在 `src/agentcfg/pi_checks.py`、`src/agentcfg/pi_commands.py` 与 `agents/pi/runtime/tool-operations.ts` 集成独立系统bwrap日常可组合Shell/文件执行；固定可执行身份及最小挂载，Base不依赖Codex资产，不挂整个HOME或宿主根换兼容；C++增量/缓存/临时目录/Neovim正控制和越界通过后启用，失败记录后由主代理显式重选。 2026-10-05阶段记录：父侧严格来源校验、密封FD交接和保守系统子树遮罩已实现，842项默认回归通过；run08当前Linux固定helper三项原生场景observed（边界19/19、错误身份拒绝、后代108ms终止且心跳稳定）。后续已完成产品父侧operation/lease/runtime/Writer交接的内部接线和离线故障矩阵；外层专用dup FD挂载，worker无RPC凭据。产品路径原生、默认factory/preflight及用户场景仍未验收，T033不勾选；详见`native-shell-probe.md`与plan中的产品父侧阶段。
- [ ] T034 [US2] 在 `src/agentcfg/pi_checks.py`、`tests/test_pi_checks.py` 与 `tests/test_pi_tool_sandbox_os.py`（新增独立OS suite）明确网络/loopback/Unix socket/env/HOME/缓存/运行包/策略/认证/`.git`和子进程边界；保护哨兵且正常任务成功，后端缺失/namespace禁用零宿主回退，默认套件不启动真实宿主。
- [X] T035 [US2] 在现代 `agents/pi/runtime/official-file-admission.ts`、`src/agentcfg/pi_operation_admission.py`、`pi_admission_control.py` 与 `pi_operations.py` 的实际消费点实现ExecutionPermit状态“pending -> consumed”“pending -> revoked | expired”，仅执行入口原子消费；参数/cwd/session/policy/model/限制/模式/cancel epoch变化失效，跨请求、重复消费、迟到响应均零执行；缓存只复用确定性策略结论。 permit不能扩大PreparedOperation的根、网络、argv或角色，更不能提升OS权限。
- [X] T036 [US2] 在 `src/agentcfg/pi_commands.py`、`src/agentcfg/pi_pid_namespace.py` 与 `tests/test_pi_commands.py` 绑定ExecutionLease出生身份和grant generation；验证未执行撤销、starting未知、cancel-requested→stopping→终止证明才canceled，无证明为termination-unknown且保留资源；许可消费后配置变化不得伪称进程已撤销。
2026-10-11 T031/T032/T035/T036 实现任务已按现代公开接线完成交叉验收：单一manifest权限/角色上限、受管七文件工具与显式Shell/MCP、一次permit原子消费、参数/会话/config（含当前模型/思考/设置/项目限制）/policy/cancel失效、原lease出生身份与generation、unknown保持保护均已有稳定默认与T019/T020有限原生证据。任务原拟文件名映射到实际official admission组合；不新增重复权限层、不继续旧host兼容改写。旧launch权限分支仅留恢复资产，现代producer不加载。模型来源不能改变hard deny或角色上限；取消仅撤销grant，不假装进程已停止。既有各轮测试不合并不重标最新锁：T029198、T030232、T019306、T020119分别已接受；本次scout只读映射，Root稳定权限核心16输入 receipt `19ea51c1eeea5d54e63a371b4502dea77011913e4472bc401c4afe0544d9cc22`。T033/T034/T037/T040与Full实际组合继续开放，产品gate仍false；正式22/100。
- [ ] T037 [US2] 对 `agents/pi/runtime/`、MCP/Code Mode、用户`!`、各选定扩展和后端逐入口建立 `docs/pi-permissions.md` 覆盖矩阵；裸spawn/直接IO若未隔离如实标记，关闭未获准旁路。 未覆盖的裸spawn/直接IO不得以整个Pi已隔离宣传，新增提供者必须补同一覆盖矩阵。
- [X] T038 [US2] 在 `tests/fixtures/pi/whole-process/`（新增）准备合成恶意扩展、文件/网络/派生进程哨兵及Docker受限场景；测试入口与显式执行前提写 `specs/005-pi-two-profiles/quickstart.md`，禁privileged/宿主docker socket/宿主token复制；不在默认pytest启动容器或宿主。
2026-10-10 T038 准备任务完整验收：八个固定允许/拒绝/凭据可读限制场景、自有 child 与哨兵、封闭 Docker 声明及显式执行前提已写入。Root 冻结 CLI placeholder P2 修正后最终受影响 17 个静态测试通过，原 13 个准备身份保留；稳定差量审查通过，证据 `whole-process-fixture-preparation-review01`。不执行恶意 fixture/Node/Pi/Docker/网络，不把容器内同 UID 凭据可读声明成隐藏；实际 namespace/UID/正反/终止和支持结论仍由 T039 验证。正式任务 12/100。
- [ ] T039 [US2] 执行Q3，先验证标准Docker受限容器、独立Pi原生home/登录、CLI/SSH及工具链，在 `docs/pi-permissions.md` 记录实际版本、威胁模型、支持/限制和负向结果；普通容器不承诺对容器内恶意扩展隐藏原生凭据。缺安装/授权记未测，不作技术不支持；若选支持必须完成真实整进程负向验收，调查结论不能替代必需受管工具隔离。
- [ ] T040 [US2] 通过真实受管入口执行当前Linux OS正反与获准Pi native测试，记录 `docs/acceptance/pi-two-profiles/tool-sandbox.md`；后端缺失/namespace禁用时明确unavailable，不能回退宿主。
- [ ] T041 [US2] 在 `docs/acceptance/pi-two-profiles/base-gate.md` 汇总Base/隔离的临时状态，验证普通编辑/构建提示与开销；M01–M07的Base/共同能力适用子项或其他Base必需项尚未闭合时不得签发Base passed，结果保留not-run/failed、执行状态可为blocked。T047/T048补齐Base两态性能、手册与维护证据后按acceptance.md独立重算；不等待Full专属数据或四态完整对照，继续US7和独立Full工作，不等待Base passed才实施Full。

## Phase 5：US7 — 长期维护与可替换提供者（P1）

**目标**：提前交付升级/替换/恢复机制；完整Full维护、性能与总证据在最终阶段执行。

**独立验收**：隔离候选中冷装/重复部署/失败恢复；至少一组等价提供者替换、失败恢复、不兼容拒绝及卸载残留检查；配置/运行包/数据回退分开。M01–M07机制层，真实组合在最后复验。

**验证入口/前置**：V1、V5；先用Base及两等价替身独立验证机制，不能将替身通过记为真实插件或完整US7通过。

- [ ] T042 [P] [US7] 在 `tests/test_pi_provider_replacement.py`（新增）先写M07：同能力允许/拒绝/取消/故障、激活中断、重复owner、未知来源/不兼容、账号会话哨兵、旧任务引用、旧grant失效和卸载残留；默认两个替身禁网络，断言具体副作用与旧实例仍可恢复。
- [ ] T043 [P] [US7] 在 `tests/test_pi_validation_runtime.py` 增加候选安装未完成、三方漂移、活动实例、旧包恢复引用、磁盘满及配置/包/数据各自回退测试；禁止靠清理用户状态恢复成功。
- [ ] T044 [US7] 在 `src/agentcfg/pi_runtime_packages.py`、`src/agentcfg/pi_capabilities.py` 实现ReplacementRecord“staged→validated→activation-pending→active→retired”；“失败进入restored或recovery-required。”；候选校验后仅空闲边界激活，多文件pending恢复，旧任务绑定旧身份，不宣称跨配置/数据库/进程绝对原子。
- [ ] T045 [US7] 在 `src/agentcfg/pi_vendor.py`、`src/agentcfg/pi_runtime_packages.py` 实现旧引用保护、卸载受管资源及失败说明；“只在允许的空闲边界激活，旧引用未清零不得卸载。”；不删除账号/会话/用户数据，未知旧执行不重派，不让旧代码读取不兼容新库，不自动换弃维护来源。
- [ ] T046 [US7] 在 `tests/test_pi_provider_replacement.py`、`tests/test_pi_validation_runtime.py` 完成冷装/重复部署、版本/等价提供者切换与中断恢复，核对安装/加载/残留/原生home/活动实例和旧恢复引用；恢复后相关证据stale并重验，不假定会话格式透明互通，配置回滚/运行包回退/数据恢复分别记录；本任务完成M07的Base实际组合与替换机制验证，Full实际组合在T095复验，不能仅用两个替身签发Base真实支持。
- [ ] T047 [US7] 在 `src/agentcfg/activity.py`、`src/agentcfg/pi_commands.py` 与 `tests/test_pi_resource_retention.py`（新增）实现有界日志/输出洪泛/背压/磁盘满/保留和清理；重复基础任务检查孤儿/FD/RSS增长，不清理必需证据或活动/恢复引用；高级组件同一约束在各故事和最终阶段复验。 新增 `scripts/benchmark-pi-profiles.py`，按T005冻结方法/预算先执行纯Pi/Base两态对照，结果分profile写 `docs/acceptance/pi-two-profiles/performance.md`；所需授权与有效身份分别记录，Full四态由T093补齐。
- [ ] T048 [US7] 在 `docs/pi.md`、`docs/pi-permissions.md`、`docs/pi-two-profiles.md`（新增）和 `specs/005-pi-two-profiles/quickstart.md` 写短中文启动/认证/模型/权限/恢复/提供者替换及卸载手册；先绑定已实现Base/维护命令，高级章节随对应故事补齐并核验，最终交付不留虚构命令或未填占位。 Base手册逐条核验后汇总M01–M07的Base适用子项并重算T041；Full专属项保留未完成，不借Base通过签发Full或全部US7通过。

## Phase 6：US3 — 可选模型风险审批（P2）

**目标**：Full默认关闭、按需启用的独立reviewer；机械安全与真实模型质量分开交付。

**独立验收**：Base默认/Full关闭额外调用0；启用态allow/ask/deny与故障可区分，取消/失效零执行；冻结开发集与独立保留集六指标达标。P08–P10。

**验证入口/前置**：V6；依赖US2权限/许可/覆盖契约。live质量缺授权可继续US4–US6，但不能签发Full通过。

2026-10-10 权限控制提供者选型执行规则：本阶段先衡量固定版pi-jev完整扩展原样复用，再做仅必要公开接口薄适配；以下risk-review路径可作为rotom接口/策略/许可适配，不预定必须自研判断引擎或重新实现工具拦截/人工确认流程。同一操作唯一审批owner，避免重复弹窗或重复模型调用。保留统一预算、来源、取消和许可契约；同条件质量/维护/费用证据说明最终选择，不因已有代码保留自研。当前不安装/启用新提供者，详见research D17。

- [ ] T049 [P] [US3] 在 `agents/pi/packages/risk-review/tests/protocol.test.ts`（新增）先写fake reviewer，覆盖封闭结构 `allow | ask | deny` 及来源 `hard-policy | deterministic-policy | reviewer | human | system-failure`，将有效ask/deny、超时、provider/协议故障、取消分别分类；无UI ask保持blocked，秘密/秘密散列不进入请求。
- [ ] T050 [P] [US3] 在 `agents/pi/packages/risk-review/tests/permit-races.test.ts`（新增）先写取消/限制收紧/参数变化/重复消费/迟到/等价改写/动态脚本变化反例；用执行计数和模型请求计数验证hard deny/必须人工零调用、有效拒绝不换模型复审。
- [ ] T051 [US3] 在 `agents/pi/packages/risk-review/src/index.ts`（新增）接公开Pi事件与可信PreparedOperation；审批和执行消费同一准备对象，工具输出/模型自报不是用户来源；“模型审查不持有执行回调，不接收认证材料，不带工具，不隐式重试或换 Provider。”，硬策略与角色上限先执行。
- [ ] T052 [US3] 在 `agents/pi/packages/risk-review/src/transport.ts`（新增）实现显式获准路线、实际模型、单请求deadline与计量，禁工具/retry/fallback；从发送边界观察请求次数；查询不推理/下载/登录，取消迟到只记最小账本及调用事实，不能形成决定。
- [ ] T053 [US3] 在 `agents/pi/packages/risk-review/src/decision.ts`（新增）及 `agents/pi/runtime/permission-access.ts` 合成ApprovalDecision和一次许可；有效绑定且硬策略允许才allow，ask等待人工或blocked、deny不经等价改写翻案，来源/原因码/绑定/时限严格验证，旧grant不能交给新provider。 allow合成须满足原样约束：“只有硬策略已允许、风险类别允许自动通过且所有绑定仍为 current 时，才能合成为 `allow`。”。
- [ ] T054 [US3] 在 `tests/fixtures/pi/risk-review/manifest.json`、`tests/fixtures/pi/risk-review/development.jsonl`、`tests/fixtures/pi/risk-review/heldout.jsonl`（新增）冻结样本、标注规则、独立保留集与预算revision；包含授权编辑/测试、复合命令、撤销、指代、注入、动态脚本和协议失败，不因候选表现改标签/阈值。
- [ ] T055 [US3] 核对实际授权后执行真实reviewer评测并保存 `docs/acceptance/pi-two-profiles/reviewer-quality.md`，危险命令只评判不执行；分别计算规则/模型/协议、误放行/误询问/覆盖/延迟/成本，失败不改标签。 使用 `scripts/evaluate-pi-risk-review.py`（新增显式live入口），六指标必须含协议失败率；不自动运行或执行被评判危险命令。
- [ ] T056 [US3] 在 `profiles/pi-full.toml` 和依赖切片提供按需启用，Base不安装reviewer专属包；验Full关闭零调用、普通操作不逐次review、无需TK/Durable。
- [ ] T057 [US3] 在 `docs/pi-permissions.md` 提供smart/manual状态、拒绝理由、一次人工处置与失效说明；独立审查P08–P10，质量未过不能靠默认关闭宣布Full完成。

## Phase 7：US4 — 统一、有限委派（P2）

**目标**：Pi/Codex入口共用核心与首批两个后端，真实生命周期、Writer和预算可核验。

**独立验收**：两宿主×两后端分别提交/观察/消息/继续/取消/结果；同run可核对，未知不重派，跨profile只一个Writer，普通小任务直接完成。F01–F04、F08–F10、X01/X02/X07。

**验证入口/前置**：V7；依赖共享基础和US2，Q4正式公开协议未证明的Writer能力不得开放；不等待US3模型质量。

- [ ] T058 [P] [US4] 在 `tests/test_model_delegate_contract.py`、`tests/test_pi_delegate.py` 先写幂等冲突、消息序列、同run继续、unsupported、启动未回执、cancel ack与物理停止、错误不得包装成功及模型身份核对用例；默认fake backend。
- [ ] T059 [US4] 执行Q4，在 `specs/005-pi-two-profiles/research.md` 冻结官方Pi和Codex CLI（已有0.154.0资产先验）的公开参数/事件/权限/模型/消息/继续/取消能力；隔离候选探测不更新正式锁，native/live须对应授权，私有协议/TUI抓屏不可作替代。
- [ ] T060 [US4] 在 `src/agentcfg/model_delegate.py` 固定DelegateRequest/DelegateRun及submit/status/message/continue/cancel/result；“Pi 与 Codex 入口产生同一规范请求。”，“继续必须绑定同一 run；不支持时明确拒绝。”；requestId同请求同身份、不同内容冲突，approved/taskId/role模型字段不构成授权。
- [ ] T061 [US4] 在 `agents/pi/runtime/delegate-pi.ts` 与 `src/agentcfg/pi_delegate_spawn.py` 使用公开Pi接口完成选定认证、实际模型、权限及继续能力；无法支持的路线明确拒绝。
- [ ] T062 [US4] 在 `src/agentcfg/model_delegate_backends.py`、`scripts/pi-delegate-codex.py` 与 `tests/test_model_delegate_codex_worker.py` 接官方Codex公开协议；映射实际CLI/model/权限/消息/继续/取消，不改全局登录/模型/信任，Full正式资产落锁后重验Q4，不解析TUI或调用私有guardian。
- [ ] T063 [US4] 在 `agents/pi/packages/model-delegate/`、`shared/skills/model-delegate/` 及现有CLI入口接同一核心，使Pi/Codex宿主实际调用，禁止重新实现另一队列。 CLI桥接明确落在 `src/agentcfg/cli.py`，共享Skill入口为 `shared/skills/model-delegate/SKILL.md`；入口不拥有新的执行队列。
- [ ] T064 [US4] 在 `src/agentcfg/pi_delegate.py`、`src/agentcfg/pi_delegate_spawn.py` 和 `tests/test_pi_delegate_files.py` 对接共享WorkspaceLease及监督者；验证消息顺序、同run继续、提交前/后未回执、PID重用/终止未知和非Git受限路径；只释放有终止证明的Writer，Git worktree/status/checkpoint能力不伪装为非Git支持。
- [ ] T065 [US4] 在 `src/agentcfg/model_delegate.py` 与 `src/agentcfg/pi_delegate.py` 投影BudgetLedger `known | estimated | unknown | reserved`、实际模型、上下文、日志/产物/调用；“重启、重连、resume 或 profile 切换不清零累计值。”，发送未知不释放预留，外部未知不显示0/无限，禁止未计量嵌套Writer。 DelegateRun至少保留runId、backend native identity、resume token、实际模型、状态、消息序列、用量和产物引用；“状态来自真实后端和监督者，不从模型文字推断。”。
- [ ] T066 [US4] 从两宿主到两后端执行mock、获准native/live能力矩阵并存 `docs/acceptance/pi-two-profiles/delegate-matrix.md`；只读及受管Writer分别验证，简单任务仍不委派。

## Phase 8：US5 — Task Keeper Inspect/Fix（P2）

**目标**：同一delegate核心支撑固定工程流程与可信接受；TK仅拥有阶段/验收。

**独立验收**：合成C++ Inspect/Fix有唯一Worker、可信checker与必要Reviewer；非零/零测试/全跳过/篡改/旧证据拒绝，最多两轮返工。F05–F09、X02–X04/X07。

**验证入口/前置**：V8；依赖US4正式准入/Writer/结果，不依赖Durable。

- [ ] T067 [P] [US5] 在 `agents/pi/packages/task-keeper/tests/two-profiles-contract.test.ts`（新增）先写固定流程、可信准入、checker篡改、零测试/全跳过/缺输出、最多两轮与失败不被改invalid的反例；断言唯一Worker和具体接受状态，使用fake delegate。
- [x] T068 [P] [US5] 在 `tests/test_pi_input_snapshots.py`（新增）先写未跟踪/配置/策略/runtime/provider/checker变化失效，以及heartbeat/日志/轮询/记账不自我失效；秘密只记引用类别，正文和秘密散列不进入InputSnapshot。
- [ ] T069 [US5] 在 `agents/pi/packages/task-keeper/src/adapters/subagents.ts`、`agents/pi/packages/task-keeper/src/agentcfg-config.ts` 改接统一delegate核心，任务/步骤/角色/范围/预算由可信控制面准入；不只删除UNMETERED_EXTERNAL_DELEGATE，不复制delegate队列，不继续要求独立pi-subagents调度器。
- [ ] T070 [US5] 在 `agents/pi/packages/task-keeper/src/orchestration/workflow-plan.ts`、`agents/pi/packages/task-keeper/src/orchestration/service.ts` 实现固定Inspect/Fix与Workflow阶段；“Inspect/Fix 最多两轮定向返工；超过后保留未完成并交主代理决策，不把 exhausted 改写为成功。”；唯一Worker、必要独立Reviewer，小任务仍直行。
- [x] T071 [US5] 在 `src/agentcfg/pi_checks.py`、`agents/pi/packages/task-keeper/src/verification/runner.ts` 冻结TrustedCheckBinding的checkerId/实现/argv/通过条件/可信配置；“Worker 不能修改 checker、通过条件或其权威配置。若 checker 位于 Worker 可写范围，检查无效。”；非零、零测试、全跳过、缺配置要求的 test ID/输出/终态或错版本工件不得接受。必需 ID 来自可信检查配置，旧绑定未声明时保留聚合计数语义，不声称已核验具体 ID。
- [x] T072 [US5] 在 `src/agentcfg/pi_input_snapshots.py`（新增适配）、`agents/pi/packages/task-keeper/src/evidence/context.ts` 实现相关受跟踪/未跟踪输入闭包、配置/策略/runtime/provider/checker及环境身份；“heartbeat、日志增长、轮询时间和用量记账等纯观测字段不进入语义输入身份”；产物排除显式，预算每次准入独立复核，不默认全仓索引。
- [ ] T073 [US5] 在 `agents/pi/packages/task-keeper/src/evidence/status.ts`、`agents/pi/packages/task-keeper/src/evidence/evaluation.ts` 区分执行、checker、Reviewer和接受，EvidenceRecord有效性为 `current | stale | invalid`；“非零、零测试、全跳过及语义断言失败都是 current 的失败证据”，完整失败不得隐藏为invalid；只有current且独立oracle达标支持passed，终端可审计划/diff/问答。 EvidenceRecord至少含profile/runtime/config/platform/检查ID/层级/规范输入、真实入口/cwd/起止时间、协议状态、退出/测试计数、终止证明、产物和未知项，字段缺到不可核验时invalid；“测试结果与有效性分开”。
- [ ] T074 [US5] 用 `scripts/verify-pi.py` 的taskkeeper-lifecycle mock适配及新增故障fixture验证准入伪造、双Writer、撤销、取消、两轮返工和恢复预算。
- [ ] T075 [US5] 经授权完成合成C++ Inspect/Fix真实宿主/模型场景与独立review，在 `docs/acceptance/pi-two-profiles/taskkeeper-lifecycle.md` 保存输入/检查器/模型身份，不能只用SDK示例或单元通过代替。

## Phase 9：US6 — Durable 持久只读任务（P2）

**目标**：Full按需独立服务，单owner与持久只读任务，恢复保护未知副作用和累计预算。

**独立验收**：实际入口提交→关前端→重连→服务重启→取消→结果；保持同ID，业务写/Shell拒绝，unknown不补发，查询零scheduler，单owner与公开WAL/FULL可观察。F11–F16、X01/X05–X08。

**验证入口/前置**：V9；依赖US2与共享身份/预算接口（US4），不依赖TK；Q5失败保留Full未交付。

- [ ] T076 [P] [US6] 在 `agents/pi/packages/durable-service/tests/protocol.test.ts`（新增）先写协议版本/未知字段/授权伪造/同ID冲突、status/result/watch零调度零模型、断连/背压、registry同名不同内容拒绝、业务写/任意Shell禁止与服务不可用不得降级用例。
- [ ] T077 [P] [US6] 在 `agents/pi/packages/durable-service/tests/recovery.test.ts`（新增）先写fake SDK/Provider持久化和发送切点、计数oracle、取消迟到、输入变化与预算unknown；“prepared→sending→result-recorded→settled”及unknown/not-sent分支，先红后实现，不将mock证明冒充真实SQLite或宿主证据。
- [ ] T078 [US6] 执行Q5，在 `specs/005-pi-two-profiles/research.md` 核对正式 `@earendil-works/pi-durable@1.0.1` exports/Harness/Registry/Storage/Provider、SQLite公开设置、恢复/重试/压缩全部发送路径和认证路线；隔离候选不修改正式锁。无法通过公开接口覆盖准入则阻塞/主代理重选，不能私改连接、SDK或全局fetch。
- [ ] T079 [US6] 在 `agents/pi/dependencies-modern.json`、`locks/pi-modern/manifest.json` 固定Q5通过的SDK/存储/registry正式组合，仅Full安装；在 `agents/pi/packages/durable-service/package.json`、`agents/pi/packages/durable-service/src/deployment.ts`（新增）固定DurableDeploymentIdentity的SDK、公开adapter/配置、schema、registry内容及工具清单，打开存储前检查兼容性。
- [ ] T080 [US6] 在 `agents/pi/packages/durable-service/src/server.ts`（新增）实现Full显式请求才连接/启动的本地Unix socket；目录/文件所有权和链接校验、连接用户及任务授权均验证，同UID不等于管理员；控制目录/认证不挂给受限任务，普通启动/编辑/诊断零服务启动。
- [ ] T081 [US6] 在 `agents/pi/packages/durable-service/src/owner.ts`（新增）实现“同一 Durable 存储同时只有一个写所有者。新 owner 必须先证明旧 owner 已退出或完成恢复接管。”；按部署/私有目录校验→原子owner锁→旧owner/格式核对→开库→未完成对账顺序，boot/process birth/epoch齐全，PID或心跳超时不足以接管。
- [ ] T082 [US6] 在 `agents/pi/packages/durable-service/src/storage.ts`（新增）用公开SQLite适配设置并读取核验WAL/FULL；受理确认、外部发送、结果通知之前完成对应持久写，满盘/只读/失败停止新副作用；缺公开配置接口则按Q5替代/阻塞，TK SQLite与Durable存储独立，账本不复制任务队列。
- [ ] T083 [US6] 在 `agents/pi/packages/durable-service/src/requests.ts`（新增）持久化DurableTask稳定request/task ID、授权/只读能力/产物/快照/状态/消息/epoch/结果/终止证明；状态完整采用data-model第6节，覆盖“accepted -> queued -> starting -> running -> completed | failed”及unknown/blocked分支，同ID同规范输入同任务、不同输入冲突。 对accepted持久确认失败不返回成功，queued/starting/running及终态按存储事实报告；状态不同于结果/账单/证据有效性。
- [ ] T084 [US6] 在 `agents/pi/packages/durable-service/src/registry.ts`（新增）仅注册受限读取/搜索，业务根只读、专用状态/日志/产物可写且防别名越界，无任意Shell/完整CodingTools；原样遵守“产物发布到业务位置需要新的显式操作与权限。”；原生获准凭据不复制token，客户端不能扩读根/工具/路线。
- [ ] T085 [US6] 在 `agents/pi/packages/durable-service/src/model-attempts.ts`（新增）实现attemptId、task/phase、registry/input/policy、model route、预留/发送状态/result引用；“先持久sending再发请求，崩溃后无确定结果为unknown，不自动补发。能证明未发送才转not-sent释放预留。”；重复响应按attempt归并，账本无认证正文且不作第二队列。
- [ ] T086 [US6] 在 `agents/pi/packages/durable-service/src/provider.ts`（新增）用公开Provider包装实现唯一发送准入，覆盖SDK初次/恢复/重试/压缩/后台总结；关闭隐式重试，unknown阻止该任务后续付费发送，其他任务可查询/执行；只读status/result/watch不能调用SDK wait/resume或启动scheduler，无法证明覆盖则Q5失败。
- [ ] T087 [US6] 在 `agents/pi/packages/durable-service/src/client.ts`、`agents/pi/packages/durable-service/src/observations.ts`（新增）及 `src/agentcfg/cli.py` 接逻辑submit/status/message/continue/cancel/result/watch与Pi公开入口；同task消息/继续，快照+有界订阅/慢客户端重置，断前端仅移除观察者；记录真实命令到 `specs/005-pi-two-profiles/quickstart.md`，不虚构已有子命令。
- [ ] T088 [US6] 在 `agents/pi/packages/durable-service/src/cancel.ts`（新增）实现“queued/running -> cancel-requested -> stopping -> canceled”和“starting/running/stopping -> unknown | blocked”；先持久取消/撤销未用许可再中止工具/Provider，仅SDK静止及外部活动终止证据齐全才canceled；响应可取、费用结算与物理停止分列，无UI不默认批准。
- [ ] T089 [US6] 在 `agents/pi/packages/durable-service/src/recovery.ts`（新增）先恢复owner/部署/registry身份并对账，再准入SDK恢复；“unknown -> reconciled-running | completed | failed | canceled”，不热换同名registry；安全读取仅输入/授权一致重放，未知模型不能随工具safe重发。预算 `known | estimated | unknown | reserved` 累计不清零；明确新授权只创建新的有界attempt并保留原未知预留。
- [ ] T090 [US6] 在 `tests/test_pi_durable_processes.py`（新增独立进程suite）和 `agents/pi/packages/durable-service/tests/recovery.test.ts` 注入intent/commit/发送前后/回执窗口、真实双owner竞争、PID重用、SIGKILL、满盘/只读/丢响应；观察原ID、发送计数、占用数、预算和终止事实，实测SQLite设置；进程kill不冒充断电/介质损坏保证，所需故障层分别记录。
- [ ] T091 [US6] 在 `agents/pi/packages/durable-service/src/maintenance.ts`、`agents/pi/packages/durable-service/tests/maintenance.test.ts`（新增）实现SDK/schema/registry兼容拒绝、停止写所有者后的副本备份恢复和迁移失败；旧活动引用保留，旧版本不开不兼容新库，旧registry缺失不可用同名新版续跑。
- [ ] T092 [US6] 从实际Pi产品入口演示提交→关前端→重连→重启→取消→结果，保存 `docs/acceptance/pi-two-profiles/durable-lifecycle.md`；服务不可用时普通编辑通过，Full持久路径不得降级为短期任务。 扩展 `scripts/verify-pi.py` 的显式层级场景并把确切入口加入quickstart；同时保留原任务身份、服务健康与普通编辑互不阻塞的证据。

## Phase 10：Polish — 全组合验证与最终交付

**目标**：对稳定的最终组合闭合各故事真实层与交叉约束；不以Base阶段交付结束长期目标。

**独立验收**：当前Linux必需账号/体验/Base/Full/隔离/维护gate全过，63检查适用必需项及8不变量有current证据，无严重未关闭审查发现。

**验证入口/前置**：V10及各故事受影响回归；只对稳定diff作最终审查，无新问题不反复全量审查。

- [ ] T093 用冻结方法与预算执行纯Pi/Base/Full idle/active及smart开关对照，结果存 `docs/acceptance/pi-two-profiles/performance.md`；记录实际样本、人工TUI、模型等待/本地耗时和取消延迟，失败优化后重测。 用 `scripts/benchmark-pi-profiles.py`（复用T047的显式入口）区分本地/模型等待，复核启动、首就绪、RSS/CPU、上下文/工具元数据、终端交互、取消延迟和释放；Full idle零隐式模型/Worker/Durable。
- [ ] T094 在当前Linux完成尚未闭合的真实账号、国内路线、C++/Shell/Neovim、SSH/终端体验和两profile演示；授权不足只阻塞对应项，状态写入 `docs/acceptance/pi-two-profiles/linux-experience.md`。 独立记录US1–US7缺失native/live项，不用同一个演示覆盖未观察的矩阵格。
- [ ] T095 对共享基础及提供者替换重跑两profile相关回归、DSH/OMP受影响配置契约与冷安装，核对最终锁/来源/完整性、替换后的加载集合及旧入口退出，相关旧证据失效后重新验收，在 `docs/acceptance/pi-two-profiles/maintenance-final.md` 汇总。复验US7的M07真实选择、Durable数据恢复与各高级组件资源释放，并闭合T002两profile资源/行为差量及声明与实际发现核对；先前Base/替身结果不能自动升级成最终Full维护通过。
- [ ] T096 逐条运行/核对 `docs/pi.md`、`docs/pi-permissions.md`、`docs/pi-two-profiles.md`、`specs/005-pi-two-profiles/quickstart.md` 最终中文手册命令，覆盖两宿主委派、审批、服务重连/取消/恢复与提供者维护；诊断无秘密正文/散列/原始内部认证日志，OS/native/live分别引用证据。
- [X] T097 对可选项目/会话Stop hook核对公开支持、故障/无进展/停止/其他会话行为并写 `docs/pi-two-profiles.md`；用户未信任或不支持记inactive，不阻塞产品、不改全局配置/信任库。

T097验收（2026-10-11）：固定官方1.0.1公开声明确认agent_end/agent_settled/session_shutdown事件；scope明确未选择Stop hook，当前inactive，启用态故障/无进展/停止/其他会话场景不适用，不伪造运行通过。原生会话恢复已有独立记录，事件不作接受或物理终止证明。未执行hook/模型、未改信任或全局配置；Root五输入收据`e8435b14d0067aa0f37cccb1243a4b26eaa73b458896e4b8b19726db6177832d`。
- [ ] T098 在写入完成后的稳定diff或commit上进行最终独立安全/错误成功/恢复/性能/复杂度/Base污染审查，记录 `specs/005-pi-two-profiles/review.md`；修复严重发现后复核受影响边界，修改期间审查仅作阶段性证据，不无限重复全量审查。
- [ ] T099 在本任务最终scope和 `docs/acceptance/pi-two-profiles/final-gates.md` 计算Base/Full/隔离/维护/当前Linux/账号/体验gate；保留所有failed/not-run/needs-login/stale，不凭任务勾选签发通过。
- [ ] T100 更新 `specs/005-pi-two-profiles/plan.md` 的最终状态，交付配置/代码/锁/入口、取舍/加载清单、演示、性能/用量、手册及一次性切换/回退步骤；只有全部必需gate通过才标总完成，默认切换/推送/合并另按授权。

## 依赖图与执行顺序

2026-10-07 当前组件记录（不是正式任务或产品 gate 的勾选证据；正式仍 7/100）：

| 状态 | 组件与本轮证据 | 下一条件 |
|---|---|---|
| 已完成 | 九类纯初始化消息 codec 的两NEW文件，指定四suite同次402passed/2.42s、无fail/skip；独立稳定审查0P1/P2及root验收26输入receipt `ed62af290b009f8a45bfc03b6f967cb331ed9906700506f609d53b87bb04920b` | 仅默认组件已闭合，不授来源/IO/Node/DB权限 |
| 已完成 | 纯InitReplyWindow两NEW文件、六suite同次724passed/5.61s，无fail/skip；独立稳定0P1/P2及root验收30输入receipt `01963ba9f1360d3747aa22fe8ad0e679ae131f1e3316db228e785c9bf7a2d348`；Full-only origin方向14输入34b85a74已接受 | 纯窗口不授sender/source/IO/DB权；origin仅路线方向 |
| 已完成 | 六个uv.lock原wheel源字节与被动成员清单14输入receipt `325b8f445ab50d96e8ece2ceb0b58f54338dfacd45ffc710f0437457865560a1`；独立controller寿命方向复核0P1/P2、18输入receipt `ed1a63795f5af3390b386c2b7e3f18a922a00ca6f6830d210ea40eaa80102b0c` | 源材料不等于完整依赖/ABI/安装/原生资格；寿命仅方向，新的activation/hold接口仍待冻 |
| 已完成 | resolution共享数据内核与仓库兼容，原六suite278pass/2个v1不适用skip；caller异常上下文P2真实red1fail→最终受影响包47pass/2skip，独立稳定增量0P1/P2，34输入receipt `eab9336f0663f09a3d0f0695f3cd015c03adeebe35983ae372ffe9dc4dc5d3a7` | 原仓库schema/recipe/source/archive/build/license等保留；不同轮次不相加；只默认数据规则获验收 |
| 已完成 | v2 invoked PyYAML与声明缺口9输入receipt `39346460b6cb4f7521e8a052644b3ee8c1414081d47a78bb6fc04dee9fbe372f`；PyYAML锁定原wheel806638B/28成员被动取证9输入receipt `8a886afda47d97203b17469969400875f7e5988dc34e76b7da6d25fcd496a561` | 原档字节/被动成员事实，不签RECORD语义/许可充分性/签名/ABI/installed；完整闭包仍待补 |
| 已完成 | [header/resource有限接缝](durable-lock-header-resource.md)三文件稳定0P1/P2，31输入receipt `a3f02b19f4c809c6cf7de3f45f98d47270e65aaf56049346414073550d69b845`；首次318pass/5文案期待失败/2skip，修测试后受影响header44pass/0skip；首轮其余六套279pass/2skip分列；三叶imports限定6输入cb3a9698已接受 | schema/version/identity→recipe→bindings原顺序、独立完整旧基线保持；不称单次323pass，strict installed资源/声明/完整来源未签 |
| 已完成 | [显式selection数据入口](durable-selection-data-api.md)两文件稳定0P1/P2，30输入receipt `9d7002984b608160eea831169a247613048d22c7d43c0eb6631a8f045c020f49`；八suite一次365pass/2旧v1skip/52.89s，42新case零skip；独立旧resolver/context/proof与前像逐字相等、shared VERSION lazy接线 | 原十字段/digests/错误/proof与stable-data合法域保持；v1无现代合法selection，不新增identity等式/header gate，不签source/issuer/hold/activation/native |
| 已完成 | 七wheel所选METADATA/WHEEL/RECORD与原被动inventory对应事实，15输入receipt `552a8c24e78a5d8f86a449275b49316f570c8697bc1bff744566b908050ab1f0`；163 files/4显式空目录、25依赖规则8active/17extras inactive；原archives引用已有source receipt，未重复制或执行 | 仅元数据／内部一致性和原hash对应，不签所有guardian闭包、实际安装、许可充分性或ABI；bwrap source-only静态6/d93346f0同样限定 |
| 已完成 | [Python bundle数据契约](durable-python-bundle-data-api.md)三data API及原三P2修复273pass历史保留；合法Dynamic与双许可增量同两文件，原4真实fail→最终新套件一次387pass/44.08s、稳定0新/openP1P2，25输入receipt `f43e4cf29f88c91d670ab30700668358149529ede2cfe7c999ad93deff290fff` | 仅合成默认组件；114新增、原273不动，轮次不相加，旧三suite不重跑；actual stage/source/Full/schema/controller/activation另包 |
| 已完成 | 同七原档案／相同declaration的纯数据编译inner0/0.424s，163files/40dirs/4,942,283展开字节、25rules8active17inactive；稳定证据0新/openP1P2、13输入receipt `c18ae514b853d1226adbf6c6c0545281a5f1ad70e4d8fdfdab559a0055758af2` | 仅数据一致性／实际档案校验；不含实际安装／第三方import／ABI／publisher／许可法律或Full来源；旧失败保留 |
| 已完成 | [私有scratch stage组件](durable-python-bundle-stage.md)两NEW文件默认验收：稳定审查发现已有目录无关大小写别名误拒P2，原源2fail/3pass→同范围5pass、受影响27pass→完整新套件一次204pass/18.30s/inner0；稳定增量0新/openP1P2，32输入receipt `f62dee9e792ee77e2daa5fe54da0b1545bbd72ec255da142e5fdc3e96ace5538` | 仅合成临时FD/IO组件；原199字节保留、五新增，初始35输入open receipt `463ff8852840ae7ace54563364c2b90b63628fbcc7f59ecd0325b1d584e1611f`保留三guard失败及198pass/1fail测试自读atime问题；无产品caller／正式Full/sourcehold接线 |
| 已完成 | 七已捕获固定档案的被动临时stage写入/回读inner0、0.527s：163原成员加canonical inventory共164文件、40目录，4,942,283原展开字节；独立静态证据0新/openP1P2，21输入receipt `1bd87e9d95564214a40e4489d929ef62bdeb8748bcd07050b2c8106ccf319f73` | 仅临时物理数据IO；第一次旧cache预检inner1/95ad记录保留，修后使用三份原字节自有源码副本；未import第三方/native，不授Full来源、ABI或产品stage资格 |
| 已完成 | [wheel source/ref四数据API契约](durable-wheel-source-contract.md)限定字段、HTTPS离线语法、版本/成员配对、Base冷路径及原错误边界；首核两P2修后增量0新/openP1P2，11输入receipt `b4d95038f505562d3b645e5fb9172c28d50f0448a6da316857fcbdf7ff5f31d2` | 仅设计与两新文件实现范围；原稿事前实际捕获，未授权schema或caller，公开数据不签来源资格 |
| 已完成 | 四数据API首版233项后修复单次caller快照P2；原233字节不动、15追加，原源9fail/6pass/8errors→15pass→完整248pass/3.67s；独立稳定增量0新/openP1P2、43输入receipt `31d047be350eae7ea6139d86b601c481d852e2596da9faa1501e4523c3789ed7` | 仅默认数据组件；首四轮与46输入open receipt `11e825172dd32af4520fad623e258dfc1e0bbeefb6d5299672beb8557780aed7`保留，late mutation不签原子/sourcehold能力，caller/schema/native/product资格仍独立 |
| 已完成 | [wheel锁数据接线B1](durable-wheel-caller-contract.md)根file白名单P2旧源4fail/24pass→同组28pass→仅解析器/新integration148pass/2skip，稳定root增量0新/openP1P2，41输入receipt `2991ae630094258852da69880b4b7b615907193c15b2d60d3fab7e83f359f5e7`；旧75输入open与七轮原失败各自保留 | 仅六源schema/锁caller数据接线；原73前缀保留、新28追加，schema逆去与完整旧JSON深相等；Base原recipe公共bytes扫描保留，其后不读所选body/vendor/core。独立executor线程不可用，root最终正确性与scout schema有限证据分列；B2物理安装、Full来源及产品资格未签 |
| 已完成 | [B2默认安装接线](durable-wheel-stage-integration.md)冻结八target后root稳定验收77输入receipt `cde031bb1fd6dc04c9214c7560b5427a169e11d8d67b9fa0b1dff1e75097f839`；首轮175pass/3fail中runtime69已绿不重跑，实际原seal后receipt闭合shape拒ref的P2保留40输入open；必要schema旧源3fail/18pass→定向25pass→同次受影响261pass/54.04s，无skip | deps39/runtimeFiles91/integration131，各轮不相加；原100正文26148B保持，仅移除已过期722B阶段函数，B1完整101历史不覆盖。原producer/hook/seal/activate/status真实执行，进程为fake；schema逆去与旧JSON深相等，独立scout仅核schema/测试，root审完整新helper/69测试及caller/integration diff，无额外executor线程。Full正式来源、CPython/ABI、sourcehold及产品资格仍未签 |
| 进行中 | [current公开部分候选](durable-current-public-projection.md)原producer/嵌套validator/两身份编码有限证据13/7/6输入d6dd26/52f5aa/773c45；三个域/opaque捕获设计P2修后有限候选已接受10输入receipt `b19fde9425e975432d0c115944f42928b0acaa5aedef619cf5efb31977e45a95`，完整FullSourceView/IO仍未冻结 | 排除generation/preimage/whole state与私有环境；原identity缺省编码有明确标记且null不能fallback；pi-full/hex64是新入口支持前提，须实际原caller再核。不授权另建提前签发模块或source IO；现有saved-state不能认证current/launch公开shape |
| 已完成 | [物理投影方向](durable-source-physical-projection.md)有限设计9输入receipt `7fa3bd1216df678e6cfdb345d02037416a9c80c1e823625c88a3d25ca330d5ce`；physical/startup三段澄清8输入receipt `f3663f8a52d8fcca341ed686b6ae14449822f7fc69400629c46af1336f1b96b8`，逆去新增段落逐字节回到真实preimage | 仅文档方向；十进制转换前限长、stat变化关联不声称隐私不干扰、generation仅由原actor私有方法核。完整schema/codec/来源IO/长期hold未实现或授权，不能据此勾正式Full任务 |
| 已完成 | [完整锁metadata数据接口](durable-lock-metadata-data-api.md)三target稳定默认验收106输入b89202；随后29输入receipt `c938483bac7a95b6f387c48e0503ef3ef10b83d8a140de399d12889db3ce84a9`把6292B一次迁移整文件hash审计移出永久pytest，精确逆插回完整原test且保留函数/AST相等；当前完整新suite76pass/10.77s。原九suite553pass/2旧v1skip/87.42s仍适用、未重跑 | historical77/66、ENOSPC未知inner及Data祖先248fail/305pass/2skip分列保留，不相加。生产两模块无改；整deps b6/23788B与四核审计仍在冻结快照上可复现，不阻以后producer/runtime合法演进。root验有限稳定diff、actual collection/log/XML；无额外executor独立代码审查，不签installed闭包/来源/hold/产品资格 |
| 已完成 | [installed origin材料方向](durable-installed-origin-materials.md)有限原producer、runtime identity完整函数不变及候选格式方向21输入receipt `9b59cee272f4b8d7d20f1550614bfce72c4569bd948d8b75064d556369037fd5` | five-key envelope不含自己的source identity/preimage或资格；正式缺bundle row与完整helper/schema闭包，exact格式/角色/IO仍待冻结，不授权writer/reader或正式锁 |
| 已完成 | 默认验证空间恢复：仅认领且已结束pytest-1114/1115/1116字节与硬链接关系保留后回收原tmp副本；不触未知或活动目录；Data basetemp被原安全祖先规则拒绝后改独占安全/tmp，affected03完整通过 | 只为后续默认验证恢复空间；目录inode/ctime改变，不算连续持有/source资格；没有放宽HOME/offline/fakeprocess/路径guard。两个环境失败与原失败计数分别保留 |
| 已完成 | metadata入口静态import/分发缺口4输入receipt `377c28e0bb1e7169c5d1d0d73dd85909440769329ee17778a97785fc3122785e`；实际32个自有模块与jsonschema/referencing/yaml roots，当前modern只声明Base、缺15个自有模块及固定supervisor/schemas/pi-lock.schema.json；ended affected03 fixture保存/回收12输入72dc3fd3 | 仅读限定调用图与module-scope edges，动态/第三方/整个controller闭包未证明，不称Actual Full；第一次自动审批deadline未启动、唯一分拆retry成功，字节/硬链关系保留不称inode/ctime连续持有 |
| 已完成 | [B3 origin默认材料接线](durable-installed-origin-production.md)11target STOP后root稳定验收86输入receipt `28d18a7ca53fcb3f451d7897d9204e0c8dc0bde8f8c778361094190cf0094491`；new02一次83pass/84.72s，原前缀完整保留后追加真实旧installed保留case另次1pass/4.50s；原affected01 479pass/2fail/54err保留，56具体未成功节点六小批54pass/2旧v1不适用skip，XML精确覆盖 | 默认材料only，不称一次84/535pass。原producer→origin读回→精确集合→原seal/activate/status同次context闭合；两schema逆全旧JSON，旧test只两获准迁移audit共11+5行移出固定工件、精确逆回40713B。root完整代码/受影响diff审查＋scout限定结构证据，没有额外executor全实现安全审查。完整source/principal/hold/解释器/native/正式Full/产品仍未签；下一完整来源接口沿双actor本地重核 |
| 已完成 | [B4 installed只读观察](durable-installed-source-observation.md)三target STOP后root稳定默认验收93输入receipt `7c7e365d3adec97598e45c02bcfe3488c1ddef5e7fa6c3f9e7971c5aa8f456bd`；93新case首轮92pass/1fixturefail保留，wheel目录选择仅一行修后该原节点1pass；八旧function实际10nodes分八批全pass/零skip/error | 跨轮覆盖不称一次93pass。原status完整顺序/catch保持，AST审计与final050ef8 pin对应；新source63d2d68e与test2141475f固定。两代码P2语义根/重复entry已修且受影响用例实际覆盖，root完整初版＋最终delta审查；scaled caps及合成UID/重复项不签actualFull最大值、旧链资源硬限、原子snapshot/sourcehold/角色或产品资格 |
| 已完成 | [现代启动契约](modern-launch-contract.md)四文件 STOP 后 root 稳定默认验收197输入receipt `9665b731cdd863c544f9c7d8b6ac7e6ec035376b1ca1e5a4ed7647915bcf7e02`；new02同次73pass/36.71s＋追加资料分工单项另次1pass/2.98s，旧六函数实际12nodes分六批全pass/零skip/error | 当前74跨轮覆盖不称一次74pass，首轮45fail/27pass原样保留；精确旧test逆全6922B，原runtime尾部与只读源码保持。实际validate_selected与record/apply/readback使用明确合成backend，candidate原门拒绝保持。正式modern manifest仍缺，实际安装/backend/Full/source/native/product未签，AUTO OFF |
| 已完成 | [summarize关闭/公开重开三场](native-durable-summary-recovery-probe.md)d61799精确授权后一次actualrun，46输入receipt `8059bd7f417bca109a35c94726dc33d986fcb220f346924e89eca29be6e1f879`；3/3started/observed/complete/exit0，12来源端点稳定、48原工件/21files一致 | 新有界A2 summary12/entry11/head8、calls1/settled2/reserve0；拒绝freshprepare/send0；A1 sending/unknown在close/passive/final保持calls1/reserve10/settled0。namespace/actualRuntime/Context原unknown；无重跑，授权已闭合，不签owner/crash/费用/计量/Full/product，default64与native3不相加 |
| 失败待决策 | B1根file引用P2已由同新套件真实red/green与稳定增量闭合，原75输入开放证据保留；f3243原档案inner1已由c18ae同数据边界闭合，原失败与3068诊断保留；旧proxy-agent-negotiate包级MIT正文仍unknown，已决定官方9.0定向覆盖并由新candidate闭合该选型阻塞，旧许可缺口保留；原P219输入147ec3d1、首网络URLError和RPM临时锁宏失败保留；两轮UID guard分别113/9属环境不足 | 不删历史失败，不将源collector/验签当产品测试；当前未发现未解决B1问题，B2另验收，新问题按两有效尝试升级root |
| 已完成 | [Base共享解析模块声明](modern-base-runtime-declaration-closure.md)两文件 STOP 后 root 默认验收106输入receipt `9b2e909b990057ee348155f03866d5945fce2bb5af909a87155afa2e607df2fb`；实际缺模块1fail→新2pass，旧三批10nodes全pass；Full名单唯一常量修正后新2项另次pass | 声明从105到106行，逆去整个原38646B相等；29私有模块均来自原物化目录。只接受共享声明缺口，未执行宿主/SDK/native或签解释器/Full/source/hold/产品；封存脚本三个exit1另列，不冒充产品red |
| 已完成 | 官方npm11.19.1私有工具材料13输入receipt `b31b4f6226dcce8259e8bf91a8659d78e38af8de8e4782ce90bc086cf9414e57`；tar SHA1/SRI匹配metadata、1943files/460dirs逐项hash/mode/links核验 | 下载默认DNS失败与正常网络开发重试成功分别保存，未运行JS/Node/npm/resolver，不改nvm11.9.0或声明pin；signatures未独立验证，材料不签来源hold/产品 |
| 已完成 | [modern候选解析历史诊断](modern-base-candidate-resolution.md)：execution03当时原license门拒绝，inner/wrapper1，无成功candidate/readback；146samepaths/order、141sameidentities、五版本/URL/SRI差异；后续seed由execution04实际闭合，新145图execution05另接受 | 身份差异是充分拒绝条件，不证明唯一前门原因；root诊断receipt `1aef15d032352dcfba94740e9bd20180061f3cb52e011b222b21bd52c97b5c74`。不刷新版本、不放宽原门、正式锁/native/product未签 |
| 已完成 | 原public rmtree诊断组件默认21pass/独立0P1/P2与execution03真实两JSON捕获/hash/readback/原异常与清理保留 | 只签限定开发诊断；scaled cap测试不冒充32MiB压力测试，不签sourcehold/host/产品资格 |
| 已完成 | [固定npm解析输入默认组件](modern-npm-resolution-seed.md)：五文件STOP后root稳定receipt `8b523b5b11378c261e39035f81b9a2689b6386959b3b98a35cb53b8e5f79a3f3`、独立有限0P1/P2；原red1fail→39pass，2修4增另次6pass，旧25六批全pass | 当前43为跨轮覆盖；raw逆审计与actual archives/REGISTRY146只签材料数据，实际解析另验；永久counts可按已审查新selected/registry演进 |
| 已完成 | seed后完整源码2204files/231dirs/48,522,706B新receipt `8a9dda163f0e304835cea52aed3e00dddcb7b3a6dae51f30ea864513de9a35de`；execution04一次实际9.546608s、inner/wrapper0，原PiBackend→read_lock返回Base候选；root终态23输入receipt `1ff8237326fd22a761ec3dd039cef98c968b909d9aa7554d5d77cd36e485cb34` | 固定72800B锁全bytes不变、146九字段identity有序全同；2210复制pins与35自有模块对应已核，受控组empty/临时根absent。只签候选解析，不签许可安装/Full/sourcehold/产品；01–03历史失败保留 |
| 进行中 | 原 proxy-agent-negotiate@1.1.0 的版本绑定正文仍 unknown；已按实际官方材料转向有限 9.0.0 代理依赖覆盖候选 | 精确上游路径是已查历史线索；fresh metadata/commit 未证明新包正文继承，不用通用 MIT，也不放宽旧 installed unresolved 门 |
| 已完成 | [Python发行信任标准](durable-controller-publisher-trust.md)：官方文档指定HTTPS key入口、fresh env-i原key字节相同、既有两RPM签名对应，独立有限0P1/P2、18输入root receipt `b2cda77711f6f7ce39adcd79823afe84b7199dfb8f8fb80a4c4ac07f65ed284a` | 采用明确vendor_https_bootstrap，独立指纹公告仍未证实；不签完整loader、manager、Full或运行资格 |
| 已完成 | 两官方 proxy parent 9.0.0 的固定 tgz、完整包内 MIT 正文及公开一参数构造器静态兼容已接受；19 输入 root receipt `196b665154946aa4deb8af052c1974337f0991700d38a97da574c38a64962a44` | SHA1/SRI、成员数/bytes 与 actual capture 对应；原包不修改，不代表实际 overrides、安装、SDK 或代理行为 |
| 已完成 | [Modern npm 定向覆盖默认代码](modern-npm-dependency-overrides.md)：三个 target STOP 后完整 delta/新增 helper与test/实际 XML 核验，有限独立0P1/P2，85输入 root receipt `3c74789f265422bee1b1db6a2dcc0b1b8cc84ad6ff875cba217921fd4d1ca4d7` | red1fail；new01一次77pass/7.57s，affected01另次64pass/15.71s/零skip。strict selector/typed/seed与direct pin保护；原license/readback门和无字段/legacy保持；此receipt不签实际SDK/安装 |
| 已完成 | 固定 npm 覆盖 private lock-only execution02，12输入 root receipt `8ff6e1458eb91b30c8c27758bdbc337797e482f418b1bab27447d5938dc5dcd2`；145远程节点、所有148共同完整raw记录相同 | 只删top HTTP/HTTPS9.1及Negotiate1.1，新增PiAI私有目录两9.0；gaxios7.0.6与四local不变，npm1943来源首末相同，未装node_modules。首次采集失误/未知完整图的 receipt `7ede68b2…` 保留，不能把第二次证据回填第一次 |
| 已完成 | 新 Base seed/定向覆盖声明、profile 专用 REGISTRY与公共来源 provenance 五文件 STOP 后接受，66输入 root receipt `752c8850dcc171feff2c39818ebf03b9057e9999fc8f6b0d85f1e30037eb351a`，独立0P1/P2；默认两个 actual-data selectors一次2pass/零skip | 三材料与已reviewed准备bytes相同，声明与唯一test整bytes逆回相同；143原许可行保留、2新archive-body，旧global REGISTRY/来源不覆盖。zero unresolved仅图材料，尚未新原PiBackend/安装/SDK/正式发布 |
| 已完成 | 新完整源码 2,206files/231dirs/48,645,711B freeze `1a3d745594d7d8512d2947e51f3e4c7d0869c3a1dab1e3c2b7d552a003851190` 后 execution05 原 PiBackend/read_lock 一次 actual 9.934205s、inner/wrapper0；38输入 root receipt `7a31bff152192cd72a4a1d404653126ed7359eb4f1108316cf4af071a5abbfa1` | Base candidate identity2f99a9…，新72246B锁与seed逐字相同、145九字段有序匹配；2212复制记录、35module与20输出条目（13files/7dirs）核对，groupempty/TMPabsent。不签sourcehold、installed许可/SDK/Full或产品；旧失败保留，原sync候选门不绕过 |
| 已完成 | Python 静态文件/ELF 清单 actual 一次 1.944s：2,513 files、2,433 RPM 摘要绑定、1,779 pyc；137 ELF 图节点/139 metadata commands 全 exit0，首末记录匹配；root receipt `91206c137aaa397498b3296d2769bd76e19d8c745485f2e395714ca8711a696b` | pycache 读取未被 -B 排除；loader cache 仅 opaque hash，375 unknown 保留。仅静态候选，actual dynamic route/manager/import/sourcehold/Full 仍未资格 |
| 已完成 | Python fixed Source RPM 验签与被动源码补齐：20成员、11补丁字面映射、7原始源码／许可、安装 sysconfig signed-RPM摘要匹配；51输入 receipt `38dac03a297fa699bf329358d8bbec95f078a1b5b11641e230927134562a8840` | 初次过滤失败原输出保留，精确名修复后被动重跑成功；未应用patch/spec/build，无真实信号／kernel／manager／loader／sourcehold／Full资格 |
| 已完成 | Python system ELF 35物理端点的私有 RPM DB 副本归属查询，35actual exit0、21exact package headers、3032B raw输出；76输入receipt `a884de31f1d7fe68fa79845c046f935fc4c200abf1a5ca8903298b6530bfd56d` | source只读复制且empty WAL／目录项前后检查，RPM仅获自有副本argv；非atomic／no hold，包归属不验21包发行签名或actual loader／manager／Full |
| 已完成 | [独立Base开发安装](modern-npm-dependency-overrides.md)：install01实际npm ci0、版本raw匹配，原strict source／installed许可145registry rows通过，16653保存条目逐项无差异；37输入receipt `3749a2962388ee5236231b47196537b023b1dd871beb8fff1782ec8575f2feb2` | npm报告added124packages与145registry行不同统计域；candidate／pair未变，源副本保存后清理，比较器误读字段历史保留；不sync/seal/current/activate、无SDK/Full/sourcehold/产品资格 |
| 已完成 | 21个system RPM固定公开位置：42HEAD、21×200／21×404；6输入receipt `b2a63e67c561c9e15f29d9c53dc907abbfd82722f17c1933363ee092b5993f8c` | 首次默认DNS失败保留；HEAD仅位置／header，不签包正文或来源，404不代表全局不存在 |
| 已完成 | 21个system RPM正文实际GET，21.442s、8,958,480B、全部200，保存／读回SHA与HEAD长度一致；25输入receipt `d0af138279f6ca1c29a5cbfb07a31aeb0a192376d69858065f6cf48f1d82c0e5` | 固定URL／无redirect或retry／auth／proxy／安装解包，未执行RPM/native；验签、35端点filelist对应及loader／manager／Full另验 |
| 已完成 | 21个system RPM实际验签／filelist查询43命令全0，86raw／102,922B；35历史物理端点bytes／SHA对应signed regular records，99输入receipt `a1b6b4ec91d681145c98170dd31f8b87089d4cc49f47c99d3f740bebfc426560` | vendor HTTPS-bootstrap／固定cac33616 key签名有效；25exact＋10已观察/lib64 parent alias，错误内层receipt引用历史保留。未重hash现存targets、无loader／manager／sourcehold／native／Full资格 |
| 已完成 | [当前Base安装闭包SDK6](native-modern-base-installed-sdk-probe.md)明确授权后 sdk01 一次六项 observed、child／wrapper／tool outer 均0，真实file与stdout逐字一致、16653条目及材料前后稳定；独立保存结果复核与10输入root receipt `cd3624dcfa90984031df7ed70d694c7e81cf1c3fc549df9977a2fcb3e5495684` | 本次grant闭合／无需重跑，旧fake5和native6分列；仅当前Base SDK组合，namespace后代退出、持续sourcehold、Full和产品未资格，work全部保留，AUTO OFF |
| 已完成 | 同版glibc Source RPM固定HEAD2定位与第二次显式GET完整字节身份，17,388,972B／22.856831s／inner0；6输入receipt `647c94e950ddc27ee16531c256071316577c7915237c5b9d70b72c80a403388e` | 初次403／0B／outer2保留，只加HEAD同UA重试；session33757工具未返回outerexit不合成0，body未验签，source／loader／native／Full资格未签 |
| 已完成 | 同版glibc SourceRPM私有DB验签／filelist实际3exit0、30,211B输出，228regular记录／220patch；18输入receipt `f78136fc7eb20733125b0a0e029c3890dd8b82bb1a72b6cfc50a1e211028a475` | 固定vendor HTTPS key标准；未展开payload／应用patch／执行build，loader／native／manager／Full未资格 |
| 已完成 | [零SDK Node bootstrap](durable-node-bootstrap-interface.md)三新文件STOP后稳定审查，18输入receipt `daa520bf4ac787369e9843e49cb9eb7e7b8876252c76bb19ebba2862eb9ea55b`；一次Node mock59pass／Python临时映射6pass，raw日志附录181e8a07 | 仅组件与默认测试；实际CLI／fd3／proc／flags／原OFD／EX锁／pipe／wait未验，不从fake或旧FD6补资格；新组合准备中，父controller／来源／初始化／DB另闭合 |
| 已完成 | [Node引导器单场实际验收](native-node-owner-bootstrap-probe.md)原失败bwrap flag保留、定向fake红绿后新work正控制：Node／outer0、hello／bound／closed、原pidfd观察与reap匹配；14输入root receipt `59d9e52877fb7db79f3e63dc4a46820f25e396190917e2dab2c1d53495694eee` | 本单场grant闭合；child flags仅自身检查，OFD／EX、namespace全后代、正式controller／SourceHold／真实锁释放未独立资格，旧29／59＋6不重跑 |
| 已完成 | [当前Base项目信任实际验收](native-modern-base-project-trust-probe.md)trust03一次2observed／exit0，实际三资源及正文deny0／allow1；16输入root receipt `40bdbb0bc86c6752d62c50d4dced589b2690e1d9ec929fac22125cadc63cd03c`，独立保存复核无P1／P2 | 本grant闭合；原01／02失败保留，公开发现后缀.js定向修复、不增加additional paths；只签reload，不签CLI首启／保存信任／sandbox／SourceHold／产品 |
| 已完成 | [当前Base安装RPC5实际验收](native-modern-base-installed-rpc-probe.md)rpc01一次5observed／各exit0，正文0／0／0／0／1，实际event／state／哨兵重核；12输入root receipt `3a5587f46dd9f7591266df53c65b1925a851c1816b90c5b0ea7df3491e1f7bb1` | 独立保存证据0P1／P2，本grant闭合；当前16653树与旧18498／52默认证据分列，不签真人／namespace全后代／SourceHold／实际模型／计费／产品 |
| 进行中 | [独立source SH／EX方向](durable-source-hold-locks.md)实际锁／mutator调用链已有限记录；先退役旧lifecycle／state EX的验收措辞P2已闭合；原instance候选锚经单段独立复核，4输入root receipt `93b09034f28d16291bcfae05bf12ed5a467a8e7e68ed06053f6677da8b51d0bd` | 未实现SourceHold／guardian／完整FullSourceView，首次创建／原对象／OFD／caller接线仍待冻结；不签锁、跨进程或产品资格；正式7/100保持 |
| 已完成 | 同版glibc被动payload及247输出独立读回，228signed成员／19upstream源码／220patch字面map；33输入receipt `350a2ca46cfe26c3b1e345cf32fab50c5d4f4cda3d8c3668519a3db1029a860d` | spec多一Lifsea条件Patch2001不在payload；8selected有literal patch target，未执行或应用patch／spec／build，不签loader／Full |
| 已完成 | 固定cache41193B匹配旧SHA，639rows纯数据解析、137ELF的366引用／36NEEDED各1已记录候选；9输入receipt `506b2e2798e40438a1f25a5e66db12936003fad01e49f4aad749e7cafdc8ca1a` | root19byte magic错误及撤回hash漂移归因历史保留；7invalid＋1valid合成仅parser，path不follow／targets不重hash，不签actual loader |
| 已完成 | precache静态137记录无RPATH／RUNPATH或slash NEEDED；原UID1002视图root-owned/etc下preload首末ENOENT | 默认namespace UID65534只记unsupported；原视图端点absence非hold，零内容／条目follow。19源码无sysdep hook定义，固定档案最多4header被动增量准备中；不签loader／Full |
| 已完成 | sysdep四候选被动增量原run失败outer2、2.321287s，generic前提推翻；唯一可选elf头1879B／15cecbe8的字节、stub和220补丁字面关系已有限核对 | root只接受保存header事实，保留原失败／未降required／未重跑；optional_missing尚未计算，其它可选候选unknown，不签实际Linux build选择／loader／Full |
| 环境不足未验证 | 有限ELF/libpython对应及发行/签名已分层接受；完整loader/stdlib/sourceRPM/build/actualmanager和controller/pipe/lease/native组合未验，来源/角色/授权IO未实现；Recovery3三场已有限原生验收，namespace物理停止仍unknown | 只阻塞依赖项；旧fbfea8/FD6授权已经闭合，不能覆盖新增组合，strict metering未验前AUTO OFF |

实际委派执行模型：实现及独立审查executor均gpt-6.1-sol/medium；静态来源/安装映射scout为gpt-6-luna/high。root保持主会话模型配置。模型说明是本轮执行记录，不是发布运行包的来源资格。

```text
Setup T001–T006 → Foundational T007–T016
                         ├→ US1 T017–T028 ─┐
                         ├→ US2 T029–T041 ─┴→ Base功能候选/临时报告（尚非passed）
                         └→ US7 T042–T048（维护机制先验，最终组合后复验）
US2的策略/许可/隔离 → US3 T049–T057
US2 + 共同Writer + Q4(T059) → US4 T058–T066 → US5 T067–T075
US2 + US4身份/观察/预算接口 + Q5(T078) → US6 T076–T092
US1/US2候选 + US7的Base维护/两态性能适用证据 → Base gate（独立判定）
US1–US7 + 冻结预算(T005/T054) → T093–T100（各gate及总验收）
```

| 执行包 | 必须先完成 | 等待时可继续 |
|---|---|---|
| 共同基础 | T001–T004、T006静态/API选择；T007/T008先测试，再T009–T013；T014先测试，再T015/T016 | T005的获准基线测量可独立；候选性能/质量结果在阈值冻结前禁采集 |
| US1实现 | 共同基础；T017/T018测试先于对应实现 | 原生MCP/认证的假服务检查可先做；T027/T028真实执行需US2就绪 |
| US2实现 | 共同基础；T029/T030先测试，T031/T032→T033–T036 | T037覆盖调查、T038场景准备不等待live；T040/T041集成需US1入口可用；T041仅临时报告，Base passed另等M01–M07的Base适用证据 |
| US7维护机制 | 共同基础；T042/T043先测试，T044/T045→T046 | 与US3及以后故事独立；T047基础保留策略先验，高级资源释放在T095复验 |
| US3 | US2策略/许可/受管执行；T049/T050先测试，T051–T053实现 | T054可先冻结样本；T055真实质量只需reviewer实现和预算，不依赖开关UI；T056/T057完成启用关闭与提示验证 |
| US4 | 共同Writer和US2；T058测试、T059 Q4→T060–T065→T066 | Q4探测可提前在隔离候选进行，不阻塞Base，不等待US3真实质量 |
| US5 | US4正式准入/执行/Writer/结果；T067/T068先测试，T069–T073实现→T074/T075 | 不依赖Durable；live未授权时完成错误成功/快照反例 |
| US6 | US2策略与US4身份/观察/预算接口；T076/T077测试及T078 Q5→T079–T090实现/故障→T091维护→T092真实入口 | Q5可提前独立探测，不阻塞Base；不依赖TK，查询实现不等待真实模型 |
| 最终交付 | 各故事实现与所需实证；T093需T005预算冻结；T094/T095闭合真实层，T096/T097文档/可选hook后固定版本，T098最终审查→T099 gate→T100 | 未授权/环境不足保留not-run/blocked并处理独立项；不因此删除必需目标 |

默认按编号选择已满足依赖的任务；US1真实集成等待US2时，先继续US2实现。Base最终gate还需M01–M07的Base适用子项，由T042–T048闭合维护、纯Pi/Base两态性能及手册证据后重算T041；不等待T093的Full四态完整对照。适用项未齐的早期功能增量不得冒充正式gate。Full实施仅依赖US2执行契约，不等待Base最终passed，以免形成循环。US7优先级P1指保护机制提前，其完整维护/性能/全组合验收由T093–T100闭合；不能在T048后宣称US7整体完成。T059/T078候选实验仅为可行性证据，正式锁定后各故事重新验收。

## 每个故事的并行示例

以下各行均最多一个代码写入者加一个只读scout；没有共享文件同时写入。`[P]`测试包可与不相交的测试包调换次序，当前默认仍由同一executor顺序写入。

| 故事 | 执行者任务 | 同时进行的只读工作 |
|---|---|---|
| US1 | T019原生日常工具 / T024原生MCP适配 | 核对资源发现、正式公开接口及Base污染，返回具体证据 |
| US2 | T032独立权限 / T033隔离 | 核对覆盖矩阵与OS正反用例，事务/权限决定交主代理 |
| US7 | T044替换状态 / T045卸载 | 审旧引用、数据归属及失败恢复，不在写入中签发最终审查 |
| US3 | T051–T053 reviewer | 核对冻结样本、请求计数与分型，不提前观察保留集结果调阈值 |
| US4 | T060–T065统一核心 | 核对Pi/Codex正式公开协议和实际模型证据 |
| US5 | T069–T073 TK | 找checker可篡改、证据过期与错误成功反例 |
| US6 | T080–T091服务 | 检查发送/持久化/owner/取消时序及SDK公开入口，不自改恢复语义 |

## 验收命令组

以下是实施阶段的确切入口：标“新增”的文件当前不存在，必须由对应任务创建后才可执行；禁止提前记录通过或临时改成真实宿主补齐。环境缺依赖记环境不足，安装仍遵守显式lock/sync。

| 组 | 默认离线命令（在仓库根） |
|---|---|
| V0 范围 | `./.venv/bin/python -m pytest -q tests/test_pi_validation_fixture.py` |
| V1 profile/提供者 | `./.venv/bin/python -m pytest -q tests/test_pi_dependencies.py tests/test_pi_capability_manifest.py tests/test_pi_optional_capabilities.py tests/test_pi_vendor.py tests/test_pi_validation_runtime.py tests/test_pi_provider_bindings.py`（最后一项新增） |
| V2 身份/执行 | `./.venv/bin/python -m pytest -q tests/test_pi_operations.py tests/test_pi_commands.py tests/test_pi_guarded_files.py tests/test_pi_workspace_leases.py tests/test_pi_registered_roots.py`（最后一项新增；合成进程不启动宿主） |
| V3 原生日常适配 | `./.venv/bin/python -m pytest -q tests/test_pi_login.py tests/test_pi_mcp_script.py tests/test_pi_mcp_stdio.py tests/test_pi_native_mcp.py tests/test_pi_session_profiles.py tests/test_pi_provider_routes.py tests/test_pi_main_auth.py`（后四项新增） |
| V4 权限 | `./.venv/bin/python -m pytest -q tests/test_pi_checks.py tests/test_pi_operations.py tests/test_pi_commands.py`；`node scripts/test-pi-mock.mjs agents/pi/runtime/tests/permissions.test.ts`（新增） |
| V5 替换维护 | `./.venv/bin/python -m pytest -q tests/test_pi_provider_replacement.py tests/test_pi_validation_runtime.py tests/test_pi_resource_retention.py`（第一、三项新增） |
| V6 审批 | `node scripts/test-pi-mock.mjs agents/pi/packages/risk-review/tests/protocol.test.ts agents/pi/packages/risk-review/tests/permit-races.test.ts`（新增） |
| V7 委派 | `./.venv/bin/python -m pytest -q tests/test_model_delegate_contract.py tests/test_model_delegate_backends.py tests/test_model_delegate_codex_worker.py tests/test_pi_delegate.py tests/test_pi_delegate_files.py`；`node scripts/test-pi-mock.mjs agents/pi/packages/model-delegate/tests/bridge.test.ts` |
| V8 TK | `./.venv/bin/python -m pytest -q tests/test_pi_checks.py tests/test_pi_input_snapshots.py`（后一项新增）；`node scripts/test-pi-mock.mjs agents/pi/packages/task-keeper/tests/two-profiles-contract.test.ts`（新增） |
| V9 Durable | `node scripts/test-pi-mock.mjs agents/pi/packages/durable-service/tests/protocol.test.ts agents/pi/packages/durable-service/tests/recovery.test.ts agents/pi/packages/durable-service/tests/maintenance.test.ts`（均新增） |
| V10 最终 | 先执行最终变更影响的V0–V9及 `specs/005-pi-two-profiles/quickstart.md` 已核对命令，再用现有 `scripts/verify-pi.py --report-only --scope <冻结scope> --evidence-root <本次证据目录> --output <新报告路径>` 汇总；占位必须替换，汇总不能制造缺失证据 |

独立真实OS入口在T034创建后为 `./.venv/bin/python -m pytest -q tests/test_pi_tool_sandbox_os.py`；独立进程/真实SQLite恢复入口在T090创建后为 `./.venv/bin/python -m pytest -q tests/test_pi_durable_processes.py`。两者用合成根/哨兵/假模型，默认套件应显式排除OS专属用例，运行须满足实际环境前提。Q3容器、真实Pi/Codex、账号模型、终端人工用例分别按授权执行并写确切命令；本文件不提供虚构产品命令。

## 实施策略与MVP

1. 完成Setup和共同基础，按Q1公开能力选择正式候选，先保护账号/会话/活动引用及Writer。
2. 完成US1+US2，复用US7的安装/失败恢复保护，形成可独立验证的Base功能MVP。正式Base gate须acceptance.md中Base适用的M01–M07等必需证据，包含纯Pi/Base两态性能与维护项；这些通过即可独立判定，不等待Full四态及专属组件验收。适用项未满足时只交付功能增量状态。
3. 继续US3与US4，随后US5与US6；可在真实账号/质量评测等待时推进不依赖它的实施。Full默认单主Agent，高级能力按需启用。
4. 对正式组合复验US7、性能和各真实层；停止写入后独立审查，严重发现修复后只复核受影响边界，计算最终gate并交付。

Base通过不会结束长期目标；所有适用必需项完成才总交付。可选Stop hook和其他平台保持如实inactive/not-run；Q3有证据的不支持只闭合调查，不能替代已选择支持能力或受管工具隔离验收。默认入口切换、发布、推送或合并沿用各自授权，不由任务勾选自动触发。

## 旧任务编号迁移

下表旧编号只表示2026-10-04 plan阶段的74项，不再作为当前执行入口；新编号中的合并/拆分保留目标。旧T012拆为各故事Q4/Q5，旧T046提前为共同Writer基础，旧US7的最终实证移至最终阶段。

| 旧编号 | 当前任务 |
|---|---|
| 旧T001 | T001 |
| 旧T002 | T002 |
| 旧T003 | T003 |
| 旧T004 | T004 |
| 旧T005 | T005 |
| 旧T006 | T006 |
| 旧T007 | T007 |
| 旧T008 | T009 |
| 旧T009 | T011 |
| 旧T010 | T012 |
| 旧T011 | T013 |
| 旧T012 | T059、T078 |
| 旧T013 | T017 |
| 旧T014 | T019 |
| 旧T015 | T020 |
| 旧T016 | T021 |
| 旧T017 | T023 |
| 旧T018 | T024 |
| 旧T019 | T025 |
| 旧T020 | T026 |
| 旧T021 | T027 |
| 旧T022 | T028 |
| 旧T023 | T029 |
| 旧T024 | T031 |
| 旧T025 | T033 |
| 旧T026 | T034 |
| 旧T027 | T035 |
| 旧T028 | T036 |
| 旧T029 | T037 |
| 旧T030 | T039 |
| 旧T031 | T040 |
| 旧T032 | T041 |
| 旧T033 | T049 |
| 旧T034 | T051 |
| 旧T035 | T052 |
| 旧T036 | T053 |
| 旧T037 | T054 |
| 旧T038 | T055 |
| 旧T039 | T056 |
| 旧T040 | T057 |
| 旧T041 | T060 |
| 旧T042 | T061 |
| 旧T043 | T062 |
| 旧T044 | T063 |
| 旧T045 | T064 |
| 旧T046 | T016 |
| 旧T047 | T065 |
| 旧T048 | T066 |
| 旧T049 | T069 |
| 旧T050 | T070 |
| 旧T051 | T071 |
| 旧T052 | T072 |
| 旧T053 | T073 |
| 旧T054 | T074 |
| 旧T055 | T075 |
| 旧T056 | T079 |
| 旧T057 | T083 |
| 旧T058 | T084 |
| 旧T059 | T087 |
| 旧T060 | T088 |
| 旧T061 | T090 |
| 旧T062 | T089 |
| 旧T063 | T091 |
| 旧T064 | T092 |
| 旧T065 | T046 |
| 旧T066 | T047 |
| 旧T067 | T093 |
| 旧T068 | T048 |
| 旧T069 | T094 |
| 旧T070 | T095 |
| 旧T071 | T098 |
| 旧T072 | T097 |
| 旧T073 | T099 |
| 旧T074 | T100 |

本轮仅生成任务与同步引用；产品验收事实仍为not-run，任务未勾选。

2026-10-09 Durable controller fd3 前置原语：仅新增仓库自有 reserve_controller_slot/check/close，原主线程且3明确EBADF才预留/dev/null；已观察为foreign/未知3零close，close先永久退役再核原held身份并一次关闭。executor默认64后独立发现登记后捕获中断遗漏，root新反例RED1/64deselect及同模块GREEN65 exit0，稳定影响路径再次独立通过。receipt fccfe79648e8ee69b844018657de18ba1e66701638c83bd0363e7cfeb28a8d91。全部syscall/thread为假，不启动controller/SDK/Node，不提供SourceHold/principal/FullSourceView或原OFD真实资格；整体任务保持未完成，正式8/100、AUTO OFF。

2026-10-09 Durable 初始化双pipe创建前置：两次原pipe2立即登记，低号原端以F_DUPFD_CLOEXEC转>=4，FIFO/方向/flags核验及逐端退休close-only；不覆盖foreign3。默认101后独立2P2已修：登记后中断先退役record、失败cleanup不先分配新端点batch且异常固定转换。反例RED3failed/104pass，稳定同模块GREEN107 exit0，影响路径独立复核无剩余P1/P2，receipt 9386b5cf0b0ed856ce65771ccc79c0c15305e5385900041eb97856d14c75aa56。全假syscall/thread、无读写/launch/handoff/role/grant/SourceHold或原生资格。正式8/100、AUTO OFF；整体任务未完成。

2026-10-09 Durable initializer 私有bootstrap纯数据codec：Python/Node同12字段/canonical4BE frame，完整golden746B/最大payload757B/cap2048；token只显式frame输出、默认展示/错误脱敏。Python默认180pass、固定Node24原bwrap/mock guards50pass，两语言有效RED/GREEN exit记录分开；首次Node namespace环境失败无测试不计RED。稳定独立复核无P1/P2，receipt 3ed51fad518389e460d1a0fcacdbb218958e1e520e9f46f67f7a4dc914950096。DTO/frame/WeakMap不是角色/IO权限，不交付carrier、initializer或SDK资格；实际新角色/native仍未执行。正式8/100、AUTO OFF。

2026-10-09 受管运行包读取边界：receipt16MiB/pkgJSON1MiB、65536 entries、256MiB/file、2GiB total、128目录层/4096 UTF8 path/graph visits固定限额；预算在collect/sort或file open/hash前，原9签名/status catchtuple/ownership/activation保持。初始默认27pass与旧最小13pass分轮；独立P2增长超读已用真实3B文件append32B反例RED35>4修复为剩余+1哨兵，当前同模块28pass exit0，旧13仅引用其原identity，生产后续唯readcount一行。稳定影响路径独立复核无剩余P1/P2，receipt 9f4b6577d4dd88a28fbbaba88d4590088624953e5060a0dd65cc4449a844a562。默认自有真实owner/tmp与fake installer，不实际host/SDK，不提供wall-clock/原子快照/SourceHold/Full来源资格，正式8/100、AUTO OFF。

2026-10-09 当前部署Full来源点时数据producer：仅actual Workspace/PiAdapter，从自身受管current.launch双ID推导final root，原marker/SourceSH、bounded部署/receipt及完整owner/capture校验、末核原generation/physical/bytes，未知消费current/launch字段拒绝。38个真实/tmp+SourceSH+原pipeline合成Full夹具有效RED/GREEN，accepted原context正控、detached candidate消费层负控（非合法candidate installed声明）；稳定独立无P1/P2，receipt f45c4b56ad7991e0008e91ed691691fc133f3404e9241eaa1dc1e981f9083fc0。没有实际Full/加载/FullSourceView/SourceHold/principal/issuer资格，返回前已释放观察锁，私密generation/rawbody及hash不输出，正式8/100、AUTO OFF。

2026-10-09 独立持续SourceSH reader资源：共用唯一latch acquisition，捕获原Tree/source/methods/thread与marker/context；不保留life/stateEX。真实/tmp默认正控证明两轮前台life/stateEX释放后普通准入可进，而source mutatorEX仍零写拒绝；初始82=44新+37旧latch+1lifecycle，保持旧动态after-body与cleanup优先级。独立P2无界强引用已改成功close删除、未知退休保留并计64资源上限，起始预留在IO前、finally释放/覆盖重入；有效RED6fail45pass、当前52pass=51新+1旧（原82仅旧identity引用）。稳定affected review无剩余P1/P2，receipt 7b107840c7be3acb00487b2adb44bc30558f4a72c29b1520b1a863ab2fd413bb。无跨线程/进程handoff、独立holder、FullSourceView/SourceHold/actor权限资格；产品gate未提升，正式8/100、AUTO OFF。

2026-10-09 Base 优先收敛：补入 docs/pi-two-profiles.md 的升级/配置/模型/权限/替换/使用边界说明，并用现有 v2 验收计算器对 revision1 原scope重算 docs/acceptance/pi-two-profiles/current-gates.json 与 final-gates.md。八gate全false、108必需子项not-run，产品身份和checker尚未冻结；2个not_selected不计为通过。该报告不以旧pytest或候选探针签发产品证据，不完成T048/T096/T099；正式8/100、AUTO OFF。pi-jev只读参考已记research D17，不加入默认依赖或重开权限架构。

2026-10-10 T025 Base 资源离线子项：保留原dirty C++ SKILL前缀并增加本仓库原创数据库契约相对参考；真实Base resolver/render验证完整技能包、许可、exec位和普通prompts隔离。初次5passed属于旧测试identity；独立发现plugin排除断言盲点，Root改为精确Base三插件集合后仅受影响1passed，轮次分列不合称6passed。稳定独立无剩余P1/P2，rootreceipt a3fa56ef8b7bb64103cc0ad88147a87307af2c08ea68231b714ae3f9a1d5ae96。manifest只相对本包dirty起点更新target SHA，原source/history/adaptation保留。现代Full选择及T028/T095实际加载待验，T025整体保持未勾、正式8/100/AUTO OFF。

2026-10-10 T015整体验收完成：逐条核CLI register/inspect/list、passwd公共锚、跨profile/别名/替换/未知root、通用file/command/checkpoint与所选共用模块Git假设；Git专属明确拒绝、readseek未选排除，权限文档齐全。既有当前production源码匹配的两模块72passed保留；新增实际CLI inspect只读断言单独1passed（实际owner新私有tmp、原guards），首默认路径ownership setup失败未进入行为，不计RED。来源/测试身份及轮次不合并。独立条款审计无代码缺口，rootreceipt ee4a58c22b0061a3725fb38d46efb6237938e9f1382a07b7ae02f802ee7db453。历史12场nonGit OS对应旧source不提升为当前；T016迁移/终止恢复和Base/Full产品仍未完成。正式任务更新9/100、AUTO OFF。

2026-10-10 Base Host Shell生产接线默认完成：modern显式shell选择才构造桥，File/Shell使用同一原账本；原namespace/helper收据+16MiB真实文件字节+完整planner与末核，固定错误清原链，原resolve/spawn/消费/unknown顺序保持。有效RED10failed/3passed，首次实现22passed/2个新test误认原接口失败，修断言后最终同受影响24passed，轮次不相加。稳定独立无P1/P2，rootreceipt aa50d7018e269e3e2dc854ddff698d53ae040d1ddd0de6b6063fa5afc7743bc9。helper为合成未执行ELF、原planner为小受控系统树，未称正式运行包/实际SDK/产品隔离通过；T013/T020/T033整体仍未勾、正式9/100/AUTO OFF。实际Base插件ID/能力ID与Todo模型工具白名单错配另包修复中。

2026-10-10 Base plugin→capability→模型工具默认组合完成：真实render保留用户pluginIDs，现代显式封闭plugin_capabilities对应安装capIDs；仅selected runtime extension的公开tools中正确归属、唯一且callable的声明工具入SDK allowlist。Todo现在进入主会话工具集合；原RegisteredTool/definition/execute重绑、丢失/碰撞拒绝旧准入，声明进入ConfigIdentity（active子集相同仍变）。Python33passed/Node131passed分别真实exit0，稳定独立无P1/P2，rootreceipt 04d6d2147aa2def71771475c7b369288eb830991cf888ecc47c3657f880c84c2。未执行SDK/宿主、改vendor/正式锁/verified；当前candidate仍需真实产品组合资格，不完成T009/T010/T019/T026整个任务，正式9/100/AUTO OFF。

2026-10-11 T022现代国内路线承接实现交叉验收完成：正式配置投影→原公开ModelRuntime默认initializer/selected model scope，现代manifest排除旧openai-proxy，全局fetch/dispatcher包装退出；仅显式direct支持，未实现proxy严格拒绝，密钥路线独立且不跨账号fallback。已有T021默认/ABI及原正常CLI print04/05真实合成HTTP发送收据覆盖生产入口，本轮只读核对不重复测试、不迁移旧runtime资格。Root receipt `e0b88e6b9320b32be3f083d4fcc7c7b0077b00d4403f40f7055cb4340bd17b95`。真实国内端点、真人账号、无海外代理实际路线及最新组合仍为未验证验收目标，B项/产品gate不提升；正式24/100。

2026-10-11 T013共享操作契约完整实现验收：当前共用OperationAdmissions/可信Host上下文及file/shell/MCP桥绑定最终私有参数、policy/context/root/backend/可执行身份；随机private_input_ref无正文/正文散列外泄，重复请求异参冲突，permit一次消费在实际分配之前且失败不恢复。现代Node official-file-admission复用同一prepared，不制造拟议permission-access重复层。T019/T029/T030既有分层证据保留，本轮零重跑；正在变化的Host先等待FD稳定审查，再由Root确认原principal/peer/lease/generation与共享账本组合不变。Root receipt `ba3bb904dd8b786bee223b08faaa9cb7b77ea8bd151fbb88a70575d33d9a0f36`；整体OS/Full/所有入口资格仍另验。正式25/100，产品gate保持false。

2026-10-11 T012 基础运行包实现完整交叉验收：原staging/seal/receipt完整inventory、双私有状态与nativehome、三方部署/恢复、漂移/链接/所有权/活动实例拒绝已实现。已有88默认、17guard、19现代静态校验分层收据和正常currentBase安装四CLI0分别保留；历史cold不重标当前，Full高级包/最新组合/账号/体验分别归后续故事。Root receipt 274d8e3f57708600bfd9a81114106074ab8f94faf5073698f6aec1a9b0678908，本轮不重复测试；正式26/100，八gate仍false。
