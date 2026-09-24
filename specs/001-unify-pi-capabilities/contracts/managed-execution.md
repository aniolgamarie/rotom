# Managed Execution Bridge v1

## 1. 版本与所有者

协议名 `agentcfg-managed-executor-v1`，消息通道使用 `agentcfg:subagents:managed:*`。
每个实例只有一个活动 AgentManager；worker 内没有 AgentManager，也不自动加载父插件。
全部消息 closed schema、snake_case、UTF-8；未知字段/版本、缺字段或多监听者直接失败。
这些接口是要实现的 vendor 补丁，不是声称上游原包已提供。

## 2. 操作

| 操作 | 请求 | 返回与不变量 |
|---|---|---|
| handshake | protocol_version、instance_id、request_id | manager_activation_id、owner_nonce、runtime_identity、capabilities；只接受一个匹配响应 |
| preflight | 受管描述符、request_id | 已解析角色/模型/工具/路径摘要与 admission_token；不能执行模型或脚本 |
| dispatch | 描述符、admission_token、idempotency_key | attempt_id、manager_run_id、lease_id；相同键相同内容返回原运行，否则拒绝 |
| inspect | owner、manager_run_id | 持久 state、last_sequence、active_work、观察时间；不依赖 UI record |
| get_result | owner、attempt_id | 不可变 receipt 与 artifact 引用；未就绪/缺失明确错误，不返回旧结果 |
| cancel | owner、attempt_id、reason | accepted/已处理；仅表示撤销和停止请求已接受 |
| reconcile | 当前监督者认证、lease_id、历史owner引用 | 仅核对旧记录与进程身份；无证据时仍unknown |
| consume | owner、receipt_id、receipt_digest | 幂等确认 Task Keeper 已接管；允许清理 manager 镜像但不删除权威证据 |
| recover_stop | 已认证新监督者、lease_id、plan_digest、用户stop请求 | 仅撤销/停止已核实归属的旧执行，不授予旧任务继续执行权限 |

owner 固定展开为 instance_id、manager_activation_id、owner_nonce，不接受任意身份字典。
Task Keeper 在发送前持久分配 attempt_id；manager 原样确认，首次 continuation_of=null。

监督者重启后的reconcile为独立恢复操作：新supervisor先验证同实例所有权和私人控制通道，
从受保护持久记录读取旧owner，不接受调用方提交任意旧nonce认领。
它可以只读核对旧runtime、进程启动身份、外部工作和终止证据；旧nonce不能用于新dispatch/cancel，
新激活不能自动转移授权或释放旧lease。仅证明从未启动或完整终止才能解除保护，其他情况保持unknown。
对仍活跃的旧执行，普通reconcile不能隐式终止。旧supervisor已证实失效时，用户可通过独立
recover_stop取得仅停止授权；核验计划、进程身份、撤销generation及终止后的释放规则见
[控制恢复与工作区契约](recovery-and-workspaces.md)。旧nonce仍不可用于新dispatch/cancel。

普通 Agent RPC 不接受管理字段，也不能指定受管角色或将其改为 session executor。
禁止 bypassQueue、未知角色 fallback、模糊模型选择、未经声明的 configCwd/session 覆盖。

## 3. 描述符与事件

请求描述符必须包含：

- 协议与所有者：protocol_version、request_id、instance_id、manager_activation_id、owner_nonce。
- 任务身份：task_id、step_id、attempt_id、continuation_of、budget_scope_id。
- 内容身份：role_id、role_digest、runtime_digest、policy_digest、candidate_id、snapshot_digest。
- 执行范围：cwd、source_cwd、allowed_tools、read_roots、write_roots、inherited_denials、
  context_mode=fresh、nested=false、executor=managed-process。
- 模型路线：provider_id、model_id、model_digest、route_id、thinking。
- 准入：request_ceiling、turn_ceiling、deadline、可选 token/cost 限额、result_schema_digest、allowed_artifact_ids。
- 写入：workspace_write_lease_ids、workspace_identity_digest、grant_generation、allocation_id；reader可为空数组，
  writer/可写检查必须先取得跨实例工作区准入，包含descriptor/admission复核。

描述符不存储秘密值；child grant 只指向启动时安全提供的有限凭据。
preflight 对实际资源、模型、路径和 provider transport 进行 capability 检查，admission_token
绑定描述符摘要、runtime/slice/policy 身份、deadline 与 manager 激活；
启动前必须再次复核，过期/策略/运行包变更返回冲突。

事件包含 task_id/step_id/attempt_id/manager_run_id、producer_id、sequence、event_id、
phase、request_id/ordinal（如适用）、usage_id、process_identity、active_tool_ids、external_work_ids、
candidate_digest、result_digest、termination_confirmed。
事件按 producer 单调递增、按 event_id 去重；检测序列缺口，不能据缺失尾事件报告成功。

## 4. 角色权限

| 角色 | 工具 | 允许写入 |
|---|---|---|
| task-keeper-reader | tk_read/tk_find/tk_grep/tk_ls、受控结果提交 | 无项目写入 |
| task-keeper-reviewer | 同上，显式当前候选与证据 | 无项目写入 |
| task-keeper-writer | 同上加 tk_write/tk_edit | 当前候选允许根，排除 .git/原 checkout/秘密 |

