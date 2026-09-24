## ADDED Requirements

### Requirement: Qwen long task recovery is a first release criterion
系统 SHALL 在 P1 提供 Qwen 长任务同路线限流恢复；模型与承载服务由验收配置绑定，MUST NOT 以跨模型兜底尚未实现为由推迟该能力。

#### Scenario: Long Qwen task hits rate limit after tool use
- **WHEN** 已绑定 Qwen 路线执行长上下文任务，工具产生修改后收到临时限流
- **THEN** 保留现场、任务与上下文，通过认证 continuation 恢复，不重放整项任务，不重复已完成写入（TK09）

#### Scenario: Same family through different services
- **WHEN** 两个 Qwen fixture 使用不同 provider 名称和不同结构化限流响应
- **THEN** 分类适配器归一化事实后使用相同核心恢复机制，无模型名分支（TK10）

### Requirement: Evidence based error classification
系统 SHALL 区分短时频率、资源压力、窗口配额、网络过载、认证计费政策、上下文合约和未知执行错误；分类器 MUST 保留原始 code、脱敏原因、notBefore 来源与不确定性。

#### Scenario: Resource usage pressure
- **WHEN** 响应匹配有证据支持的 usage allocated quota exceeded 分类 fixture
- **THEN** 按资源压力等待，不假定月额度已耗尽（T20）

#### Scenario: Permanent or non quota error
- **WHEN** 认证、计费、政策拒绝或上下文参数错误发生
- **THEN** 明确阻塞对应路线或请求修正，不进入无限配额重试，也不自动升级模型（T26）

#### Scenario: Network outage exhausts its finite policy
- **WHEN** 网络或服务过载重试达到配置的尝试或活动时间上限
- **THEN** 暂停并报告网络诊断，不转入临时配额专用的无限等待链尾

### Requirement: Settled continuation boundary
系统 SHALL 等待原生 retry、compaction 与 follow-up 结束，并在派发时重查 idle、队列、上下文变换活动、身份、epoch 和副作用；低层 agent_end MUST NOT 独立触发续跑。

#### Scenario: Native retry succeeds
- **WHEN** 首次 429 后原生短重试成功
- **THEN** 不产生额外外层 continuation（T18）

#### Scenario: More work exists after agent end
- **WHEN** agent_end 后仍有压缩、重试或排队消息
- **THEN** 等待已认证 settled 边界并再次检查，不与其并发恢复（T19）

### Requirement: Persistent cooldown and deadline
系统 SHALL 持久化 incident、notBefore、deadline、continuation identity 与退避状态；服务器限制和本地冷却取更晚时间，正向抖动 MUST NOT 提前许可。

#### Scenario: Retry after and window constraints
- **WHEN** 服务返回长 Retry-After 或明确小时、周、月 reset
- **THEN** 最早恢复不早于可信限制，不高频探测（T21）

#### Scenario: Restart or clock discontinuity
- **WHEN** 等待中重启、主机休眠或墙钟回退
- **THEN** 从记录恢复并对账，合并错过 tick；时间不确定时延后而非抢跑（T25、TK11、TK12）

#### Scenario: Recovery timestamp boundary
- **WHEN** 测试时钟依次到达 notBefore 前一刻、恰好到时和到时之后，且服务器与本地冷却不同
- **THEN** 较晚约束满足前零请求；到时后也只有通过身份、取消、队列与资源准入的一个请求可发送

#### Scenario: Forever wait meets a deadline
- **WHEN** 配置允许长期额度等待但原生 deadline 到达
- **THEN** 先遵守 deadline 与终止对账，不能以 forever 覆盖 timeout（T51）

#### Scenario: One recovery request hangs during unlimited quota wait
- **WHEN** 等待政策为 forever 而真实恢复请求超过有限 requestTimeout
- **THEN** 取消并核对终止/发送状态，未知保持预留，不允许单次请求无限占用或立即重复发送

### Requirement: Shared half open recovery permit
同一协调范围的 host/quotaGroup SHALL 只有一个 half-open 真实恢复许可，成功后渐进放行；无等待者 MUST 停止探测。

#### Scenario: Ten sessions wait for one quota group
- **WHEN** 十个同状态目录的父会话共享额度池且冷却到期
- **THEN** 仅一个取得恢复许可，其余保持等待，不同时发请求（T24）

#### Scenario: Recovery permit owner disappears
- **WHEN** half-open 持有者取消或失联
- **THEN** 确认未发送则释放许可，确认终态则结算，是否发送或终态未知则保留并对账，不只靠 lease 超时发第二个恢复请求

#### Scenario: Canary succeeds but real request fails
- **WHEN** 小输入探测成功而原长上下文请求仍限流
- **THEN** 保持同 incident 并延长等待，不清预算或放开全体（T22）

#### Scenario: Canary is explicitly enabled
- **WHEN** 配置启用轻量 canary
- **THEN** 探测不携带项目代码，计入相应请求政策，成功只作为恢复候选信号

#### Scenario: Successful HTTP status without completed stream
- **WHEN** HTTP 200 后流内错误或响应不完整
- **THEN** 不标恢复成功，不关闭 breaker（T23）

#### Scenario: Repeated quota failure eventually recovers
- **WHEN** 多轮临时限流后一个真实长请求完整成功，所有状态、预算和队列约束均满足
- **THEN** 原任务沿原生上下文继续并可完成，失败历史保留，无重复工具副作用；无等待者后停止探测并清理本 scope 的 timer/listener

### Requirement: Human control invalidates automation
真实人工输入 SHALL 撤销相应 scope 的后续自动权，stop SHALL 进入终止协议；内部可信控制消息与终端协议回应 MUST NOT 被误判人工输入，用户输入 MUST NOT 被吞掉。

#### Scenario: User interrupts an awaited callback
- **WHEN** 用户在 probe、模型切换或派发 await 期间输入或取消
- **THEN** 旧 epoch 回调不能继续派发，迟到成功仅记录证据（T35、T38）

#### Scenario: Internal message or session lifecycle change
- **WHEN** 收到内部恢复消息、终端协议回应，或发生 reload/fork/switch/shutdown
- **THEN** 前两者不自我取消，生命周期变化使旧 ctx/epoch/timer 失效（T36、T37）

### Requirement: Waiting does not reset task responsibility
配额等待 SHALL 保留 workScope、预算、原失败和工作区；MUST NOT 消耗语义修复次数或盲重放未知 continuation。释放执行槽前 SHALL 确认原执行结束。

#### Scenario: Acknowledgement lost during recovery
- **WHEN** continuation 可能已发送但回执丢失
- **THEN** 按 intent 对账，未知则阻塞，不再次发送相同恢复（T40）

#### Scenario: Independent job can continue
- **WHEN** 一个 job 等待额度而另一个 job 的路线及资源独立可用
- **THEN** 前者保留等待，后者继续调度；前者未知 writer 仍保留写占用（TK13）
