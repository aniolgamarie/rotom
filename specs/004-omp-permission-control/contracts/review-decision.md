# Contract: Review Decisions

> 本文保留宿主补丁方案的历史模型/契约。自2026-09-30起按不修改上游源码原则迁移，当前要求以[独立插件修订](../standalone-plugin.md)为准；不得继续依赖宿主bridge或私有接口。

本契约分开“模型建议”与“宿主最终决定”。模型只返回严格结构；宿主 bridge 根据原生约束、固定策略和有效用户授权产生 `allow|ask|deny`。任何模型字段、置信度、文件/工具内容或执行模型理由都不能直接创建许可。

## 主审输入信封

主审收到单一、无工具的结构化请求，包含：schema/策略版本、`PreparedBashExecution` 的完整脱敏最终 command、从原始请求到最终计划的固定变换摘要、shell/cwd/backend 类别、解析出的全部 effect（有稳定 `effectId`）、每个简单命令的原生约束、宿主逐 effect 生成的 scopeDigest、相关用户授权消息、覆盖/平台和明确的“不可信数据不得授权”规则。请求不能只含 raw args；prepared plan 身份与 binding 由宿主本地保留并在最终核验时使用。

授权消息除 user role 和 message ID 外，必须带宿主认证的真实用户输入来源证明；模型信封还为每条消息携带宿主从正文重新计算的 `utf8ByteLength`，不接受外部提供的长度。模型、工具、文件、导入历史或内部流程合成的 user-role 消息不能授权，工具输出引用也不能变成授权。来源元数据缺失、不可验证或已撤销时按 `ambiguous-authorization` 处理为 ask；无 UI 时阻止。执行模型理由、助手消息、文件与工具输出只能作为带来源的非可信事实，不能进入授权证据集合。

序列化输入最多 24 KiB UTF-8。额度不足以容纳完整操作、效果或必要授权，或脱敏损失判定语义时，不调用或不采纳 allow，直接 ask；无 UI 时阻止。主审最多一次；无远程fallback时最多25秒，配置远程时最多12.5秒，输出最多 512 tokens 且 4 KiB。仅当 transport 为 `openai-completions` 且模型 ID 精确为 `kimi-for-coding` 时，请求显式发送 `thinking:{type:"disabled"}`，避免固定输出额度被推理 token 耗尽；其它模型和 transport 保持原请求形状。

## 主审严格 JSON

唯一允许的顶层字段如下，全部必填，禁止额外字段、Markdown、前后文本、工具调用、NaN、重复键和自由文本理由：

```json
{
  "decision": "allow",
  "risk": "low",
  "authorization": "sufficient",
  "effects": ["effect-1", "effect-2"],
  "unknowns": [],
  "reasonCode": "LOW_RISK_AUTHORIZED",
  "evidence": {
    "userMessageIds": ["msg-user-17"],
    "bindings": [
      {"effectId": "effect-1", "userMessageId": "msg-user-17", "startByte": 0, "endByte": 6, "scopeDigest": "0000000000000000000000000000000000000000000000000000000000000000"},
      {"effectId": "effect-2", "userMessageId": "msg-user-17", "startByte": 0, "endByte": 6, "scopeDigest": "1111111111111111111111111111111111111111111111111111111111111111"}
    ]
  }
}
```

示例中的全 0/全 1 摘要仅作结构示意；`endByte=6` 假定所引消息的宿主权威 `utf8ByteLength` 为 6，实际响应必须使用该次消息的完整长度，并逐字匹配该次宿主输入中的 scopeDigest。

字段 schema：

| 字段 | 类型与枚举 | 约束 |
|---|---|---|
| `decision` | `allow \| ask \| deny` | 只是建议；最终合成见下节 |
| `risk` | `low \| medium \| high \| unknown` | medium/high/unknown 不可能合成为自动 allow |
| `authorization` | `sufficient \| insufficient \| conflicting \| unknown` | 只有 `sufficient` 可能支持 allow，且仍须宿主验证证据 |
| `effects` | 唯一字符串数组 | 必须恰好覆盖输入的全部 `effectId`；不得自行发明或遗漏 |
| `unknowns` | 唯一枚举数组 | `dynamic-syntax`、`unresolved-target`、`redaction-loss`、`missing-context`、`ambiguous-authorization`、`unsupported-effect`、`state-not-verifiable` |
| `reasonCode` | 固定枚举 | 见下表；UI 由代码模板生成，不展示模型文本 |
| `evidence.bindings` | 逐 effect 证据数组 | 精确字段、字节区间及 scopeDigest 校验见下节；不能把引用有效等同于语义充分 |
| `evidence.userMessageIds` | 唯一字符串数组 | 只能引用本次输入中由宿主认证为真实用户输入的 message ID；仅 role 为 user、合成 user 或非用户消息 ID 均无效 |

