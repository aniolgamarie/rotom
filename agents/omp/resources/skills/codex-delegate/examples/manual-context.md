# 示例 3：手动范围与 pointer-first 上下文

## 用户请求

```text
委托给 codex review：src/auth.ts:10-50, tests/auth_spec.ts，只关注 token 过期处理。
```

## 范围解析

- `src/auth.ts:10-50`：主要实现范围；
- `tests/auth_spec.ts`：关联测试；
- 关注点：token 过期处理；
- 模式：`review`，因此 sandbox 为 `read-only`。

## Prompt

```text
Mode: review
Working directory: /repo
Scope: src/auth.ts:10-50, tests/auth_spec.ts
Task: 只审查 token 过期处理
Acceptance criteria: 指出可复现问题、文件/行号、缺失测试和最小修复方向
Constraints:
- 从 cwd 读取文件，不在 prompt 中复制完整源码
- 不检查无关目录，不修改文件
- 最终回复小于 4 KiB
Output: status, findings, verification, unresolved risks
```

## 调用

```bash
"$RUNNER" start --observe \
  --cwd /repo \
  --prompt-file "$PROMPT_FILE" \
  --sandbox read-only \
  --approval-policy never
```

手动模式控制 Codex 的检查范围，不代表调用 agent 要预先加载并粘贴这些文件。只有 cwd 外且无法读取的短信息才内嵌，并在发送前脱敏。

常见范围写法：

```text
src/api.ts,src/db.ts
src/legacy.ts:100-200
commit:abc123
diff:main...HEAD
```
