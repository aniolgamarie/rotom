# Phase 0 Research: OMP 权限管控

> 本文保留宿主补丁方案的历史模型/契约。自2026-09-30起按不修改上游源码原则迁移，当前要求以[独立插件修订](standalone-plugin.md)为准；不得继续依赖宿主bridge或私有接口。

日期：2026-09-29。输入：[spec.md](spec.md)。以下是设计决定与源码证据，不是功能验收结果。

## 研究边界与来源

- 研究基线为仓库锁定的 OMP `v18.3.0`，commit `62bc57be1b03ef0802a33cf7f5f530e534527531`；源码归档 SHA256 为 `edcc0f93a0ab0c0223d0651bba3624c55a32d25494a43b0257ea626be1dff97d`，与现有锁一致。
- 上游链接固定到该 commit；不以在线最新接口或尚未合并的 PR 作为实现能力。
- rotom 集成依据 [omp.py](../../src/agentcfg/omp.py)、[omp_dependencies.py](../../src/agentcfg/omp_dependencies.py)、[plugins.toml](../../agents/omp/plugins.toml)、[依赖文档](../../docs/omp-dependencies.md)。当前工作树已有其它修改；计划以读取到的工作树为基线，不覆盖这些改动。
- 两项独立 scout 研究分别核对宿主审批路径及 rotom 交付边界；主代理负责模型预算、tiny 加载、风险策略和最终取舍。

## R1 — 接入方式：本地扩展 + 有版本的宿主桥接接口

**Decision**：扩展名为 `omp-permission-control`，用 TypeScript 编写；通过新增的 `permission-control/v1` 宿主接口注册审查器，不覆盖同名 Bash 工具。宿主补丁放在 `agents/omp/patches/permission-control/`，与扩展一起锁定。最终参数完成所有修改后，宿主取得原生策略来源，按优先级审查，在真正执行前消费一次性许可。

**Rationale**：现有 `tool_call` 只能 block 或改 input；`tool_approval_*` 是观察事件；approval 本身是同步声明。普通 hook 中做完模型审批，wrapper 仍会弹原生 prompt。同名 Bash 覆盖虽能通过 `ctx.invokeTool` 调原工具，却会跳过其原生审批；公开 context 又没有有效 Settings/native approval resolver，无法可靠保留命令规则和运行中变更。

**Alternatives considered**：纯观察 hook 无法消除重复审批；同名工具 `approval:allow` 和全局 YOLO 会削弱原生保护；复制当前配方规则到扩展会产生两个策略来源；等待上游合并不具有确定交付时间。选择局部、可审计的宿主接口，代价是需要维护补丁运行包。

**Evidence**：[wrapper](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/extensibility/extensions/wrapper.ts)、[扩展类型](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/extensibility/extensions/types.ts)、[runner](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/extensibility/extensions/runner.ts)。

## R2 — 原生审批来源与最终决定

**Decision**：宿主保留已有原生解析器和用户规则顺序，新增结构化来源：`explicit-deny`、`command-prompt`、`critical-safety`、`native-allow`、`tool-default`、`tier-default`、`compound-structural`。前三类不可交给模型放宽；无法识别的来源按必须人工处理。后面三类默认询问可委派，前提是扩展能完整分析命令。原生 allow 仍须符合已知低风险条件，不能把宽泛 allow、YOLO 或连接符本身当成安全证明。

复合命令对每个完整解析出的简单命令使用同一原生匹配函数，再合并全部副作用；保留单个命令内原生规则的首个匹配语义，跨命令以 deny > mandatory-human > 其它决定合并。原生已拒绝的整条请求始终拒绝。解析不足不能消除原生要求。

固定策略只允许两条自动放行路径：确定性已知低风险；或主审返回 low、授权充分、无未知效果且通过全部硬边界。medium/high/unknown 一律 ask，模型 deny 则 deny。模型返回 allow 只是建议，不能覆盖宿主边界。manual 跳过全部模型，保留已知安全许可，其余人工。显式配置的命令 prompt 包括例行写操作，仍须用户处理。