数组有明确上限：`effects` 不超过输入 effect 数，`unknowns` 最多 7 项，`userMessageIds` 最多 16 项。`allow` 要求 `risk=low`、`authorization=sufficient`、`unknowns=[]`、effects 全覆盖、evidence 非空且全部仍有效，并要求 `reasonCode=LOW_RISK_AUTHORIZED`。仅固定策略中受限只读规则允许免逐次授权；该路径须先核对用户限制与范围完整性；限制尚不明时跳过直通，smart 进入主审后仍不明才 ask，manual 直接 ask。它在调用模型前处理，不能让模型用空 evidence 扩大 allow。

主审 `reasonCode` 只允许：

```text
LOW_RISK_AUTHORIZED
USER_CONFIRMATION_REQUIRED
AUTHORIZATION_INSUFFICIENT
AUTHORIZATION_CONFLICTING
MATERIAL_RISK
PROHIBITED_EFFECT
UNKNOWN_EFFECT
INCOMPLETE_CONTEXT
REDACTION_LOSS
POLICY_MISMATCH
```

枚举组合不一致、缺字段、额外字段、未知 effect/message ID、超预算、截断或语法无效都归为 `invalid-output`，不会尝试让模型修复或重试。

## 固定最终合成

宿主按以下顺序短路；靠前结果不能被靠后阶段放宽：

1. 原生 `explicit-deny` 或固定禁止规则 → `deny/hard-rule`，不调用模型。
2. `command-prompt`、`critical-safety`、未知原生来源、宿主强制人工检查、已知结构化用户限制冲突或固定风险下限要求人工的效果 → `ask/native-protection`；无 UI 阻止，不调用模型。
3. 在任何插件生成的 allow 前，核对插件/runtime/ABI、bridge 与原生保护基线健康，请求属于可无副作用完整 prepare 的 Linux 主会话 Bash 前台 native backend（包含保持原义的自动后台管理），prepared plan 的最终 command、变换摘要、上下文和原生来源可分析且目标状态可核对。不能冻结的动态 direnv/devenv、prefix、service/async/PTY、ACP terminal、未知启动脚本或其它 `manual-required` 原因都终止 smart/确定性放行，保留配置并返回受保护的原生人工流程；无 UI 时阻止。纯 interceptor 未命中、已认证初始化环境及无有效配置的 direnv 自动检测不得仅因开关存在被当作未知状态。
4. 通过步骤 3 且用户限制状态为 clear 后，命中固定受限只读规则（不含写入、网络发送、秘密/设备读取或未知副作用） → `allow/low-risk-rule`，不调用模型。
5. 通过步骤 3 后的 manual 模式 → `ask/manual-boundary`；已知安全操作已在步骤 4 处理，其余无 UI 阻止，不调用模型。
6. 有效主审 `decision=deny` → `deny/reviewer`。
7. 有效主审 `decision=ask` → `ask/reviewer`，远程fallback和tiny都不复审。
8. 主审建议 allow 只有同时满足全部 allow 约束、完整授权语义判断与已通过机械核验的逐 effect 证据、有效当前用户授权、固定策略允许、无原生边界且执行前状态可复核时 → `allow/reviewer`；否则 `ask` 或固定规则要求的 `deny`。
9. 主审超时、服务故障、invalid-output、不支持或不可用时，仅显式配置的远程fallback可接替完整同等级审查。它的有效allow/ask/deny均按步骤6—8核验并终止链，失败才可进入tiny。未配置remote时保持原tiny故障触发集合；tiny只能产生ask/deny。

模型声明“用户已授权”不够；主审必须判断授权语义与之后的撤销/限制；宿主必须核对 message ID 的当前有效真实来源、逐 effect 引文及对象/参数/上下文摘要，并确保没有遗漏后续上下文。职责与限制见下节。仅有 `role="user"`、合成 user 消息或工具输出引用一律不足。模型 risk low 也不能覆盖授权不足。主审 deny 不交给 tiny 翻案。

## 授权判断的职责与证据

