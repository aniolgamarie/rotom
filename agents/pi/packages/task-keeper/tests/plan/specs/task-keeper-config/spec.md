## ADDED Requirements

### Requirement: Independent local package and common entrypoints
系统 SHALL 作为 `pi/packages/task-keeper/` 的单父入口 Pi package 分发，提供 `/orch`、`/throttle`、`kernel_task` 和 kernel-orchestrate skill；命令、工具和恢复计时器 MUST 使用同一任务服务及派发准入。

#### Scenario: Tool and command control the same job
- **WHEN** 工具创建 job 后用户通过 `/orch pause` 暂停该 job
- **THEN** 所有入口均看到同一暂停状态且禁止新派发，不存在工具专属的旁路队列

### Requirement: Environment independent bindings
系统 SHALL 从配置读取 route、provider/model、账号引用、quotaGroup、transportDomain、网络、角色 profile、等待链、预算、可信检查和存储位置；核心 MUST NOT 按具体 provider/model 名称选择限流政策。

#### Scenario: Qwen service binding changes
- **WHEN** Qwen 场景改用另一个服务入口、模型 ID 和错误分类适配器
- **THEN** 仅修改配置与对应 adapter 绑定，核心调度和恢复状态机保持不变

#### Scenario: Missing deployment bindings
- **WHEN** 使用 enabled=false 且角色和账户未绑定的包默认配置
- **THEN** doctor 显示缺口且不发送模型请求；启用未绑定功能返回具体配置错误

### Requirement: Monotonic project policy
系统 SHALL 对路线、工具、recipe 取允许交集，对预算与并发上限取更严格值，对额度保留取更大值，对 required 检查取并集；项目 MUST NOT 替换用户层账号、执行器、网络或可信命令绑定，未知键和不可比较的扩权配置 MUST 被拒绝。

#### Scenario: Project expands protected budget
- **WHEN** 项目把用户上限 12 改为 24，或删除 required reviewer
- **THEN** 有效预算不超过 12 且 reviewer 保持 required，并解释被收紧或拒绝的字段

#### Scenario: Project disables a correctness invariant
- **WHEN** 项目新增 ignoreRequiredChecks 或 cancelMayResume
- **THEN** 配置验证拒绝，不将其作为可用开关（T87）

#### Scenario: Project adds an untrusted verification command
- **WHEN** 项目新增 required checkId 并试图随之定义任意 argv
- **THEN** 只有用户层已存在的可信绑定可被引用，新的执行命令被拒绝

#### Scenario: User explicitly changes the root contract
- **WHEN** 用户明确调整根验收、权限或预算
- **THEN** 建立新的授权与 TaskSpec 版本，使受影响提议及回执失效；普通 resume 不执行该变更

#### Scenario: Restriction algebra and numeric boundaries
- **WHEN** 项目收紧重复应用，或输入空允许集合、零预算、负数、非有限数和越界比例
- **THEN** 重复应用不扩权；空集合禁止对应动作，零预算禁止新的对应请求，非法数值被拒绝，required 检查不丢失

### Requirement: Capability gated defaults
系统 SHALL 默认 disabled、仅 direct、Advisor off、narrator off；能力声明和配置意图 MUST 分开，未实现的功能请求 MUST 明确拒绝，认证失效 MUST 阻止依赖动作。

#### Scenario: Unsupported advisor mode requested
- **WHEN** P0–P3 安装配置 advisor.mode=on-demand
- **THEN** 返回未实现能力错误，不静默开启或使用主模型代替

#### Scenario: Managed executor is unavailable during P1
- **WHEN** pi-subagents 未安装或 child reporter 尚未认证，但 InteractiveAdapter 已认证
- **THEN** 合格的主会话同路线恢复仍可启用，受管 workflow 显示不可用，不阻塞 P1

### Requirement: Deployment preserves user state
包声明 SHALL 通过 settings 模板及现有事务同步分发；用户 task-keeper.json、凭证与 runtime.db MUST NOT 被包资源同步覆盖。配置升级 SHALL 保留用户绑定并验证版本。

#### Scenario: Repeated package synchronization
- **WHEN** 插件已在模板声明且本机已有策略与等待任务数据库，再次同步
- **THEN** 包声明保留，用户授权绑定、预算、intent 与等待任务均不被重置

### Requirement: Explainable user control
系统 SHALL 支持 `/orch doctor|audit|inspect|fix|status|evidence|decisions|pause|resume|stop` 与 `/throttle status|pause|resume`；输出包含实际路线、原生状态、任务状态、失败或未知、未完成检查和下一合法动作。

#### Scenario: Resume a terminal job
- **WHEN** 用户对 COMPLETED 或 CANCELLED job 调用 resume
- **THEN** 返回终态及原因，不重开执行或刷新预算

#### Scenario: Resume while a blocker remains
- **WHEN** 用户恢复仍存在 required 失败、未知 writer 或未满足 notBefore 的任务
- **THEN** 重新核对阻塞和资源，只执行当前合法动作，不清除失败、预算或服务器冷却

#### Scenario: Low noise status without a footer dependency
- **WHEN** 任务长时间等待或关键证据通道失效
- **THEN** 宿主状态区以节流更新显示等待时间或 stale/unknown，仅关键变化通知；无 UI 时保留同等状态字段
