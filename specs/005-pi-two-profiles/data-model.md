# Pi 双 Profile 逻辑数据模型

日期：2026-10-04。状态：规划契约；字段描述逻辑身份和不变量，不要求新建通用数据库、配置 DSL 或公开 schema。实现优先复用现有 manifest、supervisor、lease、receipt 与运行包记录。

## 1. 身份与所有权

| 实体 | 最小逻辑字段 | 不变量 |
|---|---|---|
| `ProfileDefinition` | `profileId`、共享基础版本、选择的资源/插件/模型、策略引用、功能开关 | `pi-base` 与 `pi-full` 是两个最终产品；可共享只读运行包、公共资源和数据库工程知识 Skill，不共享可写会话、审批或任务状态。Base 的定义中不存在 Full 专属包、工具、受管流程 Skill 和服务探测。 |
| `RuntimeIdentity` | profile、上游发行物、依赖切片、运行包摘要、适配器版本、目标平台 | 一次执行和证据固定一个身份。运行包变化使依赖其行为的旧证据失效；摘要不包含秘密。 |
| `CapabilityBinding` | 能力名、提供者来源/固定版本、适配契约版本、兼容范围、配置与状态所有者、冲突能力、迁移/卸载/回退引用 | 是现有依赖与资源清单的逻辑扩展，不是新插件平台。用户流程依赖能力契约；替换只改提供者绑定及必要适配，不放宽权限或使Base引入Full依赖。旧执行保留原绑定，不假定不同提供者的会话/状态格式互通。 |
| `ProviderSelection` | capability→provider绑定、profile、required/optional、契约版本、来源revision、当前/候选/已验收状态 | 与安装树/加载集合分别核对。当前0.84.4锁不是候选1.0.1已安装的证明；同一单owner能力拒绝多个提供者，替换不能在运行时自动换源。 |
| `ReplacementRecord` | 原/新绑定、staged位置、兼容/迁移检查、配置基线、数据恢复点、活动引用、激活进度 | `staged→validated→activation-pending→active→retired`；失败进入restored或recovery-required。只在允许的空闲边界激活，旧引用未清零不得卸载。 |
| `ConfigIdentity` | 有效 profile 配置、机器覆盖、项目收紧项、策略版本的非秘密摘要 | 项目只能收紧上界。账号、OAuth token、API key 内容及其散列都不进入身份、日志或通用摘要。 |
| `PermissionPolicySnapshot` | policy generation、规则摘要、角色上限、读写根、命令绑定、网络/服务上限 | 单一权威来源，默认拒绝。hard deny、必须人工项和角色上限不能被模型、项目或子任务放宽。 |
| `WorkspaceIdentity` | 规范路径、文件系统身份、根类型、适用时的Git/worktree身份、协调锚身份 | 同一物理工作区在不同受管 profile、进程和任务中映射为同一写资源；路径别名和符号链接不能为受管入口创建第二个 Writer。未受管 Pi、用户编辑器或其他进程不遵守此租约，其变化由快照/身份复核发现并使证据失效。 |
| `RegisteredRoot` | 明确登记的根、文件系统身份、Git/非Git类型、本机协调锚、登记所有者 | Git根复用现有租约；非Git根必须登记且跨profile指向同一协调锚，不以profile HOME派生各自独立锁。根被替换或身份未知拒绝写入；不自动git init。 |
| `StorageOwner` | 存储根、服务实例身份、格式版本、所有权 epoch | 同一 Durable 存储同时只有一个写所有者。新 owner 必须先证明旧 owner 已退出或完成恢复接管。 |

所有身份中的 digest 只用于变化检测和绑定，不是权限令牌。无法完整表示、无法规范化或包含未知字段时失败，不做猜测性修复。

## 2. 权限与执行实体

### `OperationIntent`

表示宿主从真实入口观察到的一次候选操作，至少绑定：

- 唯一 `operationId` 与调用方 `requestId`；
- profile、会话、角色、cwd 和工具入口；
- 最终工具参数或规范 argv，而非显示用摘要；
- 用户意图来源及当时仍有效的限制；
- policy generation、运行身份和执行上下文；
- 请求时限、取消 epoch 和需要的资源类别。

`operationId` 不可由模型自报取得权限。相同 `requestId` 重试只有在完整规范请求相同的情况下返回同一身份或结果；相同 ID 携带不同请求必须报幂等冲突。

### `PreparedOperation`

可信控制面完成解析、根解析、固定命令绑定、权限上界和资源预检后的执行对象。它包含非秘密 `operationDigest`、具体读写根、网络/服务能力、可执行文件身份、目标工作区和预期执行后端。审批审查的是这个对象；执行也只能消费同一个对象。