**Rationale**：工具级默认 prompt 是用户要减少的重复询问；命令级 prompt 是用户希望保留的明确边界。仅用最终 `prompt` 布尔值无法区别两者。风险低与用户授权充分是两个条件，模型不能通过高 confidence 自行放宽。

**Alternatives considered**：所有 prompt 都保留无法达成体验目标；所有 prompt 都可模型覆盖则破坏 FR-005；直接调用原生 judge role 会引入未选择的候选模型链。

**Evidence**：[BashTool.approval](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/tools/bash.ts)、[原生审批](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/tools/approval.ts)。

## R3 — Bash 分析范围与执行一致性

**Decision**：首版实现不执行命令的保守词法/语法分析器，只接受可完整消费输入的字面量简单命令及 `&&`、`||`、`;`、管道组成的列表，识别引号、转义、注释和重定向。对变量/命令/进程替换、glob、here-document、后台作业、函数、控制结构、脚本内容及未知语法标为 unknown，转人工。重定向和管道目标参与合并效果；可识别语法不等于可自动批准。

确定性允许表按命令、子命令、完整选项和操作数约束编写，不按首词或正则前缀概括允许。首批涵盖受限的 `pwd`、`ls`、`head`、`wc`、`rg`、`git status/diff/log` 只读形态；pager、外部 diff、textconv、exec 选项、设备、秘密路径、未知可执行文件、仓库脚本均不能因命令名而放行。不会调用 `bash -c`、`eval` 或外部程序来“解析”输入。现有 interceptor 改写/阻止仍在冻结参数前完成；插件不改写命令或自行换工具重试。

每个会话串行处理受管 Bash 的审查到发起执行过程；待执行许可绑定最终参数、cwd、shell/可执行文件身份、必要目标状态、授权版本、策略和模型版本、会话 generation。执行前重新读取并核对与判定有关的文件身份/内容摘要、Git 状态等；无法枚举或核对目标依赖的操作不走自动允许。执行前消费许可，中间不得再 await 或修改参数；状态变化后回到新请求，不复用旧结果。

**Rationale**：完整 Bash 解释器不是首版目标；保守子集可以处理大量常见复合读操作，而不把未知语法交给语言模型猜测。文件系统最终核对和进程启动之间仍存在操作系统层面的外部竞争窗口；本插件不宣称消除该窗口或提供 OS 沙箱。对无法给出稳定判定上下文的操作要求人工，与 spec 的单次许可一致。

**Alternatives considered**：按连接符拆字符串会错解引号和替换；只问模型无法保证解析覆盖；新引入完整 Shell 解释器会增加依赖、执行语义和跨平台负担。首版选择零新增解析依赖的拒绝未知子集，并用固定复杂语法样本检验边界。

**补充核对与决定**：`BashTool.execute` 内还会提取 cd、改写 worktree/internal URL，并可能创建目录、启动 service/job；`executeBash` 又会加载 direnv、添加 shell prefix 和改变环境/后端。因此仅在 wrapper 冻结 raw args 不够。宿主补丁同时提取无副作用的 `prepareBashExecution` 与单次 `commitPreparedBashExecution`，bridge 绑定准备好的最终执行计划；不允许批准后重新跑输入变换。首版智能覆盖进一步限定为可证明闭合的前台 native backend：service/async/pty/ACP、direnv/devenv、非空 prefix、未知 shell startup、内部 URL 及未核实 worktree 改写转原生人工/无 UI 阻止。不会为了进入 smart 静默关闭用户已启用的环境行为。

这不是再造完整 Bash backend；只提取覆盖路径的准备/消费边界，其它路径保留原生人工。纯准备阶段不得执行 direnv、mkdir、daemon、job 或命令来探测环境。已知 cwd 变换可静态完成并进入计划；无法静态闭合则不能自动批准。

