# Phase 0 Research: Pi 能力统一

**Date**: 2026-09-16  
**Inputs**: [spec.md](spec.md)、[初始调查](source-inventory.md)、[宪章](../../.specify/memory/constitution.md)

本文件记录设计决定，所有新桥接、后端及补丁均是待实现内容，不代表现用 Pi 已具备这些能力。
研究仅阅读仓库、已安装包源码和上游资料；没有运行宿主、安装器或真实模型测试。

## R1. 采用现有公共管理架构，补齐真实 Pi 边界

**Decision**: 增加 PiAdapter、PiBackend、声明式原生投影保护及受管活动监督接口；
沿用现有配置合并、SecretStore、Artifact、Tree、三方部署和上一版备份。
agentcfg 管配置与运行资源，Task Keeper 管任务策略，新 AgentManager 管子执行生命周期。

**Rationale**: 公共命令已通过 adapter/backend 分发，但 DSH 的 dependencies.py、lock schema、
包收据与必要入口检查仍有宿主专属假设；CLI 及注册表也只声明 dsh。
活动 flock 能保护宿主，不能据此推断所有 Node 子孙进程都持有同一描述符。

**Alternatives considered**:

- 直接复用 DSH 锁策略：会错误处理 Pi 的包、Superpowers 和原生入口，拒绝。
- 把旧 Lua 同步器搬进 Python 命令：形成第二套合并、认证与恢复规则，拒绝。
- 新建独立 Pi 管理器：重复已有所有权与部署功能，拒绝。

**Evidence**: [backends.py](../../src/agentcfg/backends.py)、[dependencies.py](../../src/agentcfg/dependencies.py)、
[workspace.py](../../src/agentcfg/workspace.py)、[runtime.py](../../src/agentcfg/runtime.py)、
[profile schema](../../schemas/profile.schema.json)。

## R2. 固定版本与补丁身份

**Decision**: 首个实现基线为 Pi **0.84.4**、`@tintinweb/pi-subagents` **0.19.0**，
新管理者以上游提交 `e955e29c51b7a6cce37e1108cd2d6c57a77e151c` 为来源，
生成带独立补丁版本 `0.19.0-agentcfg.1` 的可重建 vendor 包。
Task Keeper 从 starter 提交 `c60599df39e6350123f7fb9378cfe63dc5ed814f` 迁入，
移除旧 0.63.0 适配依赖并以 `0.2.0-agentcfg.1` 记录新契约。
构建基线采用 Node **24.14.0**、npm **11.19.1**，初版 Pi 运行也要求精确组合；
不改变 DSH 已允许的工具链范围。其余包的来源基线见最终能力清单。

**Rationale**: 已知 Pi 0.84.4 的 Node 下限为 22.19.0，新管理者 peer 要求 Pi 0.84.0 以上，
选择固定现用家族减少同时升级宿主的变量。精确工具链比未经验证的兼容范围更容易识别证据。

**Alternatives considered**:

- 沿用旧管理者或新旧并载：违背统一目标，拒绝。
- 跟随 latest 或未合并 PR：没有固定验证对象，拒绝。
- 只改 Task Keeper 版本门槛：不补接口与执行保障，拒绝。

