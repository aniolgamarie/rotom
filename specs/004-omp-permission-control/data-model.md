# Data Model: OMP 权限管控

> 本文保留宿主补丁方案的历史模型/契约。自2026-09-30起按不修改上游源码原则迁移，当前要求以[独立插件修订](standalone-plugin.md)为准；不得继续依赖宿主bridge或私有接口。

日期：2026-09-29。输入：[spec.md](spec.md) 与 [research.md](research.md)。这里描述逻辑实体、关系和状态，不把内存对象或审计格式误当作跨版本持久化 API。

## 总体关系

```text
ManagedPermissionConfig ──生成──> NativePermissionControl
          │                         │
          ├──约束──> PluginDeliveryIdentity
          │                         │
          └──设定──> SessionPermissionState ──准备──> PreparedBashExecution ──冻结──> ReviewRequest
                                      │                    │
                                      │                    ├──至多一次──> ReviewerInvocation
                                      │                    └──故障时至多一次──> TinyInvocation
                                      │
                                      ├──产生──> PermissionDecision ──ask──> HumanDecision
                                      │                    │                  │
                                      │                    └──自动 allow─────┴──> ExecutionPermit
                                      └──追加──> RedactedAuditRecord
```

本插件为审查新增的 Bash 文本副本和最小用户授权上下文只在当前判定的易失内存中存在；本契约不要求删除或改变 OMP 原有的原生工具调用历史。插件审计只保留加盐摘要、枚举和消息 ID，不保留命令正文、消息正文、模型自由文本或异常原文。

## 1. `ManagedPermissionConfig`

rotom profile 中由用户或仓库维护者填写的意图。

| 字段 | 类型 | 约束 |
|---|---|---|
| `runtime_variant` | 字面量 | 启用本功能时必须为 `permission-control-v1` |
| `default_mode` | `smart \| manual` | 必填；`omp-kernel` 为 `smart` |
| `reviewer_model` | 可选 rotom model ID | 若存在，必须同时出现在该 profile 的 `models` 选择中 |
| `remote_fallback_model` | 可选rotom model ID | 与reviewer一样须已选择且唯一可解析，运行时故障才参与 |
| `fallback_model` | 可选字面量 | 唯一允许值为 `local/lfm2.5-230m`；省略表示禁用 |
| `plugin_selected` | 布尔派生值 | 必须选择 `omp-permission-control` |

该对象封闭，未知字段失败。它不能包含 provider 凭据、原生任意 runtime 片段、策略覆盖、超时覆盖、提示词或额外 allow 规则。完整配置见 [configuration.md](contracts/configuration.md)。

## 2. `NativePermissionControl`

写入原生 `config.yml` 的 `/permissionControl` 受管对象。它由适配器生成，不接受原生配置透传。

| 字段 | 类型 | 含义 |
|---|---|---|
| `schemaVersion` | `1` | 原生对象版本 |
| `defaultMode` | `smart \| manual` | 每次新建或恢复会话的期望模式 |
| `reviewer` | `session` 或 `{provider, model}` | 缺省动态绑定审查开始时的会话主模型；显式值是已解析原生模型 |
| `remoteFallback` | 可选 `{provider, model}` | 完整同等级远程审查fallback；省略保留旧行为 |
| `fallback` | 可选 `{provider, model, installedOnly}` | 省略即禁用；首版只允许本地 tiny 且 `installedOnly=true` |
| `bridgeAbi` | `permission-control/v1` | 插件与补丁宿主的 ABI |
| `pluginId` | `omp-permission-control` | 插件身份 |
| `pluginDigest` | SHA-256 | 已锁定插件树身份 |
| `runtimeIdentity` | 非空身份字符串 | 已锁定 patched runtime 资产身份 |
| `policyVersion` | SHA-256 | 影响判定的固定策略与配置的生成摘要 |

