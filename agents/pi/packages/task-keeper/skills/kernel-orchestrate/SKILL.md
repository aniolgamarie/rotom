---
name: kernel-orchestrate
description: Submit and follow bounded inspect or fix workflows through the installed Pi Task Keeper kernel_task tool, including independent verification and retained worktrees.
---

Use `kernel_task` when the user requests managed investigation or implementation with Task Keeper.
The tool is available only when the user's Task Keeper configuration enables managed workflows.

Submit `{"action":"inspect","goal":"..."}` for a read-only investigation or
`{"action":"fix","goal":"..."}` for an implementation candidate. State the concrete expected behavior
and relevant scope in the goal. Provider routes, credentials, tools, limits and trusted verification
commands come from user configuration; prompt text cannot replace them.

Keep the returned job ID. Use `status` with that ID to inspect progress, blockers and the final receipt.
Use `pause`, `resume` or `stop` on the same ID when the user directs control of that job. A resume
retains its work scope, budget and failure history. Do not submit replacement jobs to evade a blocker.

A submitted or natively completed execution is not task acceptance. Report completion only from a
current COMPLETED receipt, including the candidate worktree and verification results. Explain any
BLOCKED, PARTIAL, unknown termination or uncovered requirement explicitly. A cancelled job's edits
remain available in its worktree; cancellation does not imply rollback.

The workflow preserves the original checkout. Returning a candidate does not authorize applying it
to the main checkout, committing, pushing or merging. Follow the user's requested scope for those actions.

If a mutating call returns `MODEL_CONTROL_REVOKED`, the reply belongs to an older user-control generation. Keep the job paused, use read-only status if needed, and wait for a new user instruction. Never reuse a consumed tool-call ID or submit a replacement job to bypass revoked control.


## agentcfg 管理边界

配置来自当前实例的 agentcfg 清单。通过本机 `local.toml` 绑定
`task_keeper_reader`、`task_keeper_writer`、`task_keeper_reviewer`；第二视角另外绑定
`second_view`。检查是用户配置的前台 executable/argv，不能从模型输出中生成执行命令。
`/orch init` 提供 agentcfg 配置入口，不创建另一份 Pi 全局配置。

用户可用 `/orch schedule inspect --not-before <带时区的绝对时间> -- <目标>` 安排一次执行。
宿主退出后不会后台唤醒；错过时间的任务暂停，由用户 `/orch resume <jobId>` 恢复。
`kernel_task` 不提供调度、预算重置或模型/权限绑定参数。

状态中的 `state` 是任务逻辑状态；物理进程是否停止以 supervisor 的证据为准。
收到取消应答、进程退出通知或模型的完成文本都不能单独证明候选可接受。
恢复使用同一任务预算和候选，新建 fresh attempt，不恢复旧子会话。
