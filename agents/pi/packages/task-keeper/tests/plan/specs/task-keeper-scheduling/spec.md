## ADDED Requirements

### Requirement: Persistent multi job queue and stable responsibility
系统 SHALL 支持多个 job 排队与活动，采用 workScope/job/step/attempt/request 身份层级；同逻辑任务恢复 MUST 继承预算及验收归属。

#### Scenario: Parent resumes the same logical task
- **WHEN** session 恢复或 fork 后继续原任务
- **THEN** 关联已有 workScope，不通过新 job 自动清零计数（T30）

#### Scenario: Model tries to allocate a fresh budget scope
- **WHEN** 模型通过 kernel_task 拆分 job 并提交新 scope ID 或 reset 意图
- **THEN** 拒绝模型指定的预算身份，继承宿主绑定的现有 workScope；只有明确用户新目标或授权版本可增加范围

### Requirement: Dependency constrained readiness
系统 SHALL 仅调度依赖满足的 step，验证计划中依赖引用有效且无环；required 依赖失败 MUST 阻止依赖它的下游执行。

#### Scenario: Required predecessor fails
- **WHEN** 一个 required 验证失败而下游等待该结果
- **THEN** 下游保持阻塞，独立 step 可运行；不把前置进程退出当依赖成功（TK01）

#### Scenario: Invalid dependency plan
- **WHEN** 任务计划引用不存在步骤或形成环
- **THEN** 准入拒绝并说明依赖问题，不留永远等待的伪就绪任务（TK02）

#### Scenario: Dependencies become satisfied
- **WHEN** 上游返回符合约定的成功证据，或预设允许跳过的 optional 上游已明确跳过
- **THEN** 合法下游从阻塞变就绪且只派发一次；无此预设时 optional 失败也不能冒充依赖成功

### Requirement: Deterministic priority and bounded starvation
调度 SHALL 在同父队列使用有界基础优先级、持续 ready 时间 aging、readyAt 与稳定 ID 选择，不抢占正在执行的有界 step；公平策略 MUST 可配置并可重放，MUST NOT 将其宣称为跨父进程全局公平保证。

#### Scenario: High priority jobs keep arriving
- **WHEN** 低优先级任务持续 ready 且其资源持续可用，新高优先级任务不断进入
- **THEN** aging 使旧任务最终获得执行机会，选择原因可解释（TK03）

### Requirement: Atomic resource acquisition
派发 SHALL 在同一事务核对并预留所需执行槽、仓库、工作区、验证槽和额度许可；资源不足 MUST NOT 持有一部分新资源等待其他资源。

#### Scenario: Competing jobs need resources in reverse order
- **WHEN** 两个就绪任务同时竞争相同的两个资源
- **THEN** 至多一个完成整组预留，另一个不持局部新预留形成死锁（TK04）

#### Scenario: Contention resolves after confirmed release
- **WHEN** 获胜任务确认终止并释放资源，未取消的失败竞争者仍就绪
- **THEN** 后者可以获得许可继续，无泄漏槽位或负计数；未知终止不满足此释放条件

### Requirement: Shared write resource exclusion
写入归属 SHALL 按 canonical workspace 及声明共享可变资源协调，MUST NOT 仅按 job ID 限制 writer；源码验证冻结期间 MUST 排除新 writer。

#### Scenario: Different jobs share one workspace
- **WHEN** 两个 job 各自只有一个 writer，但指向同一真实目录或共享构建写目录
- **THEN** 不能同时获得冲突写入许可，别名路径解析为同一资源（TK05）

#### Scenario: Verification races with implementation
- **WHEN** VerifyRunner 正验证被冻结候选，另一个 step 请求修改该源码
- **THEN** writer 等待或按政策拒绝，不能产生表面属于同快照的并发验证（TK06）

### Requirement: Explicit host coordination scope
同一主机、同一规范化状态目录的父进程 SHALL 事务性共享宿主资源限制和额度恢复许可；不同目录 MUST 明示独立协调范围。父进程 MUST NOT 接管未确认终止的其他 owner 工作。

#### Scenario: Two processes compete for last slot
- **WHEN** 同状态目录的两个父进程同时申请最后一个活动槽
- **THEN** 只有一个成功，计数不超配置上限（TK07）

#### Scenario: Independent state roots
- **WHEN** 两个实例使用不同状态目录
- **THEN** doctor 标记其保证分别局限于该目录，不能声明共同宿主硬上限（TK08）

### Requirement: Wait and shutdown preserve occupied resources
系统 SHALL 分离执行槽、持续工作区、未结预算和未知写入占用；父退出后不调度，恢复 SHALL 先对账，不以 lease 到期释放未知 writer。

#### Scenario: Quota waiter has ended execution
- **WHEN** job 等待额度且原执行明确结束
- **THEN** 释放活动执行及 repository active-job 槽，保留持续工作区、必要写入归属、incident 和预算；独立工作区任务按配置继续

#### Scenario: Resource owner lease expires
- **WHEN** owner 失联但外部 mutator 的终止未知
- **THEN** 保留相关写占用并报告 unknown，不因 lease 超时启动替代 writer（TK14）
