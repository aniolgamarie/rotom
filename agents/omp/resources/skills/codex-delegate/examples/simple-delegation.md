# 示例 1：有界只读委托

## 用户请求

```text
用 codex review 当前 JWT 登录改动，只看 src/auth.ts 和 tests/auth_spec.ts。
```

## 调用 agent 准备的 prompt

```text
Mode: review
Working directory: /repo
Scope: src/auth.ts, tests/auth_spec.ts, diff:HEAD
Task: 审查 JWT 登录改动的正确性和安全风险
Acceptance criteria: findings 按严重度排序，包含文件/行号和最小修复建议
Constraints:
- 只读，不修改文件
- 不创建 workflow/plan/TODO，不继续委托
- 不粘贴完整文件或原始 diff
- 最终回复小于 4 KiB
Output: status, findings, verification, unresolved risks
```

这里只发送 cwd 和代码指针；Codex 从工作目录读取实际内容。

## 短任务的阻塞 CLI 示例

```bash
"$RUNNER" start \
  --cwd /repo \
  --prompt-file "$PROMPT_FILE" \
  --sandbox read-only \
  --approval-policy never
```

调用 agent 检查终态 receipt，并从 `finalMessagePath` 读取有界结果。需要语义 follow-up 时保存 receipt 中的明确 `threadId`，不使用隐式 last session。

这个阻塞调用只用于明确的短任务。预计超过一分钟时，改用
[`observable-progress.md`](observable-progress.md) 中的 controller task、前台 observe 或 detached poll 流程。

## 返回用户

先独立验证 Codex 的关键 finding，再返回按严重度排序的问题、短摘要和实际可得的使用信息。Codex 输出是 review 证据之一，不自动等于最终结论。
