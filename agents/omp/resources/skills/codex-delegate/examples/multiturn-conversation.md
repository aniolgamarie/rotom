# 示例 2：明确 threadId 的多轮调查

## 第一轮

用户：

```text
用 codex investigate 为什么登录刷新后偶发 401，只读分析。
```

调用 agent 使用前台 observe；也可以把这个 CLI 会话交给专门的 controller task：

```bash
"$RUNNER" start --observe \
  --cwd /repo \
  --prompt-file "$INVESTIGATION_PROMPT" \
  --sandbox read-only
```

终态 receipt 假设包含：

```json
{
  "threadId": "019abcde-1234-7890-abcd-0123456789ab",
  "status": "completed",
  "finalMessagePath": ".../final.md"
}
```

调用 agent 保存明确 `threadId`，并从 `final.md` 读取“最可能的竞态位于 src/auth.ts:84 ...”等结论。

## 第二轮

用户：

```text
继续让 codex 验证这个竞态能否由现有测试稳定复现。
```

调用 agent 必须把上一步的明确 ID 传给 runner：

```bash
THREAD_ID="019abcde-1234-7890-abcd-0123456789ab"
"$RUNNER" resume --thread-id "$THREAD_ID" --observe \
  --prompt-file "$FOLLOW_UP_PROMPT" \
  --sandbox read-only
```

## 超时后的规则

- 调用宿主停止等待只说明 controller/exec session 中断，不能证明任务失败或成功。
- CLI receipt 为 `resumable_timeout` 时，优先使用验证过的旧 `runId` 执行 `resume --run-id ...`。
- 永远不使用 `codex exec resume --last`；并行窗口可能选错会话。
- 实现任务超时后不能立即新启第二个 writer，必须先确认旧进程已停止。