**Evidence**：[BashTool.execute](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/tools/bash.ts)、[bash-executor](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/exec/bash-executor.ts)、[内部 URL](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/tools/bash-skill-urls.ts)。

## R4 — 主审选择、输入与预算

**Decision**：配置引用 rotom 已选择的 model ID，渲染为确切 OMP provider/model；缺省在审查开始时冻结会话主模型。独立请求不携带工具，不使用 `runEphemeralTurn`、会话 retry/fallback 链或 `resolveJudge` 的自动候选池。复用 ModelRegistry 认证解析，但凭据留在宿主调用边界，审查器/审计不接收秘密。

主审输入包含完整脱敏操作、结构化效果、原生约束和有来源标记的必要用户消息；文件/工具/助手内容仅是非可信数据，不能产生授权。只选相关用户消息；若撤销、限制或必要操作上下文不能在预算内完整表示，则 ask。不以模型生成的会话摘要独立证明授权。

预算固定为：总自动等待 30 秒；主审最多 25 秒，tiny 仅用余量且最多 5 秒；每次操作最多 1 次主审、1 次合条件 tiny。主审序列化输入最多 24 KiB UTF-8、输出最多 512 tokens 且 4 KiB；tiny 输入最多 8 KiB、输出最多 128 tokens 且 1 KiB。任何额度不足不得截断动作后允许。输出严格 JSON schema，额外字段、缺项、无效枚举、截断或工具调用都算无效。

提供一次性 provider transport：禁止推理请求重试、模型切换、工具执行、响应内容日志。优先实现当前 kernel 所需 `anthropic-messages` 与 `openai-completions` 的认证兼容单次调用，复用 pi-ai 但关闭 SDK 重试并用 fetch 单发门禁验证；其它 transport 只有证明同样有界才启用，否则展示不支持并转人工，绝不静默换模型。认证刷新与推理请求分开计数；不因 auth retry 重发审查推理。用户取消在 1 秒内撤销执行资格，忽略之后到达的任何响应。

**Rationale**：省钱需要明确实际模型和请求次数。底层 provider 有各自重试机制，仅在扩展中调用一次函数不能证明只请求一次。按 API transport 验证比限制厂商名称更适合复用自定义 provider。

**Alternatives considered**：会话 turn 会带入全量上下文和工具；原生 judge chain 可自动换候选；仅依赖模型自称“授权充分”缺少来源约束；无限递归重试不符合成本与取消契约。

**Evidence**：[judge chain](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/judgment/index.ts)、[pi-ai StreamOptions](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/ai/src/types.ts)。

## R5 — tiny 只作有界故障辅助，且必须禁止资源获取

**Decision**：配置独立的 `fallback_model = "local/lfm2.5-230m"`；未配置则不启用，不跟随标题 tiny role。仅主审超时、服务故障、无效输出后使用；主审 ask/deny、硬规则、取消、无模型配置错误或不支持的 transport 均不调用 tiny。tiny 有效输出只允许 ask/deny，任何 allow 都视为无效并维持 ask。

宿主增加 installed-only tiny 调用：加载前核对完整本地模型和运行依赖，worker 侧禁用远程获取与安装；使用独立的 local-only worker 标识，不能接管普通标题 worker 的宽松加载路径。缺失、损坏或不能证明本地闭合即返回 unavailable。首版 Linux ONNX 路径；不为了 tiny 引入 MLX 平台承诺。复用已安装模型文件，不复制凭据，不下载资源。

**Rationale**：当前 `tinyModelClient.complete/chat` 可作通用推理，但 cold load 会走 `loadTransformersRuntime` 和模型 pipeline。只检查缓存目录存在或先调用标题接口，都不足以满足“不隐式下载”。模型很小也不构成可靠权限决定来源。

**Alternatives considered**：只使用已运行 worker 会不必要地限制已安装资源；让 tiny 作为普通第二审会越权；无条件调用现有 client 无法保证离线边界。