**Evidence**: 上游固定版本 [Pi package.json](https://raw.githubusercontent.com/earendil-works/pi/v0.84.4/packages/coding-agent/package.json)、
[新管理者 package.json](https://raw.githubusercontent.com/tintinweb/pi-subagents/e955e29c51b7a6cce37e1108cd2d6c57a77e151c/package.json)。
以上支持依赖身份和版本约束，不证明所选组合已通过运行验收。

## R3. 单一管理者加受管进程执行接口

**Decision**: 对新管理者增加 `agentcfg-managed-executor-v1` 窄接口：
handshake、preflight、dispatch、inspect、get_result、cancel、reconcile、consume。
普通会话与受管任务使用同一个 AgentManager；受管请求选择 process executor，
普通轻量只读请求可使用现有 session executor。Task Keeper 不另建子代理管理者。
受管 reader/writer/reviewer 每次是 fresh 工作进程，继承显式模型、工具与策略描述，
禁止隐式父上下文、动态扩展、嵌套与通用工作流。管理者的独立 scheduling/workflows 均关闭。

**Rationale**: 当前 0.19.0 的执行器在父进程内创建 SDK 会话，abort 及状态变化不等于
底层操作结束；现有公开调用不能承载所有预算、权限和终止约束。
补丁把执行设施注入现有管理者，保留唯一的队列和任务身份。

**Alternatives considered**:

- 包装现有 Agent 工具调用：无法证明控制所有请求与子执行，拒绝。
- 第二套隐藏 Task Keeper 调度器直接启动工作进程：重复管理与生命周期，拒绝。
- 永久只交付 scout/reviewer：不满足必需 Task Keeper 用途，拒绝。

**Evidence**: 上游固定提交 [agent-runner.ts](https://raw.githubusercontent.com/tintinweb/pi-subagents/e955e29c51b7a6cce37e1108cd2d6c57a77e151c/src/agent-runner.ts)；
starter 的 `pi/packages/task-keeper/src/adapters/subagents.ts` 与 `scripts/prepare-subagents.mjs`。

## R4. 请求准入、权限和结果证据不能仅依赖事件通知

**Decision**: Task Keeper 是受管任务唯一恢复与预算权威。发送每个模型请求之前，
受管 transport 必须原子检查持久额度并记录 reservation；重试、压缩、结构化结果重试和辅助请求
均复用同一 task budget，禁止未登记的额外请求。费用未知使用 null，不记为零。
工具访问使用受控工具实现与规范化路径根，有效权限为用户策略、父侧适用拒绝、角色上限和任务授权的交集。
运行结果先写入独立持久 evidence，再通知完成；直到 Task Keeper 确认消费前不能 GC 本次证据。

**Rationale**: 使用量事件发生在请求之后；UI 权限和系统提示词不是请求或文件访问的硬边界。
停止、空 completed、旧 receipt 或过期摘要不能推导当前任务通过。

**Alternatives considered**:

- 仅使用 before-provider 事件或完成后计数：有重试/辅助调用绕行，拒绝。
- 将所有父插件复制进工作进程：引入隐式工具和请求，拒绝。
- 用 result text 声称 Codex/检查已运行：缺少本次身份与候选关联，拒绝。

## R5. 实例活动保护和两种平台的执行监督

**Decision**: 增加实例 supervisor 与持久 ExecutionLease，记录 starting 后才能 spawn；
锁由 supervisor 保持，所有工作进程、项目检查和所选外部委托都必须登记。
其崩溃或观察丢失留下 unknown，部署必须先 reconcile，不得因锁描述符消失而视为空闲。
原supervisor已失效时，用户可通过R13定义的显式stop recovery回收已证明归属的旧执行。
显式 task stop 只能撤销和终止身份核实属于本任务的进程；部署不得杀进程抢锁。

Linux 使用进程启动身份、独立进程组及 bubblewrap 受限 verifier；macOS 使用独立进程组，
由随项目构建的只读进程身份 helper 获取 libproc 的 PID/PPID/PGID/启动时间，
配合 nonce 控制通道、退出回执和未结外部工作记录。
macOS verifier 使用固定 sandbox-exec 配置，默认无网络、候选目录可写，
显式所需工具目录只读；能力预检确认系统支持，否则阻止受管写入而不宣称该组合已支持。
两个平台都不支持脱离监督的 daemon 命令；受管角色无任意 shell、MCP 或 spawn 工具。
任务验证命令只能为显式绑定且前台执行的可信 argv。

**Rationale**: 进程组不足以证明任意后台程序已退出；需要限制允许启动的操作并保留不确定状态。
同用户任意恶意代码与任意 daemon 不在隔离承诺内，不将路径检查描述成 OS 安全沙箱。

**Alternatives considered**:

- 仅检查父 PID 或超时清理：存在 PID 复用及子进程残留，拒绝。
- 仅支持 Linux 后声称所有机器完整：拒绝。macOS 是同等契约的实现与认证目标。
- macOS 伪造 /proc 数据：拒绝；采用本地进程身份接口和独立验证记录。

**Validation gate**: Linux x86_64/arm64 与 macOS arm64/x86_64 为目标矩阵；
每格只有达到配置、安装、原生与受管任务相应级别后才发布该级支持。
当前计划不声称任何新组合认证已通过；没有认证不得将缩减能力计算为完整交付。

## R6. 严格配置与凭据投影

**Decision**: 保留公共 `roles` 为角色到模型 ID 映射。Pi 角色、提示、主题和扩展资源目录
声明在 `agents/pi/agent.toml` 的 closed resources 表，选择与工具选项放在 agent_options；
`content.toml` 只保存公共 registry 已支持的技能和规则。
`pi-default` 可作为无私有模型的普通初始化配方，未绑定主模型标为 unconfigured；
`pi-managed` 被选中且必需角色及检查未绑定时 validate 返回 2。
全部 profile 仍检查结构、未知字段和已提供引用；必需机器绑定就绪只校验当前选择，
避免未选中的 Pi 配方阻塞 DSH。
不将任意公共模型、代理端口或私有服务编造为可调用默认。

原生 JSON 使用叶子字段所有权。`models.json` 不做整文件或整个 provider 快照；
每个受管 apiKey 叶子仅允许精确的生成 `$AGENTCFG_PI_CREDENTIAL_<ID>` 引用，
plan/apply/rollback/capture 必须在读取投影、差异或备份之前验证当前值。
candidate/current/previous/pending 分别使用其版本记录的合法 token allowlist，
支持合法引用轮换和回滚；不以新配置 allowlist 错误拒绝旧受管引用。
秘密字面量、!command、组合模板或与预期不同的引用引发冲突；未知认证字段不接管。

**Rationale**: 普通 FILE 投影会编码完整文件；仅以敏感键过滤对象不能保护独立字符串叶子。
Pi 0.84.4 的配置解析将 `$ENV` 解释为变量，裸变量名仍是字面值。

**Alternatives considered**:

- 复制整个 models/auth：泄露与所有权风险，拒绝。
- 为 Pi 放宽公共未知字段校验：拒绝，使用独立适配器 schema。
- 原样继承全局技能扫描：不同机器不可复现，默认关闭并显式选择来源。

**Evidence**: [deployment.py](../../src/agentcfg/deployment.py)、[local schema](../../schemas/local.schema.json)；
已安装 0.84.4 的 `dist/core/resolve-config-value.js`、`provider-composer.js`。

## R7. 完整依赖与原生发现

**Decision**: PiBackend 使用独立 pi-lock schema，锁定每个配方切片各自完整的 npm 树、不可变 git 源、
本地源码及 vendor 补丁。非 registry 源先形成确定性归档；来源、许可、文件执行位与构建输入入锁。
sync 执行 frozen 安装并默认禁用生命周期脚本，必要步骤采用固定 argv 与输入哈希 allowlist，
验证后激活。每个 profile_slice 固定独立 package.json/package-lock.json 文件对，
sync 不剪裁或重写锁；根索引包含所有切片摘要。已部署启动保存组合 runtime_identity，
由锁、切片、平台和工具链构成，回滚后不从当前 profile 重新猜测运行包。
run 使用显式已安装入口与资源清单，自定义 loader 禁止远程包解析和隐式安装。
角色、提示、技能和扩展的最终发现清单在启动时记录，不能只验证复制数量。

**Rationale**: 上游 Pi 包管理器可能在资源解析阶段解析 package 来源；
新机器不能依靠现有 node_modules、相对 starter 路径或包外技能资源。

**Alternatives considered**:

- runtime settings 中保留 npm:/git: 并交由原生自动处理：违反显式依赖流程，拒绝。
- 每台机器运行 npm install 或旧 prepare-subagents：不可复现，拒绝。
- 不审查构建依赖就全部 ignore-scripts：可能交付不可运行原生依赖，拒绝，改用逐步骤授权清单。

## R8. 控制责任和可选能力

**Decision**: 固定 ordinary/managed 两种主要配方，Codex、外部网络与专业技能采用显式选择。
受管工作进程只加载桥接、受控工具及证据回报；其他 UI/权限/网络插件留在父会话并按冲突规则启用。
Task Keeper 独占恢复/预算/一次性调度，管理者独占子执行并发/生命周期，
受管权限编译器独占工作进程授权，loop-guard 只负责普通会话循环。
旧 7 个 Codex 协调角色合并到 model-delegate 统一入口，保留用途模板与新旧映射，
不让协调角色再调用一轮 Pi 模型来决定是否执行 Codex。

**Rationale**: session-yolo 当前只设置状态标记，不能假定它已控制权限插件；
handoff 会直接生成摘要，需避免绕过预算；可视 diff 插件不应在受管候选活动时启动任意外部编辑器。

**Alternatives considered**:

- 全部照搬并默认开启：有重复控制与隐藏请求，拒绝。
- 删除全部 Codex 能力：丢失指定真实执行者与凭证用途，拒绝。
- 用新角色名称兼容旧调用形态：没有实际连通性证明，拒绝。

最终逐项决定、版本与控制矩阵在 Phase 1 能力契约中记录；其实现必须验证所选可选能力，
不能因为“可选”而保留失效入口。

## R9. 迁移与诊断

**Decision**: 仅新增 `plan --from-pi-home PATH [--from-starter PATH]` 只读迁移预览输入，
不新增隐式 apply-import。输出私人 inventory/proposal 与脱敏摘要；用户采纳非秘密来源后
通过现有 apply 建新实例。旧 home、同步标记、账号与任务历史保留。
doctor 分开报告 configured/deployed/dependencies/load/auth/execution/evidence，
离线结果只引用匹配的历史证据，不执行宿主；live 仅可达性，不调用模型。

**Rationale**: 新实例最容易明确所有权；旧源与用户当前覆盖不能按文件存在直接采纳为可信配置。

**Alternatives considered**: 原地接管全局 home、自动迁移账号或复制旧缓存均拒绝。

## R10. 检查与交付证据

**Decision**: 默认 pytest 与 Node 测试只运行模型/宿主替身；旧 Task Keeper 测试入口拆分，
原生 PTY/RPC 和网络能力测试从默认套件移到独立显式脚本。
完整回归覆盖 DSH；cold rebuild 在每个声明平台至少两个不同 HOME/仓库路径执行。
格式校验、mock、原生发现、任务执行与真实账号分别记载，不能互相替代。

**Rationale**: 旧 Task Keeper 的完整套件包含真实 Pi 子进程，不能原样加入仓库默认测试。

**Alternatives considered**: 用历史通过数、无账号 smoke 或仅生成 CI 文件替代本次证据，均拒绝。

## R11. Cursor 与 Codex 可选运行环境

**Decision**: `pi-cursor` 配方使用相同 Pi 0.84.4 和新管理者来源，但以 **Bun 1.4.0** 启动，
选择 `@rahularya01/pi-cursor@1.4.29`；不选择 Task Keeper，并拒绝将该包加入 Node managed 配方。
依赖获取仍由 PiBackend 的固定 Node/npm 安装工具链完成；Bun 是该配方公开机器前提，
不运行 curl 安装脚本或原生包自动安装。其普通子代理、权限与 Cursor 登录必须单独验收。
这保留当前 Cursor 的独有账号用途，不宣称 Cursor 已通过受管请求门控。

可选 `pi-codex` 配方采用 Node 普通配方及 **Codex CLI 0.154.0** 外部发行物身份，
在 lock 时记录每个平台发布物摘要，sync 显式准备该可选运行包；
运行使用实例内 CODEX_HOME 与统一 supervisor，所有只读委托及用户显式 write/resume/control
迁入 model-delegate，不再发布旧 codex-delegate 技能或执行器。
不把外部 Codex 接入 Task Keeper 的自动第二视角，避免无法逐请求计量的模型执行进入硬预算承诺。

**Rationale**: 当前 Cursor 包 engines 与 README 明确 Bun-only；切换 Node 不能假定兼容。
旧 Codex runner 使用 setsid、/proc 和固定代理，需要迁移到平台 supervisor 及机器网络配置，
但指定真实执行者与本次凭证的价值必须保留。

**Alternatives considered**: 全部强改到 Node 扩大认证范围；静默删除 Cursor 丢失现用能力；
外部 Codex 作为 Task Keeper 不透明 helper 破坏预算，均拒绝。

**Evidence**: 已安装 Cursor 包清单与 README；上游
[Bun 1.4.0 发行页](https://github.com/oven-sh/bun/releases/tag/bun-v1.4.0)、
[Codex 0.154.0 发行页](https://github.com/openai/codex/releases/tag/rust-v0.154.0)。
它们证明目标发行身份存在，不证明 Pi/插件组合已通过认证。
macOS 进程身份字段依据 Apple [proc_info.h](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/bsd/sys/proc_info.h)；
helper 的最终系统 SDK 与编译身份在构建收据记录。

## R12. model-delegate 完整替换旧专用执行器（用户确认修订）

**Decision**: 迁移后只交付 `shared/skills/model-delegate` 和
`agents/pi/packages/model-delegate` 工具桥。model-delegate 的 Pi/Codex backend 使用同一版本化请求、
进度和结果协议；七个 Codex 角色转为用途模板，不保留旧角色注册或 codex_delegate 工具别名。
补齐 Codex 显式隔离写入、detach/readiness/unknown、cursor poll/wait、结构化上下文与反馈校验。
迁移期间可保留源环境供比较，但最终运行依赖不包含旧技能、run-codex.sh 或任何隐藏回退。

**Rationale**: 先前调查沿当前Pi插件依赖保留旧执行器，遗漏了starter的
`.model-delegate-migration-analysis.md` 替换路线。补查源码确认model-delegate已经有Pi/Codex backend、
start/status/cancel/resume和前台observe；Codex仍supports_write=false，尚无detach/poll/wait完整入口。
这些是需要在迁移中补齐的差距，不构成长期保留两套执行器的理由。
原路线图是历史设计输入，不能把其中所有“优化”建议直接视为已验证正确或当前实现事实。

**Alternatives considered**:

- 长期保留独立codex-delegate：违背用户确认的退出目标，拒绝。
- 只改名字或让model-delegate内部继续调用run-codex.sh：仍依赖旧执行器，拒绝。
- 不补齐写入与长任务控制就切换：丢失保留用途，拒绝。
- model-delegate加入另一层自动调度/重试：与既有AgentManager/Task Keeper冲突，拒绝。

**Integration**: Pi的model_delegate工具通过唯一AgentManager申请external executor，
一次dispatch只执行一个backend run；运行进程与工作区统一由supervisor登记。
独立用户CLI只执行显式单run，批量入口改为提交上层批次/收集结果，不自行创建另一执行队列。
Task Keeper继续使用可逐请求计量的managed executor；未经认证的外部委托不得被用作隐藏helper，
其接口要明确拒绝该上下文。模型委托是执行层，不替换Task Keeper的任务调度责任。

**Evidence**: starter的 `skill/model-delegate/scripts/run-model.sh`、`scripts/backends/codex.sh`、
`schemas/receipt-v1.json`，及旧迁移分析。完整新契约见
[model-delegation.md](contracts/model-delegation.md)。本轮只核对源码，未运行任何真实委托。

## R13. 分析发现修订：恢复、写入仲裁、权限与交付范围

**Decision**: 保留只读reconcile，另加绑定计划/身份/300秒有效期的用户显式recover_stop。
旧监督者必须已失效，新授权仅撤销和停止，不转移执行权或凭旧nonce重新派发；完整终止前保持租约。

工作区写入采用worktree专属Git管理目录inode仲裁与私有持久标记，跨profile/HOME共享，
不把实例锁当成业务工作区锁。未知持有者阻止新写，额外根按统一键排序预留。

策略固定Permission Policy v1：closed file/command规则，exact/subtree，默认deny、deny优先，
父规则不能转换则拒绝，project路径拒绝在候选根重绑定后仍有效。

验收固定scope，区分必需、已选可选和未选项；报告可在零证据时生成，交付批准另行检查。
未选可选账号项不阻塞，已选但无授权/证据仍阻塞，不能缩减平台或移除必需替换能力获得通过。

**Rationale**: 只读reconcile不能停止失去控制者的活跃任务；实例私有锁不能仲裁相同worktree；
没有固定语法的“规范化权限”可能被不同实现解释成不同能力；依赖全部验收完成后才汇总无法报告缺口。

**Alternatives considered**: 恢复旧nonce/自动接管、每profile各自判断writer、忽略无法转换父规则、
把not-selected或报告退出0当成执行通过，全部拒绝。

**Evidence**: 本轮对spec/plan/tasks及相关契约的只读分析U1/U2/U3/I1；精确字段和验收样例见
[恢复与工作区](contracts/recovery-and-workspaces.md)、[权限规则](contracts/permission-policy.md)、
[证据汇总与交付](contracts/evidence-and-release.md)。未新增运行通过声明。

## R14. 自动复核后的执行模式与分配事务

**Decision**: ordinary绑定真实业务worktree和OperationGrant，managed绑定候选与task grant；
两种delegate模式按显式只读/独立写根执行。原checkout只读限制不扩散到普通父会话实施。

ExecutionLease先以allocating完整持久化计划，再写跨实例reserved，全部成功后提交starting才能spawn。
abort_allocation只能凭不可变日志与未提交启动边界证明释放本次预留；starting后缺PID不能当未启动。
RecoveryGrant幂等复用首次证据/目标generation，避免授权自身撤销变化导致重复恢复被拒绝。

**Rationale**: 修订权限语法时需要保留ordinary实际能力；多目录租约需要覆盖尚无进程的崩溃窗口，
“保护未知”不能代替对可证明未启动情况的可恢复设计。

**Alternatives considered**: 全部会话强制候选、先写共享预留后才登记意图、按PID缺失直接清锁、
重试恢复时重复增代，均拒绝。

契约、数据模型、T007/T036/T038—T040/T049/T054/T072/T084与V09/V13已同步。
这些是设计修订，不声称已执行实际进程/平台验证。

## R15. Codex 工具路径重新评估（2026-09-17）

**Recommendation**：普通 Codex 委托采用官方 CLI 原生工具与运行级监督；不把 agentcfg MCP IO 替代层作为默认交付条件。
冻结 starter 的两个 runner 都使用 CLI；新增 MCP 主要来自统一权限契约对逐工具撤权的扩大要求，
其当前固定命令引用也改变了原生使用方式。完整依据、边界差异、现有代码冲突及修订清单见
[codex-execution-reassessment.md](codex-execution-reassessment.md)。

**Status**：用户要求继续后按原生运行级授权实施；spec、权限/委托契约与数据模型已同步两种执行边界。
MCP IO替代层退出默认路线，Task Keeper的工具门控和预算承诺保留。原生验证仍未完成。

## R16. 原生机器根限制与配置检查的证据边界

机器目录根限制通过冻结身份和Git common-dir对应关系投影到候选；限制同时保留原路径，readonly只减少现有write，不授予新read。
具体子路径allow不重开父限制；目录身份别名参与匹配。原生配置字典是生成结果，仍需平台沙箱native验证。

固定版本源码中的exec为LoaderOverrides设置ignore_user_config/ignore_rules；AppServerCommand未暴露相同的exec选项。
虽然config/read的includeLayers能返回配置层，额外app-server探针与实际exec并非已证明等价的加载过程，也不是同一时点快照。
因此未添加“探针通过即exec配置已封闭”的快捷认证。系统/企业配置及额外资源来源仍属T074未完成范围。
依据：已下载rust-v0.154.0的cli/src/main.rs、exec/src/lib.rs及ConfigReadParams/ConfigReadResponse协议源码；未执行宿主。

## Research completion

截至R14，配置归属、版本基线、管理者数量、请求门控位置、平台监督、完整锁与验收分层已有设计选择。
R15按用户要求重新评估Codex执行边界，已给出CLI原生工具的推荐方案；涉及的权限与证据契约已按继续实施指令同步，
不再将此前MCP选择视为最终结论。其余补丁、依赖锁、平台认证仍是必须完成的工程工作。
任何实现证据失败都保持release gate关闭；执行边界变化需明确记录，不能以静默降级制造通过。