准备对象的完整逻辑记录还绑定最终参数/规范 argv 的私有正文。它们存放在同一控制面持有的有界内存记录中；对外序列化的 PreparedOperation 投影只携带随机 `private_input_ref`，不携带正文或正文散列。这与执行契约的私有正文规则一致，不允许把任意调用者的 ref 或新参数当作原参数。审批使用本次捕获并绑定该记录的参数/安全投影；幂等及执行消费必须与原私有字节完整比较。公开 DTO 本身不是完整私有记录，也不是执行授权。

准备成功不等于获准执行。未知工具、不能表达的 deny、隔离后端不可用或策略不完整时不能产生可执行对象。

### `ApprovalDecision`

决定为 `allow | ask | deny`，并记录来源 `hard-policy | deterministic-policy | reviewer | human | system-failure`、绑定的 operation/policy/session/cwd/model 身份、时限和结构化原因码。模型输出只是候选决定：只有硬策略已允许、风险类别允许自动通过且所有绑定仍为 current 时，才能合成为 `allow`。有效 reviewer `ask/deny`、reviewer 超时、Provider 故障、协议无效和用户取消使用不同结果类别及原因码，不能都折叠成同一种 ask。

模型审查不持有执行回调，不接收认证材料，不带工具，不隐式重试或换 Provider。有效 `deny` 不进入下一模型争取翻案；故障、超时、协议无效与有效拒绝分别记录。取消后的迟到完成仍保留最小账本事实（请求身份、实际模型、取消/丢弃状态、调用计数和耗时类别），但不能创建决定或许可，也不记录秘密正文。

### `ExecutionPermit`

一次性、短期许可，绑定一个 `PreparedOperation`、policy generation、session/cwd、取消 epoch、实际决定来源和允许的资源。状态为：

```text
pending -> consumed
pending -> revoked | expired
```

只有执行入口能原子消费。重复消费、跨请求/会话/cwd 使用或绑定变化均拒绝。permit 不提升 OS 权限，也不能扩大准备对象的根、网络、argv 或角色能力。

### `ExecutionLease`

表示已进入物理执行生命周期的受保护资源，包含 grant generation、进程出生身份、工作区租约、超时、捕获输出与终止证据。许可已消费后，简单修改配置只能阻止后续动作，不能把正在运行的进程宣称为已撤销。运行中的撤销走取消协议，直到真实终止确认前仍保持资源保护。

## 3. 操作状态机

```text
observed
  -> prepared
  -> awaiting-review | awaiting-human
  -> permitted
  -> starting
  -> running
  -> completed | failed | canceled | timed-out

任意未执行状态 -> denied | revoked | expired | blocked
starting/running -> cancel-requested -> stopping
stopping -> canceled（仅有终止证明）
stopping -> termination-unknown（无终止证明，资源继续保护）
```

关键边界：

- 参数、目标、cwd、session、policy、模型选择、用户限制、模式或取消 epoch 在执行前变化，撤销未消费许可并重新准备。
- 审查 await 期间收到取消或收紧策略，迟到结果只能登记为 discarded，不能产生许可。
- `cancel accepted` 或服务返回 cancel ack 只说明请求已接收，不是 `canceled`。只有进程/后端终止和资源回收证据齐全才进入终态。
- 发送是否发生、后端是否已产生副作用无法确定时进入 `termination-unknown` 或任务 `unknown`；禁止自动重放和释放 Writer。

## 4. 委派、工作流与 Writer

| 实体 | 最小逻辑字段 | 不变量 |
|---|---|---|
| `DelegateRequest` | requestId、父宿主、任务/步骤、执行模式、后端、模型、cwd、权限/预算身份、输入摘要 | Pi 与 Codex 入口产生同一规范请求。模型提供的 `approved=true`、任务 ID 或角色名不创建授权。 |
| `DelegateRun` | runId、backend native identity、resume token、实际模型、状态、消息序列、用量、产物引用 | 状态来自真实后端和监督者，不从模型文字推断。继续必须绑定同一 run；不支持时明确拒绝。 |
| `WorkspaceLease` | WorkspaceIdentity、owner task/attempt、mode、generation、获得/释放证据 | `writer` 对同一工作区的所有受管入口排他，覆盖 Base/Full、受管 Pi、delegate 和 Durable 服务。只读任务可并行，但不能通过产物目录别名写业务工作区；用户或未受管进程的外部修改不受锁约束，并使相关快照与证据 stale。 |
| `Workflow` | taskId、固定步骤、最多返工数、当前阶段、required/optional 关系 | Inspect/Fix 最多两轮定向返工；超过后保留未完成并交主代理决策，不把 exhausted 改写为成功。 |
| `TrustedCheckBinding` | checkerId、冻结 argv/实现身份、输入快照、可信配置身份、结果契约 | Worker 不能修改 checker、通过条件或其权威配置。若 checker 位于 Worker 可写范围，检查无效。进程退出 0 不是充分通过条件。 |

