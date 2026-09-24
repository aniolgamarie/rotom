## ADDED Requirements

### Requirement: Five dimensional evidence ledger
系统 SHALL 持久化 delivery/execution/contract/acceptance/observation，LLM 自述仅为 claims；事件 SHALL 有来源、运行身份、稳定 ID 和 producer sequence，重复事件 MUST 幂等，关键缺口 MUST 明示。

#### Scenario: Lost or duplicated event
- **WHEN** 完成通知重复、关键序列有洞或通知丢失
- **THEN** 去重或对账补投递，不重新执行；无法补齐关键证据则保持 unknown（T14、T15）

#### Scenario: Conflicting event identity
- **WHEN** 相同 producer/sequence 或 eventId 出现不同关键 payload
- **THEN** 记录证据冲突并阻塞依赖该事实的动作，不按普通重复事件静默覆盖

### Requirement: Immutable failure history and explicit resolution
失败 attempt SHALL 保持失败；工具与验证的必需失败 SHALL 通过引用后续合格结果或授权处置解除，不得因最终文字正常而消失。

#### Scenario: Recovered failure followed by valid completion
- **WHEN** 首次 attempt 失败，后续合法恢复产生满足 TaskSpec 的证据
- **THEN** job 可以完成，同时回执保留失败、恢复关系和实际路线（T05、T09）

### Requirement: Non suppressible packet facts
EvidencePacket SHALL 固定包含约束、未解决错误、未知 mutator、required 缺口、预算与来源；压缩和截断 MUST NOT 删除阻塞语义。

#### Scenario: Compact hides earlier failure
- **WHEN** 主上下文压缩或模型摘要遗漏必需失败
- **THEN** 下一受管决策重新从账本投影该失败，父模型和 UI 保留阻塞原因（T10、T11、T53、T57、T84）

#### Scenario: Packet cannot fit
- **WHEN** 必需硬状态超出配置上下文预算
- **THEN** 缩小任务或返回 PACKET_TOO_LARGE，允许带完整索引的分组摘要但禁止静默裁掉事实（T56）

### Requirement: Evidence references remain claims when appropriate
引用 SHALL 验证 job、快照、来源与范围；来源内容 MUST 按不可信数据处理，引用存在 MUST NOT 自动证明语义结论。

#### Scenario: Forged reference or instruction in logs
- **WHEN** 引用跨 job、不存在、范围非法，或日志要求重置预算
- **THEN** 拒绝引用或指令，保留原授权与 Outcome；worker 自述保持 claim（T54、T55、T58）

### Requirement: Two stage authorization and freshness
StepProposal SHALL 校验结构、引用和允许动作，派发前 SHALL 再核对 spec、snapshot、decisionRevision、ownerEpoch 和资源；阶段 MUST NOT 降低根验收。

#### Scenario: Stale proposal after code change
- **WHEN** 提议后源码、TaskSpec 或权限改变
- **THEN** 提议失效，重新投影与准入（T59、T62、T70）

#### Scenario: Resource observation changes only
- **WHEN** 仅心跳、费用或 reservation 更新而决策事实未变
- **THEN** 重新预算准入，仍合法则保留提议有效性，不机械重规划（T60、T85）

#### Scenario: Invalid action payload
- **WHEN** 建议给任意 shell、新 provider、非法 JSON 或重复 decision fingerprint
- **THEN** 拒绝或去重，不默认 advance，也不产生额外派发（T63–T65）

### Requirement: Independent task outcome and progress
OutcomeReducer SHALL 独立检查 required、当前快照、未授权变化、未知 mutator 和证据覆盖；ProgressReducer MUST NOT 改验收状态，request_finish MUST 仅触发检查。

#### Scenario: Native completed but tests missing
- **WHEN** native completed 或模型请求结束，但 required 测试或 reviewer 未完成
- **THEN** task 保持 blocked/待验收，UI 与父模型明确缺口（T03、T12、T61、T83）

#### Scenario: Optional task failure
- **WHEN** 预设 optional 调查失败且其余验收满足
- **THEN** 仅按 TaskSpec 允许的 PARTIAL 语义交付，披露缺口（T13）

#### Scenario: All acceptance conditions are satisfied
- **WHEN** 当前快照的 required 全部通过，无未解决必需失败、未授权变化或未知 mutator，观察覆盖完整
- **THEN** 生成 COMPLETED 回执与一致展示；逐项撤去任一必需条件时均不得完成，历史失败已被明确恢复则不永久阻塞

### Requirement: Durable storage and artifact retention
系统 SHALL 在派发前保证关键记录可持久化，在原生工件清理前固定必需内容；数据库迁移 MUST 保留 intent、unknown 和未结预算。

#### Scenario: Storage failure or incompatible rollback
- **WHEN** 磁盘满、数据库损坏、工件缺失或回退读不懂新 schema
- **THEN** 阻止依赖动作，保留可恢复状态，不清库或重置预算（T47、T76）