`pluginDigest`、`runtimeIdentity` 和 `policyVersion` 只能由锁及规范化输入生成。任一身份变化都会使未执行许可失效。

## 3. `PluginDeliveryIdentity`

把仓库来源、锁、profile 选择和实际加载状态连成一个可核对身份。

| 字段 | 类型 | 说明 |
|---|---|---|
| `plugin_id` | 字面量 | `omp-permission-control` |
| `plugin_tree_digest` | SHA-256 | 插件源码及受管入口点摘要 |
| `manifest_path` | 字面量 | `locks/omp/permission-control/manifest.json` |
| `runtime_variant` | 字面量 | `permission-control-v1` |
| `runtime_identity` | 字符串 | patched OMP v18.3.0 构建资产身份 |
| `bridge_abi` | 字面量 | `permission-control/v1` |
| `load_state` | 枚举 | `verified \| missing \| damaged \| identity-mismatch \| not-loaded \| unhealthy` |

只有三方一致时才可进入 smart：profile 选择插件、profile 选择该 runtime variant、原生对象声明相同插件/ABI/身份。其它状态保留原生保护并把需要智能审查的操作转人工；无 UI 时阻止。官方 standalone manifest 保留不变，本实体引用独立 patched manifest。

## 4. `SessionPermissionState`

每个主 OMP 会话独有的易失状态。

| 字段 | 类型 | 说明 |
|---|---|---|
| `session_id` | 宿主会话 ID | 不与其它会话共享许可 |
| `generation` | 单调整数 | 保护基线变化时递增 |
| `configured_mode` | `smart \| manual` | 来自 profile 的期望值 |
| `active_mode` | `smart \| manual` | 当前会话切换后的值 |
| `mode_source` | `profile-default \| session-command` | 状态解释来源 |
| `reviewer_selection` | 模型选择 | `session-default` 或显式模型 |
| `remote_fallback` / `remote_fallback_state` | 可选选择/状态 | 配置模型与被动健康，和配置主审/最终实际模型分开 |
| `fallback_state` | 枚举 | `disabled \| ready \| unavailable \| unhealthy` |
| `bridge_health` | 枚举 | `healthy \| degraded \| unavailable` |
| `coverage` | 结构化状态 | 首版候选范围及当前实际覆盖：Linux 主会话 Bash、前台 native backend，并列出使请求转人工的限制原因 |
| `last_decision_id` | 可选请求 ID | 供 `explain` 查找；不构成许可 |
| `pending_permit_id` | 可选许可 ID | 串行受管 Bash 路径最多一个 |

新建和恢复会话都从 `configured_mode` 初始化，不从审计恢复临时模式或许可。切换模式、主模型或显式审查模型变化、策略或插件/runtime 身份变化、bridge 健康降级，以及宿主审批/YOLO 基线变化均递增 `generation` 并撤销待执行许可。child、eval、MCP、子代理和非 Bash 入口不能继承 smart 许可。

## 5. `PreparedBashExecution`

