## ADDED Requirements

### Requirement: Preserved design and source traceability
实现 SHALL 以 v6、设计哲学 ADR 001–019 和 S1–S26 来源为可追溯参考；变更关键取舍 SHALL 记录依据、替代方案、适用边界与对应验收，不得以外部研究或 draft 自动证明产品能力。

#### Scenario: Implementation deviates from baseline
- **WHEN** adapter、恢复或验收实现改变 v6 的决策
- **THEN** 记录局部 ADR、触发证据和受影响测试，不无声降低原保证

### Requirement: Preserve all original fault specifications
系统 SHALL 保留 T01–T88 身份、原注入及期望，并增加 TK01–TK14；测试状态 MUST 区分 specified、executed、passed、failed 和 deferred，静态检查不能标运行通过。

#### Scenario: Proposal passes structural validation
- **WHEN** OpenSpec 和设计包静态验证通过但尚未运行故障测试
- **THEN** 运行故障保持未执行，报告不得宣传生产可靠性已验证

#### Scenario: Advisor remains deferred
- **WHEN** P0–P3 发布而 T66/T68/T69/T75 的在线 Advisor 场景尚不适用
- **THEN** 保留为 P4 明确延期，验证 Advisor 启用被拒绝，不删除原场景或宣称全部 88 项通过

### Requirement: Qwen recovery release acceptance
P1 SHALL 执行参数化 Qwen 长任务恢复验收，包括原生重试、长输入限流、工具修改后恢复、用户取消、重启和同额度池竞争；fake adapter/fake clock 故障注入与实际模型环境 smoke MUST 分别报告。

#### Scenario: No live Qwen binding available
- **WHEN** 本地未提供实测路线或账号引用
- **THEN** 通用开发与注入测试可继续，实际环境验收保持 pending，该路线不得标为已认证

#### Scenario: Controlled faults pass but live smoke fails
- **WHEN** 注入测试通过而绑定 Qwen 路线无法正常运行或恢复
- **THEN** P1 的该环境发布门槛未满足，保留失败事实，不用其他模型成功替代

#### Scenario: Live Qwen smoke never exercises recovery
- **WHEN** 实际 Qwen 仅完成正常请求，既无真实限流也无该 Pi/transport 路径的可验证受控限流注入
- **THEN** 只记录可用性通过，恢复认证仍 pending；不得通过密集请求耗尽真实账号额度来制造测试条件

#### Scenario: Controlled recovery with a live binding
- **WHEN** 显式验收 profile 在实际 Pi/transport 路径注入一次限流，随后绑定 Qwen 服务完整执行原任务
- **THEN** 分别记录 injected 与 service-origin 事件、请求/副作用计数、会话身份、等待及终态，并按该版本和 profile 认证，不推广到未测试组合

### Requirement: Capability specific stage gates
发布 SHALL 分 P0 事实、P1 同路线恢复、P2 多任务工作流、P3 严格多模型策略；每阶段 MUST 满足对应契约，未开放能力不得显示完整支持。

#### Scenario: P3 gate unavailable while P1 is certified
- **WHEN** 请求 gate 未满足，但非受保护 Qwen 同路线恢复已完成认证
- **THEN** 允许发布明确范围的 P1，严格自动备胎仍关闭，不让 P3 阻塞 P1

### Requirement: Safety and utility are evaluated separately
评测 SHALL 保留安全故障轨与 L1 决策/L2 片段/L3 完整任务效用轨，固定对照模型、工具及验收；按 issue/repository family 切分，所有启动任务、infra 失败及截止仍等待的任务 MUST 进入报告。

#### Scenario: Biased success report
- **WHEN** 报告排除 infra 失败、仅统计成功成本或混用近重复开发留出样本
- **THEN** 标记评测不合格或污染，不宣称端到端收益（T73、T74）

#### Scenario: Shadow suggestion has no executed outcome
- **WHEN** 未来 shadow 建议看起来优于规则但没有实际执行
- **THEN** 不宣称已证明 L2/L3 收益（T75）

### Requirement: Source compatibility is verified at point of use
实现依赖公开接口或研究代码时 SHALL 核对固定版本、必要行为与许可证责任，区分原设计引用与本次实测证据；本机环境 SHALL 仅作为参数化验收绑定。

#### Scenario: Reference version differs from chosen runtime
- **WHEN** 参考的执行器文档版本与计划安装版本不同
- **THEN** 对适配契约重测并记录差异，不按参考文章假定当前版本兼容

### Requirement: Complete scenario test obligations
每个当前 Requirement/Scenario 及原始 fault ID SHALL 有可追溯的测试义务，包含稳定身份、fixture/变体、独立断言、测试层级、责任阶段及执行状态；仅存在套件目录或自动生成映射 MUST NOT 被视为已实现或已通过。

#### Scenario: Specification changes without a reviewed test mapping
- **WHEN** 新增、删除或改变 Scenario 的 WHEN/THEN，而登记未同步 review
- **THEN** 完整性检查失败并定位缺口，不继续宣称计划完整

#### Scenario: One test claims multiple obligations
- **WHEN** 同一测试报告覆盖多个 Scenario 或 fault ID
- **THEN** 每项均有可核验断言和所需层级证据，否则未满足部分保持未覆盖

### Requirement: Independent test oracles at the required layer
测试 SHALL 使用与被测策略独立的预期和观测；请求硬上限 SHALL 核对接收端真实请求，持久化/跨进程/终止保证 SHALL 使用真实数据库及进程证据，MUST NOT 用 fake adapter 自述代替。

#### Scenario: Mock reports success while real action violates policy
- **WHEN** mock 声称预算未超或进程已停，但接收端多收到请求或 descendant 继续写入
- **THEN** 对应能力测试失败并保留证据，不接受 mock 结果覆盖实际动作

#### Scenario: Critical fact disappears before the parent model
- **WHEN** 原始事件和数据库含必需失败，但回执、父模型实际输入或 UI 漏掉阻塞语义
- **THEN** 传播验收失败，不能仅因 details 字段存在错误而通过

### Requirement: Decision boundary and temporal coverage
关键准入 SHALL 有全合法成功对照、每个独立拒绝条件单独失效、数值边界及事件时序测试；取消/发送、崩溃/预留、压缩/传播、writer/验证等关键交叉 SHALL 按显式切点复现。

#### Scenario: Test only rejects an input with all conditions invalid
- **WHEN** 测试只覆盖多个拒绝条件同时失败，未分别验证每个条件
- **THEN** 该决策的关键分支覆盖不合格，必须补单条件反例和全合法正例

#### Scenario: Replaying a failing interleaving
- **WHEN** 竞态或属性测试失败
- **THEN** 报告保存 seed、barrier/事件序列和工件，使失败可重放；不可只依赖随机 sleep 或重跑直到通过

### Requirement: Honest coverage and stage release reporting
报告 SHALL 分开计划、实现、执行和代码覆盖；发布 SHALL 要求当前能力范围的全部必需义务达到所需层级，MUST 单列缺绑定、跳过、失败、延期、未发现测试和过期认证。

#### Scenario: Zero tests or skipped checks exit successfully
- **WHEN** 测试命令退出 0 但测试发现数为零、required 被 skip，或只有静态校验结果
- **THEN** 不满足发布门槛，未执行项不得标 passed

#### Scenario: No runtime implementation exists
- **WHEN** 仅完成规范与测试计划
- **THEN** 仅报告计划登记的完整性，行/分支覆盖为 unavailable，运行用例仍未执行