无任意 shell、MCP、spawn、nested、全局技能自动发现。项目真实检查通过 supervisor 的
可信 CheckBinding 执行，不由模型直接构造 shell。动态工具注册不能扩大有效集合。
父拒绝规则按 [Permission Policy v1](permission-policy.md) 转换并与角色/task上限取交集；
使用规定的file/command闭合字段、exact/subtree和拒绝优先，不支持regex/glob等输入时拒绝准入。
本桥接固定execution_mode=managed，不能改为ordinary；普通会话使用独立OperationGrant且不进入此桥接。
普通 `/yolo` 或其他权限覆盖不能修改硬拒绝、角色上限与任务 grant。
写入还必须获得 [WorkspaceWriteLease](recovery-and-workspaces.md)，普通编辑、model-delegate、
Task Keeper及可写检查不能通过不同profile或路径别名并行写同一worktree。

## 5. 模型请求准入

1. Task Keeper 在原任务账本中原子 reserve；同 request_id 重复调用不能再次发送。
2. 每次实际 transport.send 前再核对 owner、grant、撤销状态、deadline、模型路线与可用额度。
3. 原生重试/自动恢复在 managed worker 关闭。重试由 Task Keeper 建新请求/尝试，仍计原预算。
4. 限流等待不算新请求；真正重发才计新网络尝试。语义轮次与网络尝试分开统计。
5. second_view、schema 修复、压缩、handoff、旁路问答、父辅助请求均有 reason 且同样准入。
6. 代理必须在门控 transport 内组合，不允许插件事后替换 fetch 绕开 gate。
7. 发送与否未知时 reservation 保守保留；不以错误回调当作未发送退款。
8. 硬 token/费用上限要求可计算的保守输入和最大输出预留，未知上界则拒绝配置；
   普通只统计未知费用时使用 null，不伪造零费用。

首个必需受管 transport 为 openai-completions（direct 与显式 proxy 各有证据）；
其他 provider 可以用于普通会话，选择到 managed 时必须有同等级 transport 认证，否则预检失败。
Cursor/Bun与model-delegate外部Pi/Codex委托不属于首个受管transport，不能自动作为故障切换目标。
model_delegate在managed上下文缺少受管认证时必须执行前拒绝，不把另一CLI进程当作可绕过门控的helper。
ordinary调用统一由同一manager的external executor与实例supervisor管理，无第二个调度者。

## 6. 状态、停止与恢复

逻辑任务状态为 queued/running/waiting/paused/blocked/completed/failed/canceled；
物理 execution lease 状态独立，见 [数据模型](../data-model.md)。

- cancel_requested、execution_settled、process_terminated、resources_reclaimed 必须分别记录。
- 用户停止后先 revoke grant，阻止下一次工具/模型请求，再停止本次所有受控进程并核对外部工作。
- 父 Pi 退出、worker 不响应、PID 复用或外部工作残留均不能假报 reclaimed。
- 默认恢复为同 task 的 fresh attempt，保留 continuation_of、candidate 和 budget；
  不透明的旧 session resume 不作为受管恢复机制。
- 统计分组不能改变 budget_scope_id；配置切换不能伪造旧执行已结束。
- 一次性调度用 schedule_id/task_id 幂等键，原子 admitted_at；重启错过时间为 paused-missed。
  管理者内建 scheduling/workflows/nesting 关闭；不承诺后台守护唤醒。

## 7. 结果接受与第二视角

成功必须同时满足：本次身份、当前候选摘要、非空结构化结果、完整事件、实际终态、
所有必要检查、required review、要求的 second_view 及终止/资源清零证据。
changed candidate 使旧检查和审查失效；第二视角最多按配置有界重试，不能自动合并源 checkout。

受管结果完成后先持久化，再通知 Task Keeper；通知不触发额外父模型轮次。
get_result/consume 幂等；manager GC 不得删除尚未 consume 的 receipt。
模型输出声称“通过”不替代真实检查；空 completed、旧证据、超时 partial、错误模型与缺失事件一律不接受。

## 8. 错误契约

稳定错误码包括 PROTOCOL_MISMATCH、MANAGER_IDENTITY_CONFLICT、ROLE_CONFLICT、
UNBOUND_MODEL、UNSUPPORTED_TRANSPORT、PERMISSION_UNREPRESENTABLE、BUDGET_EXHAUSTED、
ADMISSION_STALE、DISPATCH_CONFLICT、TERMINATION_UNKNOWN、EVIDENCE_MISSING、SNAPSHOT_STALE、
WORKSPACE_BUSY、RECOVERY_OWNER_ALIVE、RECOVERY_PLAN_STALE、RECOVERY_IDENTITY_UNKNOWN。
不含原始请求/秘密/模型响应；私人详细定位使用 location_id。
映射管理器 CLI：配置 2、秘密 3、活动/冲突/未知终止 4、运行包/认证能力缺失 5、IO 6。

### 同进程资源记录

内部 executor 的 `resource` 类别管理宿主内 HTTP 请求、回调监听器、后台抓取，以及经专用准入登记的长期 MCP stdio 服务；
它复用唯一 AgentManager，不另建管理者，也不占用两个实际执行槽位。活动资源最多 16 个，
取消请求、关闭未知和未消费结果仍阻止会话变更及记录清理。该类别不是 worker 协议的新执行后端，
不得用它发起未受监督的子进程。MCP stdio 仍使用同一 supervisor 的进程租约、权限、输出与终止证明；监督者另限最多 16 个服务，公开 allocate 不能自行声明服务分类。session、managed-process 和短期 external 任务继续共用执行上限 2。
明确的 external IO 可以标记 `activity=io`；session/managed-process 不允许用该标签绕过模型 helper 限制。

普通 Web 辅助模型的内部 `service_owner_run_id` 必须指向本 manager 内仍运行的 resource。
它只用于允许所属操作已有 HTTP/文件 IO 继续，不产生嵌套 agent，不减少模型任务计数；
其他操作、managed/session、取消待确认和未知执行继续阻断。该字段不是公开 RPC 参数。