宿主 `prepareBashExecution` 在无副作用阶段生成的不可变最终执行计划；详细字段和 prepare/commit 时序以 [host-bridge.md 的最终执行计划](contracts/host-bridge.md#最终执行计划与首版覆盖条件) 为准，本模型只定义权限绑定关系。

| 字段 | 类型 | 说明 |
|---|---|---|
| `prepared_execution_id` | 宿主不可伪造内存身份 | 与 request/session/generation 一一绑定 |
| `final_command` | 易失字节串 | interceptor、确定性 cwd/参数变换后的实际待执行 command；模型只接收其允许发送的完整脱敏视图 |
| `transformation_summary` | 固定结构 | raw request 到最终 command 的变换种类与必要效果，不含秘密或自由文本 |
| `execution_binding` | 摘要与本地引用 | 绑定最终 args、cwd、shell、backend、环境摘要、目标指纹、延迟效果及 prepare 算法版本 |
| `coverage_state` | `eligible \| manual-required` | 只有完全可准备的前台 native backend 可为 eligible |
| `coverage_reasons` | 固定枚举数组 | direnv/devenv、prefix、service/async/PTY、ACP terminal、未知启动脚本等实际不覆盖原因 |

纯 prepare 不创建目录、不加载环境脚本、不启动进程、daemon 或 job，也不执行探测 shell。配置中的 direnv、prefix、service 等行为保持原样；首版不能冻结其完整最终计划时标记 `manual-required`，由原生 UI 审批且计入免询问指标，不能为了进入覆盖而静默关闭配置。commit 只能消费同一个已核验计划，不能重新计算会改变 command/cwd/env 的步骤。

默认 kernel 兼容扩展增加宿主私有 `StagedExecutionResources`，绑定同一 prepared 身份、request、session、generation 与批准链，只能在本次 allow/人工批准后创建。它包含原生 artifact/job 的未启动资源句柄、固定延迟效果种类与 `staged|started|discarded` 状态，不进入模型输入或持久授权。stage 不启动 Shell；最后核验失败/取消只允许 discarded，start 只能在同一同步消费区发生一次。自动后台阈值与相关配置摘要属于冻结计划，不能在等待期间改变后沿用许可。

`VerifiedShellState` 同样仅由宿主持有，关联实际 Shell 实例/生命周期、生成环境输入、snapshot 文件摘要、已核实的名称解析/options 与后续执行状态连续性。snapshot 存在、文件权限或一个布尔值本身不构成此证明；未跟踪执行、别名/函数/配置变更、未知 mutation 或缺失来源立即失效。冷初始化的人工批准不能自动授予后续命令权限，后续每条仍走独立审批。

## 6. `ReviewRequest`

单个最终 Bash 调用在执行边界冻结的请求。受管 Bash 在进入队列后，从构造审查上下文到发起执行按会话串行；排队时间不计入自动 deadline。

| 字段 | 类型 | 说明 |
|---|---|---|
| `request_id` | 随机 ID | 会话内唯一，用于关联 |
| `session_id` / `generation` | 身份 | 绑定当前会话保护基线 |
| `operation` | 易失 UTF-8 字符串 | `PreparedBashExecution.final_command` 的完整脱敏视图，不是 raw args；不入审计 |
| `operation_digest` | 会话盐 SHA-256 | 审计关联身份，不能跨会话追踪正文 |
| `argv_digest` | SHA-256 | 绑定工具名和最终参数 |
| `prepared_execution_id` / `execution_binding` | 宿主引用与摘要 | 绑定唯一 prepared plan；最终核验和 commit 必须使用同一计划 |
| `transformation_summary` | 固定结构 | 随最终 command 交给主审的必要变换摘要；不能只发送 raw args |
| `execution_context` | 结构化对象 | 来自 prepared plan 的 cwd、shell/backend 身份、必要目标状态摘要；排除环境秘密 |
| `effects` | 解析效果数组 | 每项有本请求内唯一 `effectId`、固定种类、目标类别和影响等级，以及宿主生成的授权绑定 `scopeDigest` |
| `native_constraints` | 结构化数组 | 原生来源和每个简单命令的结果 |
| `authorization_evidence` | 宿主认证证据数组 | 仅当前有效上下文中与动作相关、且宿主证明来自真实用户输入通道的消息 ID、易失正文及宿主从正文计算的 `utf8ByteLength`；不信任外部长度，ID 与完整引用均不等同于授权范围 |
| `mode` / `policy_version` | 固定值 | 审查期间不可变化 |
| `reviewer` / `reviewer_source` | 固定模型 | 审查开始时解析；不随标题切换 |
| `fallback` | 可选固定模型 | 与标题 tiny role 无关 |
| `deadline` | 单调时钟时间点 | 从开始构造审查上下文起算 30 秒，覆盖预处理、资源检查及模型等待；排队和人工等待除外 |
| `cancel_state` | `active \| cancelled` | 取消后至迟 1 秒失去执行资格 |

输入序列化上限为 24 KiB；主审输出上限为 512 tokens 且 4 KiB。无法在额度内保留完整操作、全部效果、原生约束和必要授权语义时，不截断后放行，结果为 `ask`；无 UI 时阻止。秘密脱敏改变判定语义时同样处理。

消息的 `role="user"` 本身不是来源证明。由模型、工具、文件、导入记录或宿主内部流程合成的 user-role 消息，以及引用工具输出的伪授权，均不能进入 `authorization_evidence`；来源元数据缺失或不可核验时结果最多为 ask，无 UI 时阻止。

### 逐效果授权证据

主审 JSON 的 `evidence.bindings` 按 [授权契约](contracts/review-decision.md#授权判断的职责与证据) 为每个 effect 提供 `effectId`、`userMessageId`、`startByte`、`endByte`、`scopeDigest`。scopeDigest 由宿主按实际 effect 对象/参数/cwd/上下文计算并随输入提供。allow 的引用区间必须覆盖本次完整脱敏用户消息，即从 0 到该消息的宿主权威 `utf8ByteLength`；ask/deny 的有效非空引用可为部分区间。宿主验证来源、精确覆盖、引文字节与当前绑定；主审判断语义，完整引用也不声称宿主能独立证明自然语言蕴含。完整引文及 evidence 只驻判定内存，不新增审计正文。用户限制状态 clear/conflicting/unknown 绑定当前 generation；只有完整上下文无待解释自由文本且结构化限制机械核验通过时初始 clear，已知冲突为 conflicting，其余含未解释自由文本或上下文缺失时 unknown；它不能走确定性直通，smart 本次主审可判断，manual 人工。本次模型判断不缓存为其它请求授权。

指代解析属于主审的自然语言语义判断。多个候选对象存在时，拟执行 operation/effect 不是消歧证据；只有真实用户消息本身唯一确定对象，或明确委托主审在候选集合中作出选择，才可能建议 allow。仅列出候选，或允许检查一个未指定候选，不构成选择委托。其余情况标记 `ambiguous-authorization` 并 ask。该提示政策仍需真实模型评测，不能视为宿主的机械语义证明。

## 7. `ReviewerInvocation` 与 `TinyInvocation`

`ReviewerInvocation` 每个请求最多一个，25 秒上限且受总 deadline 约束。它固定 provider/model、transport、输入摘要、开始/结束单调时间、结果种类和请求计数。推理请求不重试、不切换模型、不带工具；认证刷新不能重发推理。

`TinyInvocation` 只可在主审 `timeout`、`service-failure` 或 `invalid-output` 后创建，每个请求最多一个。它只用总 deadline 剩余时间，最长 5 秒；输入最多 8 KiB，输出最多 128 tokens 且 1 KiB。模型必须是已配置且本地完整安装的 `local/lfm2.5-230m`，加载路径不得下载、安装或升级。主审已经 `ask`/`deny`、硬规则、取消、配置错误或 transport 不支持时不创建 tiny 调用。

## 8. `PermissionDecision`

| 字段 | 类型 | 说明 |
|---|---|---|
| `decision_id` | 随机 ID | 会话内唯一 |
| `request_id` | 外键 | 指向唯一请求 |
| `outcome` | `allow \| ask \| deny` | 最终策略结果，不是模型原样结论 |
| `source` | 枚举 | `hard-rule \| low-risk-rule \| reviewer \| fallback \| manual-boundary \| native-protection \| system-failure` |
| `reason_code` | 固定枚举 | UI 使用代码模板解释 |
| `model_result` | 可选结构化结果 | 严格 JSON 验证后的主审建议 |
| `actual_model` / `model_source` | 可选 | 未调用模型时必须为 `not-called` |
| `fallback_result` | 可选 ask/deny | 永远不能产生 allow |
| `health_result` | 固定枚举 | 本次 bridge、主审、tiny 健康摘要 |
| `created_at_monotonic` | 单调时间 | 不用于跨进程授权 |

优先级固定为：明确 deny → 必须人工/宿主强制检查 → 覆盖、健康与信息完整性门禁 → 确定性低风险 → manual 人工边界 → 主审建议与固定策略合成 → 合条件 tiny 收紧 → 人工或阻止。只有插件/runtime/ABI 与保护基线健康、请求属于 Linux 主会话 Bash、操作与上下文完整且原生来源已识别时，插件才可产生确定性 allow；unsupported 或不健康状态不能借低风险短路扩大宿主范围。模型只有在 `risk=low`、`authorization=sufficient`、无未知项、效果覆盖完整且所有消息 ID 有效时，才可能由固定策略产出 allow；模型自身不能创建授权或覆盖原生边界。详见 [review-decision.md](contracts/review-decision.md)。

## 9. `HumanDecision`

原始 `PermissionDecision.outcome=ask` 在可靠本地 UI 中触发一次独立人工决定；无 UI 不创建本实体并直接阻止。

| 字段 | 类型 | 说明 |
|---|---|---|
| `human_decision_id` | 随机 ID | 会话内唯一 |
| `ask_decision_id` / `request_id` | 外键 | 必须关联仍有效的原 ask 与同一请求 |
| `outcome` | `allow \| deny` | 只接受真实用户 UI 操作；模型、工具和文件不能模拟 |
| `source` | 字面量 `human` | 保留 reviewer/fallback/native 的上游 ask 来源链 |
| `generation` / `binding_digest` | 固定身份 | 人工响应到达时必须仍与请求一致 |

人工 deny 终止请求且不进入 tiny 或模型复审。人工 allow 不是把原 ask 改写成 reviewer allow，而是在审计中保留 `ask → human allow` 链，并只为同一有效绑定创建一次许可。等待人工不计入 30 秒自动 deadline；等待期间的取消、模式/策略/模型/健康/目标状态变化使人工响应失效。

## 10. `ExecutionPermit`

仅自动 `PermissionDecision.outcome=allow`，或与仍有效原 ask 关联的 `HumanDecision.outcome=allow` 时，在内存创建一次性能力。

| 字段 | 类型 | 说明 |
|---|---|---|
| `permit_id` | 随机 ID | 不可由模型指定 |
| `request_id` / `decision_id` | 外键 | 只能关联同一请求链 |
| `grant_source` | `automatic \| human` | human 时同时保存 `ask_decision_id` 与 `human_decision_id` |
| `binding_digest` | SHA-256 | 覆盖 prepared execution 身份与 binding、最终 command/参数、cwd、shell/backend、目标状态、授权、模式、策略、模型选择、插件/runtime 身份和 session generation |
| `state` | `pending \| consumed \| invalidated` | 仅允许一次 `pending → consumed` |
| `invalid_reason` | 可选固定枚举 | 记录取消或哪类绑定变化 |

执行前重新核对绑定；核对失败转 `invalidated` 并从新请求重新判定。许可在启动前原子消费，消费与发起执行之间不得 await 或改写参数。取消、编辑/重排、目标状态变化、会话/模型/策略/模式/身份/健康变化和宿主保护基线变化都会失效。迟到模型响应不能把许可恢复为 pending。插件不通过其它入口自动重试拒绝或待人工操作。

## 11. `RedactedAuditRecord`

按会话隔离追加的最小记录；它只用于解释和证据，不作为许可恢复来源。

必含：schema version、request/decision ID、加盐 operation digest、最终 outcome/source/reason code、active mode、policy version、实际 reviewer 身份与来源或 `not-called`、fallback 配置与是否调用、覆盖标签、bridge/model/tiny 健康、调用次数、耗时桶和 permit 最终状态。发生人工决定时还必须记录 human decision ID、`source=human`、allow/deny 及其上游 ask decision ID，但不记录 UI 文本。可含验证过的授权消息 ID，但不含消息正文。

禁止写入：原始或可逆命令、完整 argv、cwd 中的秘密片段、环境值、凭据、完整对话、模型自由文本、provider 响应正文、异常原文和未脱敏工具/文件输出。审计写入失败不得使本来需要询问或拒绝的动作放行；状态将健康标为 degraded。

## 生命周期与失效矩阵

| 事件 | 会话状态 | 在途请求 | 待执行许可 |
|---|---|---|---|
| 新建或恢复主会话 | 从 profile 默认初始化，新 generation | 无 | 无 |
| `manual` / `smart` | 通过独立控制路径先原子递增 generation 并发出 abort，再更新模式；不等待 Bash 串行锁 | 立即失去执行资格并忽略迟到响应 | 全部失效 |
| 主模型、显式 reviewer、策略或插件/runtime 身份变化 | 重新解析并递增 generation | 取消或完成为不可执行 | 全部失效 |
| bridge/插件健康降级或 YOLO/原生审批基线变化 | 状态降级，保留原生保护 | 不得产生智能 allow | 全部失效 |
| 用户取消 | 模式不变；out-of-band 发出 abort | 1 秒内标记 cancelled，不等待 Bash 串行锁 | 失效，迟到响应无效 |
| ask 且有 UI | 等待独立的 `HumanDecision`；不计自动 30 秒 | 自动阶段结束 | human allow 后只为同一绑定创建一次许可；human deny 终止 |
| ask 且无 UI/child | 保持原生保护 | 结束为阻止 | 不创建 |
| allow 执行 | 状态不变 | 结束 | 启动前消费，不能复用 |
| deny | 状态不变 | 结束 | 不创建；不得改入口自动重试 |

## 不变量

1. 有效许可产生前不得发生被审查操作的执行副作用。
2. 一个请求最多一次主审；仅规定故障后最多一次 tiny；tiny 永远不能产生 allow。
3. hard deny、command prompt、critical safety 与未知原生来源不能被模型、YOLO 或无 UI 环境放宽。
4. 只有用户消息 ID 指向的当前有效、明确授权可参与授权判断；助手、模型、工具、文件内容均不能产生授权。
5. 任意无法完整解析、完整表达、完整脱敏或完整核对的动作最多到 ask；无 UI 时阻止。
6. 插件生成的确定性 allow 同样要求覆盖、健康、原生来源及信息完整性门禁；manual 的已知安全操作照常处理，但也不得绕过该健康门禁。
7. smart 许可只覆盖可无副作用完整 prepare 的 Linux 主会话 Bash 前台 native backend；其它 backend、执行形态、eval、MCP、task/child、子代理、非 Bash 和未验证平台保留原生 prompt/保护。
8. 主审必须审查 prepared plan 的最终 command 和必要变换摘要；raw args 与最终计划不一致、计划不可冻结或 commit 需要重算时不能自动 allow。
9. 用户授权证据必须有宿主认证的真实用户输入来源；仅有 user role、合成消息或工具引用不足以授权。
10. 配置、状态、审计、错误和摘要中秘密及插件审查副本的原始命令出现数必须为零；不改变宿主既有原生历史契约。

## Phase 11 分层审查绑定

ReviewRequest新增冻结remote_fallback实际provider/model/api，ExecutionBinding模型选择摘要覆盖主审、remote及配置/被动状态。PermissionDecision/审计分别记录primary和remote实际模型、0或1调用计数、有效性或故障状态，终态actual model/source可指向remote-fallback；tiny仍限权fallback。切换执行模型不能覆盖显式reviewer；任一审查选择/认证/provider生命周期变化失效所有在途层与permit。30秒总deadline由宿主共享，不能为remote重新起算。旧无remote配置与记录解析兼容；新增字段不能把旧历史调用虚构为remote。
