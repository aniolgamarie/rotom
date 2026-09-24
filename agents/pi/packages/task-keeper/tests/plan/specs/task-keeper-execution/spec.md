## ADDED Requirements

### Requirement: Versioned adapter certification
执行适配器 SHALL 提供能力、preflight、start、observe、continue、cancel 和 reconcile 契约，按宿主/执行器版本、补丁、模式、profile、transport 与关键配置认证；未知能力 MUST NOT 被默认支持。

#### Scenario: Foreground support does not certify background
- **WHEN** foreground/fresh 组合通过而后台/fork 未测试
- **THEN** doctor 分别显示支持范围，后台/fork 依赖动作不可用（T48）

#### Scenario: Capability changes after upgrade
- **WHEN** 执行器或关键配置摘要改变
- **THEN** 原认证失效，重新验证前不继续依赖其保证的派发

### Requirement: Verified execution contract and reporter channel
适配器 SHALL 分别记录 requested/resolved/runtimeObserved 模型、thinking、工具、上下文及隔离；关键 reporter MUST 在执行开放前验证身份、通信与持久化通道。

#### Scenario: Registration without communication
- **WHEN** reporter 注册 ack 成功但事件无法写入或读回
- **THEN** 相关能力不可用，不将注册成功标为 ready（T06、T07）

#### Scenario: Silent launch contract downgrade
- **WHEN** required thinking 低于约定、fork 改 fresh 或隔离退回共享目录
- **THEN** 报告真实差异并阻止依赖动作，不用 requested 覆盖 observed（T04、T08、T17、T43）

### Requirement: Native acceptance is distinct from completion
适配器 SHALL 保留 accepted、started、nativeRunId、执行终态、interrupted、timeout、acceptance 及观测缺口，MUST NOT 仅凭 exitCode=0 或 completed 认定任务完成。

#### Scenario: Accepted child never starts
- **WHEN** spawn 已接受但 child 启动失败
- **THEN** 执行记录失败及原始原因，任务不能完成（T01）

#### Scenario: Interrupted process exits zero
- **WHEN** 原生结果同时包含 interrupted=true 与 exitCode=0
- **THEN** 保留中断，禁止转换为任务成功（T02）

#### Scenario: Healthy execution preserves observed facts
- **WHEN** 已认证 adapter 成功启动、持续上报并正常结束，实际配置满足请求
- **THEN** accepted、run identity、终态与原生工件正确关联，允许进入独立验收，不因非关键可选元数据缺失全局阻塞

### Requirement: Single control owner and durable dispatch intent
每次派发或 continuation SHALL 在事务中记录 intent、ownerEpoch、spec/snapshot 和幂等身份，事务外执行后记录 ack；同 scope MUST 只有一个恢复 owner，所有 await 后 MUST 重查控制权。

#### Scenario: Crash between spawn and acknowledgement
- **WHEN** spawn 可能成功而 ack 前崩溃
- **THEN** 重启对账原生身份，无法确定则 BLOCKED_UNKNOWN，不重新派发 writer（T39、T40、T71）

#### Scenario: Competing automatic controller
- **WHEN** 另一控制路径对同受管 scope 发自动 fallback 或续跑
- **THEN** 拒绝受管派发或先明确停用重复控制，不允许两者同时拥有执行权（T49）

### Requirement: Termination coverage controls resource release
取消 SHALL 先撤销派发权，再请求原生终止并观察相关进程及外部工作；lease 到期和 cancel ack MUST NOT 单独解除写入占用。

#### Scenario: Writer remains alive after owner loss
- **WHEN** owner lease 到期但旧 writer 仍可能写入
- **THEN** 保留写入资源与现场，禁止第二 writer，直到对账证明终止（T41、T42）

#### Scenario: Cancel outcome is unknown
- **WHEN** stop 已发出但执行器不能确认终止覆盖
- **THEN** 展示停止意图与 termination_unknown，阻止新执行，不伪称已完全取消

### Requirement: Bounded native execution and observable failures
每个自动执行 profile SHALL 提供有限模型轮次或等价活动上限、活动时间与工具 timeout；关键错误 MUST 在吞错前采集并透传，无法观察的路径 MUST 标不支持。

#### Scenario: Required failure swallowed by backend
- **WHEN** 后端 catch 丢失关键错误且外部无事实可重建
- **THEN** 认证失败，补接口或禁用路径，不用模型猜测补造（T52）

#### Scenario: Silent long build
- **WHEN** 构建无输出但进程存活且未超过工具策略期限
- **THEN** 记录静默活动而非仅凭无输出判断失败；超过绑定上限按终止协议处理（T16、T51）