## 5. 任务、快照与证据

### `InputSnapshot`

绑定验收相关的受跟踪与未跟踪输入、配置、策略、运行身份、checker 身份和必要环境事实。可以保存文件摘要和受控路径引用；秘密文件只记录“引用存在/读取结果类别”等非秘密事实，既不保存正文，也不保存秘密内容散列。

heartbeat、日志增长、轮询时间和用量记账等纯观测字段不进入语义输入身份；预算在实际准入时单独复核。生成物排除必须显式定义，防止排除真实源码，也避免执行记录自身使所有证据持续失效。

### `EvidenceRecord`

至少记录 profile、RuntimeIdentity、ConfigIdentity、平台、场景/检查 ID、层级、规范输入身份、真实入口、cwd、开始/结束时间、协议状态、退出/测试计数、终止证明、产物位置和已知未知项。有效性状态为 `current | stale | invalid`，测试结果与有效性分开：

- 相关输入、未跟踪文件、策略、checker、运行包或所声明平台变化后为 `stale`；
- 记录损坏、身份对应错误、缺少到无法核验的必需终态/工件，或只能得到模型自述且没有程序事实时为 `invalid`；
- 身份与结构可核验且尚未过期时为 `current`。非零、零测试、全跳过及语义断言失败都是 current 的失败证据，必须保留真实失败结果，不能改标 invalid 来隐藏；
- 只有 current 证据通过独立 oracle 的产品成功条件并满足所需层级时，才有资格支持 `passed`。

快照和 evidence 是不同对象：快照描述“测了什么”，evidence 描述“观察到什么”。故障关闭、进程退出 0、测试 harness 的内部状态都不能单独证明产品语义。

## 6. Durable 与预算

### `DurableTask`

包含稳定 requestId/taskId、提交者授权、只读能力、专用产物目录、输入快照、状态、消息序列、恢复 epoch、结果引用和终止证据。这里的“只读”指不得写业务工作区或运行任意 Shell；允许写服务自身的状态、日志和该任务专用产物目录。产物发布到业务位置需要新的显式操作与权限。

状态机：

```text
accepted -> queued -> starting -> running -> completed | failed
queued/running -> cancel-requested -> stopping -> canceled
starting/running/stopping -> unknown | blocked
unknown -> reconciled-running | completed | failed | canceled
```

前端退出只断开观察者，不改变任务授权。服务重启先恢复存储所有权并对账 native identity；不能因本地行缺少终态而重复提交。响应丢失按 requestId 查询，同 ID 不同请求为冲突。

### `BudgetLedger`

按任务和可控请求记录 `known | estimated | unknown | reserved`，绑定调用身份、实际模型/provider 和累计限制。重启、重连、resume 或 profile 切换不清零累计值。无法观察的外部用量保持 unknown；不能显示为 0 或无限。预留在确证未发送或已结算后释放，发送状态未知时继续占用。

### `ModelAttempt`

服务端在公开Provider发送入口创建，字段至少含attemptId、task/phase、registry/输入/策略身份、实际模型路线、预算预留、发送状态与结果引用。状态`prepared→sending→result-recorded→settled`；先持久sending再发请求，崩溃后无确定结果为unknown，不自动补发。能证明未发送才转not-sent释放预留。账本不保存认证正文，也不充当另一任务队列。

### `DurableDeploymentIdentity`

SDK精确包身份、公开存储adapter/配置、schema版本、registry内容身份及工具选择。SQLite初选需通过公开适配验证WAL/FULL；不能假定默认参数足够。打开存储之前检查部署兼容性，任务恢复必须使用原身份或明确验证的迁移，不在进行中热换同名registry代码。

物理归属：普通执行为现有受管文件记录，TK为既有独立SQLite，Durable服务为独立SQLite与其发送账本。三者不合并为一个数据库，不复制彼此的权威任务状态；共同引用执行/任务ID进行核对。

## 7. 恢复与升级

- 配置回滚、运行包选择回退和持久数据迁移是三个动作，分别记录身份和恢复点。
- Durable 数据迁移前创建副本并实际验证恢复；不假定新格式可被旧版本读取。
- 活动 lease、Writer 或 termination unknown 存在时，新版本不能自动接管、终止或复制执行。
- profile 共享基础升级后，两者相关 evidence 同时失效并分别回归；Base 不因 Full 阻塞失去独立发布资格。
- 用户已冻结本轮必需平台为当前 Linux x86_64 环境。P0 只核实本机内核、发行版、架构和隔离运行时并形成具体矩阵；Mac、其他架构和 WSL 为可选按需项，不阻塞总交付，未执行时不记通过。
