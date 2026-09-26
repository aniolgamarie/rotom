# 示例：在调用 agent 的输出中汇报长任务进度

## 用户请求

```text
用 codex 调查并修复登录刷新后的偶发 401；任务较长时定期告诉我进行到哪一步。
```

调用 agent 为 Codex 准备有界 prompt，并选择 observable 模式。实现任务仍在隔离 worktree 中运行。宿主若支持后台 agent/task，优先让专门的 controller task 持有下面的 CLI 会话并把有用进度发回父 agent。

## 启动

```bash
"$RUNNER" start --observe \
  --cwd "$WORKTREE" \
  --prompt-file "$PROMPT_FILE" \
  --sandbox workspace-write \
  --allow-workspace-write \
  --worktree-root "$WORKTREE" \
  --heartbeat-seconds 60
```

stdout 的每一行都是完整、有界 JSON。由于启动事件可能与紧随其后的阶段事件合并，首个实际输出不保证只包含 `started`；调用方应以 `runId`、cursor 和 `.report` 为准。一个可能的首条记录是：

```json
{
  "operation": "observe",
  "runId": "run-Ab12Cd34",
  "state": "running",
  "nextCursor": 1,
  "report": {
    "recommended": true,
    "reason": "started",
    "text": "Codex delegation started."
  }
}
```

该 summary 只来自 Codex 明确输出的安全单行：

```text
CODEX_PROGRESS: Investigation completed: refresh-token rotation races with cache replacement. Next: implementation.
```

普通 `agent_message`、原始错误、reasoning、代码块、diff 以及疑似凭据不会进入可见进度。

调用 agent 立即向用户确认：

```text
已将任务委托给 Codex，运行 ID：run-Ab12Cd34。
```

## 阶段 checkpoint

observe 流返回 checkpoint：

```json
{
  "events": [
    {
      "seq": 4,
      "kind": "checkpoint",
      "phase": "implementing",
      "summary": "Investigation completed: refresh-token rotation races with cache replacement. Next: implementation."
    }
  ],
  "nextCursor": 4,
  "hasMore": false
}
```

调用 agent 汇报可验证结论：

```text
Codex 进度 · 调研完成
已定位 refresh-token rotation 与缓存替换的竞态；正在进入实现阶段。
```

不输出 reasoning、完整 diff 或完整命令日志。

## 安静期 heartbeat

如果长时间没有新事件，observe 默认最多每 60 秒输出一次 heartbeat：

```json
{
  "state": "running",
  "phase": "verifying",
  "events": [],
  "nextCursor": 8,
  "report": {
    "recommended": true,
    "reason": "heartbeat",
    "text": "Codex is verifying; elapsed 92s; last activity 18s ago."
  }
}
```

调用 agent 最多每 60 秒向用户汇报一次不变 heartbeat：

```text
Codex 仍在验证，已运行 1 分 32 秒；18 秒前仍有活动。
```

heartbeat 不推进 cursor。

## Warning 与取消

如果返回 `warning` 或 `orphaned`，调用 agent立即说明状态，但不能把它说成失败或成功：

```text
Codex supervisor 已停止，但没有终态 receipt；当前结果未知，暂不启动第二个 writer。
```

父 agent 或 controller 收到用户取消请求时：

```bash
"$RUNNER" cancel --run-id run-Ab12Cd34
```

只有拿到 `cancelled` terminal receipt 并确认 `processGroupStopped: true` 后，才能安全决定是否恢复。

## 显式恢复

```bash
"$RUNNER" resume --run-id run-Ab12Cd34 --observe \
  --prompt-file "$FOLLOW_UP_FILE" \
  --heartbeat-seconds 60
```

恢复返回新的 `runId`，例如 `run-Ef56Gh78`，并在 marker 中记录：

```json
{
  "resumedFromRunId": "run-Ab12Cd34"
}
```

不使用 `--last`，也不复用旧 run ID。

## 最终结果

终态 observe 记录：

```json
{
  "state": "completed",
  "terminal": true,
  "report": {
    "recommended": true,
    "reason": "terminal",
    "text": "Codex completed after 186s."
  },
  "artifacts": {
    "statusPath": ".../status.json",
    "finalMessagePath": ".../final.md"
  }
}
```

调用 agent 读取 `status.json` 和 `final.md`，检查 Codex diff 并独立运行验证，然后再向用户报告完成。状态栏和 MCP server 都不是此流程的依赖。

如果 detached 启动返回 `start_unknown`，不得直接重试；保留 `runId` 并先调用 `status`。默认调用会传 `--ignore-user-config`，只有任务确实依赖用户 Codex 配置时才显式添加 `--inherit-user-config`。

## Detached 兼容路径

只有宿主确认会保留后台子进程时，才把启动改为 `start --detach`，随后使用 `poll --run-id ... --after ...`。两条路径共享同一进度 schema。会清理 descendant 的 agent 工具必须使用 controller task 或可恢复的前台 observe session。
