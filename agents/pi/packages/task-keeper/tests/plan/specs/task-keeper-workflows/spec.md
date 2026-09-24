## ADDED Requirements

### Requirement: Bounded inspect workflow
inspect SHALL 按任务需要进行最多两个受限只读调查、事实汇总与范围验收；工具和输入 SHALL 由 profile 约束，MUST NOT 由角色名称推定只读。

#### Scenario: Reader profile allows write
- **WHEN** 被请求的只读步骤解析出 write 或未受控 bash
- **THEN** profile 准入拒绝或收紧后重新验证，不能仅靠提示词宣称只读

#### Scenario: Bounded inspect completes without unnecessary workers
- **WHEN** 任务可由零至两个获准 reader 完成且范围证据满足 TaskSpec
- **THEN** 合法汇总并验收，不强制创建额外 agent；源码目录保持不变

### Requirement: Persistent fix workspace
fix SHALL 按 TaskSpec 创建 job 生命周期的持续工作区，按基线、调查、实现、冻结、验证、独立审查交付；隔离失败 MUST NOT 退回用户主树，MUST NOT 自动 stash/reset/clean 用户修改。

#### Scenario: Workspace cannot be created
- **WHEN** 隔离工作区创建失败或存在未知写入者
- **THEN** fix 阻塞并保留现场，不在主目录继续实施（T41、T43）

### Requirement: Trusted verification and snapshot binding
VerifyRunner SHALL 从可信 checkId 绑定解析 argv、cwd、环境、timeout 和结果解析器，回执 SHALL 绑定源码、相关未跟踪输入、检查脚本和环境身份。

#### Scenario: Exit zero but no required tests
- **WHEN** 命令返回 0 但测试数为零或全部 skip
- **THEN** 必需测试不通过；计数不可得按约定标 unknown，不以 exit0 代替验收（T44）

#### Scenario: Candidate or check changes after passing
- **WHEN** 代码变化、旧日志被复用，或 filter/阈值/检查脚本被修改
- **THEN** 相关回执失效，验收标准变更需要独立审查或授权（T45、T46）

### Requirement: Finite semantic repair
实施 SHALL 遵守配置的共享语义尝试、重规划与派发 step 上限；环境失败和额度等待 MUST NOT 被计为实现能力不足，策略切换 MUST NOT 清零次数。

#### Scenario: Environment build failure
- **WHEN** 基线构建因环境错误失败
- **THEN** 先诊断环境，不自动质量升级，不消耗语义修复额度（T79）

#### Scenario: Step limit reached
- **WHEN** 配置的 dispatched step 上限用完而任务未完成
- **THEN** 保留现场和未完成要求，暂停请求用户处理，不新建 job 刷新次数（T72）

### Requirement: Independent required review and exact reuse
required reviewer SHALL 按固定 TaskSpec 执行；诊断审查只有相同快照、要求、完整证据与独立性满足预设规则时才能复用，MUST NOT 因 direct 或已有 critic 删除验收。

#### Scenario: Stale diagnostic review
- **WHEN** 旧候选上的 critic 被用于当前最终验收
- **THEN** 拒绝复用并保持待审查（T77、T81）

#### Scenario: Review input or risk is weakened
- **WHEN** 模型试图降低用户指定风险，或用 writer 自述替代候选 diff 与真实验证
- **THEN** 拒绝降低要求，review 输入保留 TaskSpec、真实候选、验证和硬错误，并标明 diagnostic/acceptance purpose

#### Scenario: Valid review already exists
- **WHEN** 当前快照已有完全合格的独立验收审查
- **THEN** 复用并记录来源，不重复调用或放宽要求（T86）

### Requirement: Candidate delivery preserves failed attempts
完成交付 SHALL 包含候选补丁、验证与 TaskReceipt，不自动应用主树、push 或 merge；接受失败 attempt 遗留工件 SHALL 记录 artifact adoption 并独立验证。

#### Scenario: Cancel after partial edits
- **WHEN** writer 修改部分文件后被取消
- **THEN** 保留工作区与失败/取消证据，不声称已回滚，也不将候选当成完成补丁

#### Scenario: Fix produces a verified candidate
- **WHEN** 隔离工作区完成实现、当前快照构建与目标测试通过、required 独立审查满足
- **THEN** 交付候选补丁和完整 TaskReceipt，用户主树与远端不被修改；一次失败后合格修复仍可完成并保留失败记录
