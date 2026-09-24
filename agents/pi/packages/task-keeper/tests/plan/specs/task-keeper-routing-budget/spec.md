## ADDED Requirements

### Requirement: Hard eligibility before route preference
路由 SHALL 先检查允许外发范围、账户、工具、上下文、profile、观测、资源及预算，再对合格候选排序；MUST 区分 quotaGroup 与 transportDomain，模型能力分数不能抵消硬条件缺失。

#### Scenario: Preferred route lacks required capability
- **WHEN** 更便宜或更强的候选缺失 required 工具或授权
- **THEN** 拒绝候选并显示原因，无合格路线则等待或阻塞（T27、T78）

#### Scenario: Thinking labels match but route semantics differ
- **WHEN** 两个模型都声明 high 而其协议、映射或能力证据不同
- **THEN** 按各自 route/profile 核验，不能凭同名标签认定满足要求；未知风险不自动按低风险放行

### Requirement: Configured stage chain with safe transitions
恢复 SHALL 按具有唯一 stageId 的配置链执行，允许首尾同一路线；未绑定或未授权阶段 SHALL 明确跳过，无合法最终路线 MUST 报配置阻塞，换模 MUST 在旧执行及相关副作用已对账的安全边界进行。

#### Scenario: Primary becomes available during backup wait
- **WHEN** 备胎仍在等待而主力产生恢复候选
- **THEN** 可按统一许可提前试探主力；备胎执行中不得立即另起 writer（T50）

#### Scenario: Restart during a bounded stage
- **WHEN** 阶段等待了一部分时间后探测失败、暂停恢复或进程重启
- **THEN** 继承 stageEnteredAt 与 deadline，不重新获得完整等待窗口；阶段超时只改变候选，不强杀运行 writer 或提前违反原 route notBefore

#### Scenario: Backup succeeds while primary incident remains open
- **WHEN** 备用路线成功但主力额度池尚未满足真实恢复条件
- **THEN** 原 incident 和事故备胎累计保留，后续 fallback 不借机创建零预算事故

#### Scenario: Network policy fails
- **WHEN** 配置的代理或网络路径不可用，包括 SOCKS fixture
- **THEN** 返回网络失败，不静默改直连或误判账号额度（T34）

### Requirement: Actual request attempt admission
受保护自动请求 SHALL 在每次真实 HTTP 尝试前通过可拒绝 gate 并持久预留，覆盖原生 retry、辅助生成、压缩和受管子进程；只有 payload 观测 hook MUST NOT 被认证为严格 gate。

#### Scenario: Runtime lacks reliable gate
- **WHEN** adapter 无法在每个真实尝试前可靠拒绝
- **THEN** 禁用依赖严格预算的自动调用，允许独立认证的非受保护同路线恢复（T33）

#### Scenario: Auxiliary generation consumes budget
- **WHEN** 重试、汇总或压缩产生额外请求
- **THEN** 使用同 workScope 的许可并计入累计额度，不能从主轮次计数中漏掉（T29、T67）

#### Scenario: Gate denial prevents transport send
- **WHEN** 多个受管进程同时竞争最后一个请求许可，或原生 SDK retry/辅助调用遇到 gate 拒绝
- **THEN** 独立接收端记录的实际尝试数不超过许可数；被拒绝请求不能到达接收端，异常被吞后继续发送必须使认证失败

### Requirement: Shared budget and unknown reservation
事故备胎、workScope 受保护预算 SHALL 跨 job/attempt/route/recipe/fork/恢复累计；稳定 request identity SHALL 仅结算一次，发送结果未知 MUST 保留 reservation。

#### Scenario: Fourth backup attempt exhausts configured incident budget
- **WHEN** 测试配置事故备胎上限为 4 且第四次已用完，主力仍不可用
- **THEN** 不发第五次备胎请求，返回主力等待且保留所有历史（T28）

#### Scenario: Request acknowledgement unknown
- **WHEN** 请求可能已发出但无法确认费用或终态
- **THEN** 未知预留不按零释放，新 attempt 或 incident 不重置 workScope 总预算（T30、T31）

#### Scenario: Model budget exhausted while local verification remains
- **WHEN** 模型预算耗尽，但可信纯本地检查、取消或对账仍可执行
- **THEN** 不申请模型请求许可，按实际计算及工作区资源继续；任何检查产生的模型请求仍须独立过 gate

#### Scenario: Duplicate settlement and distinct retry attempts
- **WHEN** 同一 requestAttempt 的终态重复或乱序到达，且同逻辑请求另有真实重试
- **THEN** 重复终态只结算一次，独立重试使用独立 requestAttempt 并计数，unknown 不当作未发送释放

### Requirement: Quota telemetry provenance
窗口额度观测 SHALL 绑定账户、桶、时间与来源；不匹配或过期 SHALL 为 unknown，MUST NOT 将遥测等同服务端额度预留或自动扩额许可。

#### Scenario: Stale or wrong account telemetry
- **WHEN** 观测来自不同账号、不同桶或超过配置 freshness
- **THEN** 不使用它准入依赖该遥测的受保护路线（T32）

### Requirement: Bounded recipe selection
系统 SHALL 默认 direct；启用 cascade/critique 必须经过能力、授权和测试准入，RecipePolicy MUST 是无副作用规则，不能持 timer 或执行 spawn。

#### Scenario: Critique followed by cascade
- **WHEN** 定向质疑产生修订，随后提议质量升级
- **THEN** 两者共用原语义尝试、请求和 step 额度，不通过策略嵌套刷新计数（T80）

#### Scenario: Critic has no supported actionable finding
- **WHEN** critique 无可处理发现，或意见缺乏必要证据
- **THEN** 不强迫 writer 修订，不消耗一次虚构语义修复；仍按原 required 验收继续

#### Scenario: Selector attempts to execute
- **WHEN** recipe selector 尝试注册重试 timer、写工作区或直接派发
- **THEN** 架构与契约测试拒绝，该操作只能经唯一 dispatcher（T88）

### Requirement: Required work reservation and advisory boundary
可选 critique 或未来 Advisor 调用 SHALL 保留 required 阶段最低预算；建议不能修改权限、预算或 TaskReceipt。未实现 Advisor 的版本 SHALL 拒绝启用，其未来契约 SHALL 保留 shadow 不执行、尝试有界及安全规则回退。

#### Scenario: Optional review would consume required reserve
- **WHEN** 可选 critic 的请求会占用 required 测试后审查的最低预留
- **THEN** 跳过可选步骤并披露，required 不足则暂停，不把 required 降为 optional（T82）

#### Scenario: Proposal legality unchanged after accounting
- **WHEN** 建议相关调用只改变费用观测，当前预算仍满足准入
- **THEN** 不使 decisionRevision 自动过期；预算不足时明确拒绝派发（T85）