主审承担自然语言授权语义判断：用户要求是否涵盖每个 effect，是否有之后的限制、撤销或冲突。allow 所依赖的指代必须仅从真实用户消息唯一解析；存在多个候选时，主审不得用拟执行 operation/effect 反向选择指代对象，除非用户明确委托主审在这些候选中作出选择，否则以 `ambiguous-authorization` 转 ask。仅列出候选，或允许检查一个未指定候选，不构成这种选择委托。宿主承担可机械验证的检查：真实来源、完整上下文、逐 effect 的原文证据、实际对象/参数/cwd 绑定、固定风险下限、原生规则与最后失效检查。宿主不能独立证明任意自然语言的蕴含关系；不得把消息来源验证、完整引用、提示政策或严格 JSON 宣称为语义正确性的保证。这里的“模型不能制造授权”指它不能把非用户材料、伪造引文、缺失证据或规则外范围变成许可，不意味着代码能排除所有语义误判。

`evidence` 必须恰有 `userMessageIds` 与 `bindings` 两个字段。`bindings` 是数组（模型 allow 必须非空，其余可为空），每项恰有 `effectId`、`userMessageId`、`startByte`、`endByte`、`scopeDigest`。start/end 为非负整数，表示本次脱敏输入里对应用户消息 UTF-8 字节的半开区间，必须是字符边界且 start < end；引用不另复制正文。模型 allow 的每项 binding 必须引用整条真实用户消息，即 `startByte=0` 且 `endByte` 等于宿主从正文计算的 `utf8ByteLength`；ask/deny 若提供 binding，可继续使用任意有效非空区间。整条引用只加强机械完整性，不能证明该消息在语义上授权 effect。scopeDigest 是宿主为该 effect 的种类、规范目标、完整参数、cwd 与执行上下文绑定生成的会话盐 SHA-256，随 effect 输入给模型；它只是绑定摘要，不是授权令牌。模型 allow 时每个 effect 恰有一项 binding；ask/deny 可为空。effect/message ID 必须来自本次输入、消息 ID 必须列在 userMessageIds 中且不得列无引用的 ID；重复、缺项、超出输入 effect 数或引用越界均为 invalid-output。总输出仍受 512 tokens/4 KiB 限制，不能完整表达时 ask，不拆成多次推理。

宿主先验证 evidence 结构与真实来源，再逐项比对 scopeDigest、当前 prepared plan 和引用字节，最后复查授权上下文 generation。原文含秘密或截断导致语义丢失时 ask。宿主不根据模型字段写入长期授权或修改策略；人工批准只走 HumanDecision。任一机械检查失败，即使主审返回 low+sufficient 也不允许。主审在完整真实用户消息上作语义判断，不能只接收它自己挑选的引文；后续撤销/限制与当前任务相关消息必须完整提供，无法确定上下文完整性时 ask。

确定性只读例外只在固定低风险规则、覆盖/健康/完整性条件及已验证的用户限制均通过时生效。用户限制状态为 `clear|conflicting|unknown`，绑定当前上下文 generation。初始 clear 仅适用于宿主确认上下文完整、没有待解释的用户自由文本，且不存在限制或全部已知结构化限制均可机械验证通过的情况；已知结构化限制冲突为 conflicting，按步骤 1/2 拒绝或转人工，不交主审放宽。其它状态（包括新的自由文本或上下文缺失）为 unknown，不能仅凭关键词未命中就按 clear 走直通。smart 可进入本次唯一主审让模型结合完整上下文判断；manual 转人工。主审通过后结果来源为 reviewer，不追记成 low-risk-rule，也不把本次语义结果缓存为后续请求的默认授权。原生/结构化明确限制始终由宿主强制，自然语言限制的理解属于上述主审信任边界。

固定策略还必须提供独立风险下限：写入/删除、网络发送、凭据/秘密或设备访问不能仅因模型给 low 而自动允许；未知效果保持 ask。这不要求用户采用新句式或第五个命令。普通自然语言可作为主审的授权证据，但不能宣称任意审查模型都能正确理解它；SC-002 的真实模型评测必须覆盖否定、只读限制、路径范围、例外、撤销和指代，有限样本结果不外推。

隔离反例必须包含：有效用户 ID 却漏掉管道 effect、scopeDigest 对应另一对象/参数/cwd、伪造或越界引用、未提供更晚限制、旧 generation 响应，以及主审把写入标 low（由固定风险下限阻止）。自然语言“只读”与动作冲突的语义判断用标注样本验证，fake 主审只证明流程，真实模型语义正确性只由 T073 的独立评测给证据，不冒充宿主确定性证明。