**Evidence**：[tiny client](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/tiny/title-client.ts)、[worker](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/tiny/worker.ts)、[runtime loader](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/subprocess/worker-runtime.ts)。

## R6 — 交付：显式构建、锁定、消费，保留官方运行包路径

**Decision**：本地插件沿用 packages/tree_digest/entrypoints；补丁 standalone 使用额外的受管 runtime variant `permission-control-v1`，独立锁位于 `locks/omp/permission-control/manifest.json`。仅选择该插件的 profile 要求此 variant，其它 profile 继续官方 standalone。维护者在显式构建步骤产生资产与构建 receipt，再由 `lock` 收录；`sync` 只校验和消费现有资产，不隐式安装 Bun/Rust 或执行上游安装脚本。`apply` 部署配置，`run` 只使用已部署引用。

新增封闭 `agent_options.permission_control`（default_mode、可选 reviewer_model/fallback_model）与显式 runtime_variant；生成原生 `config.yml` 的受管 `/permissionControl`。不开放 arbitrary runtime JSON。保留 Bash 原生 prompt，并为 kernel 的 task/eval 设原生 prompt；eval 只扩充现有封闭工具名白名单，不提供 eval 智能审查。详细字段见 [配置契约](contracts/configuration.md)。

构建 receipt 必含上游 commit/归档、完整 bun.lock、补丁有序摘要、构建脚本摘要、精确工具链版本与资产摘要、native 依赖来源、目标平台、输出二进制摘要及 bridge ABI。不能用上游官方二进制摘要证明补丁产物。首版只登记实际构建并验证的平台资产；缺少平台产物返回依赖错误，不使用官方包冒充 smart。相同输入的位级可复现性需要重复构建证据，当前仅承诺锁定输入和消费已验证字节，不预先声称二进制可复现。

**Rationale**：当前运行包固定官方资产，没有能给官方编译 binary 注入审批钩子的现成配置。补丁必须进入实际宿主；只把 patch 放进 Git 或编写 fake bridge 无法完成本特性。

**Alternatives considered**：运行时 monkey patch 编译 binary 不可靠；所有 profile 全部换自编译版本扩大影响；sync 动态编译扩大副作用和工具链需求。选择预先显式构建的本地资产，以既有 staging/receipt/租约/恢复模型消费。

## R7 — 状态、审计与证据

**Decision**：模式只驻留会话内存，新建/恢复时读配方默认。审计写当前原生会话的扩展记录，但不读回为许可；只存请求随机 ID、带会话盐的动作摘要、策略/模型身份、来源、结果、短原因码、耗时/调用数和健康变化。正文命令、对话、自由文本模型解释及异常原文不持久化。UI 原因由代码模板生成；需要人工时本地 UI 可展示待执行完整动作，仍遮蔽秘密。

主审输入、异常、日志、status、审计均做秘密哨兵验证；脱敏改变语义或不确定则不发送且 ask。证据分为隔离状态机验证、真实模型质量、真实宿主集成及各平台。样本预先冻结至少 100 safe + 100 ask/deny + 40 fault/state，两类命令各至少 30 compound；不以 fake 模型结果宣称模型准确率。

**Rationale**：可解释性不需要保留可泄密的原始命令；状态与许可不同，恢复审计不应恢复授权。模型输出是非可信数据，不能直接进入日志或 UI。

**Alternatives considered**：缓存全量对话/命令便于调试但违反最小化；跨请求 approval cache 会引入上下文漂移；按执行后结果改标签不能作为质量证据。

## 研究结论

接入、策略来源、解析范围、模型来源、tiny 离线性、运行包交付和证据边界均已形成具体决定，没有留给实现阶段的架构二选一。实现阶段仍需实际构建、补丁契约测试及平台/模型验证；这些是验证工作，不能作为本轮已通过的证据。若锁定宿主无法兑现 bridge 时序或 installed-only 边界，应返回主代理决策，不得降级为 YOLO、复制宽松规则或静默减少 FR。