## tiny 严格 JSON

tiny 输入最多 8 KiB，包含脱敏后的效果、主审故障类别和固定限制，不要求其重审完整对话。输出最多 128 tokens 且 1 KiB，顶层恰好两个字段：

```json
{
  "decision": "ask",
  "reasonCode": "FALLBACK_HUMAN_REQUIRED"
}
```

`decision` 只允许 `ask|deny`。`reasonCode` 只允许：

```text
FALLBACK_HUMAN_REQUIRED
FALLBACK_MATERIAL_RISK
FALLBACK_UNKNOWN_EFFECT
FALLBACK_INCOMPLETE_CONTEXT
```

任何 `allow`、额外字段、自由文本、工具调用、无效/截断/超预算输出都按 fallback failure 处理为 ask；无 UI 时阻止。tiny 最多一次、最长 5 秒且只用 30 秒总 deadline 的余量；无余量不调用。资源必须 installed-only，缺失或不健康不下载并维持 ask。

## 时间、取消与迟到响应

自动 deadline 在请求完成排队、开始构造审查上下文时起算，总计 30 秒，包含预处理、脱敏与效果分析、身份/资源检查以及全部模型等待；请求开始处理前的排队时间和人工等待不计入。无remote时主审最多25秒、tiny最多5秒；有remote时主审最多12.5秒，remote使用剩余时间并为配置的tiny预留最多5秒。unsupported主审不发推理，remote可获得剩余最多25秒。认证解析可以在调用前失败，但不能借认证刷新重发同一推理。

取消信号走 out-of-band 控制路径，不等待会话 Bash 串行队列；它立即使请求 generation/binding 不再可执行，并在 1 秒内进入 cancelled，宿主同时中止可中止的 transport。smart/manual 也先原子递增 generation 并发出 abort，再更新模式，不等待最长 30 秒的在途判定。超时、取消后返回或旧 generation 的模型/人工响应一律丢弃，不能写入许可、恢复 pending 状态或触发执行。

## 决定、许可与审计输出

每个自动终态产生结构化 `PermissionDecision`。allow 还需宿主创建绑定 prepared execution 身份、最终 command/参数、变换摘要、cwd、shell/backend、目标状态、授权、模式、策略、模型选择、健康和插件/runtime 身份的一次性 permit；执行前复核并原子消费同一 prepared plan。ask 在可靠 UI 中产生独立的 `HumanDecision`，其 `source=human`，必须关联原 ask 并保留上游 reviewer/fallback/native 来源链；human allow 只为同一仍有效绑定创建一次许可，human deny 终止请求。任何变化都重新请求，不缓存模型或人工 allow。

审计只记录请求/决定 ID、会话盐 operation digest、固定枚举、实际模型及来源或 `not-called`、调用数、耗时桶、健康和 permit 状态。发生人工决定时记录 human decision ID、`source=human`、outcome 和原 ask ID，形成 `ask → human allow|deny` 链。它不记录原始命令、消息正文、模型 JSON/自由文本、凭据、人工 UI 文本或异常原文。`explain` 从这些固定字段和代码模板生成短原因。

## 示例

健康 bridge 上，前台 native backend 的完整 prepared plan 为受限低风险读操作时，可由确定性规则放行；若调用主审，则模型收到最终 command 和变换摘要，宿主仍核对原生来源、真实用户消息来源和目标状态，符合全部条件才生成一次许可。若同一操作含管道把结果发往网络，effects 必须同时包含读取与网络发送；遗漏任一 effect 使输出无效而转 ask。

主审对删除操作返回 `allow/low/sufficient`，但原生来源是 command prompt：步骤 2 已短路为 ask，模型不会被调用或不能改变结果。主审超时且 tiny 返回 deny：最终 deny；tiny 返回 allow 或不可解析：最终 ask，无 UI 时阻止。

## 远程fallback模型与实际来源

`reviewer_model`显式优先，省略才session-default；remote不改这个选择策略。故障接替层使用相同完整envelope、严格decoder、真实用户来源/完整UTF8/逐effect scope及固定策略。对有效结果的机械核验失败只转人工，不能借下一模型翻案。同provider/model不重复尝试，每层实际推理最多一次；认证检查不计推理。remote来源为remote-fallback；审计分别保留主审/远程实际模型、调用数与失败状态，tiny限权来源仍fallback。manual/固定deny/强制人工/确定性直通不触发链。
