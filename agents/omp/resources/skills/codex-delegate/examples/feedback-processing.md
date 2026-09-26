# 示例：Feedback 处理与 Disposition 分配

## 场景

Codex 完成了上一轮的 investigate 委托，`final.md` 末尾包含 `pi-agent-feedback/v1` 块。Pi 需要处理 feedback 并决定如何向用户报告。

## Codex 返回的 Feedback

```json
{
  "schema": "pi-agent-feedback/v1",
  "artifact_id": "ctx-provider-reset-01",
  "delegation_id": "provider-reset",
  "turn": 1,
  "generated_at": "2026-07-20T10:28:00+08:00",
  "status": "completed",
  "confirmed_fact_ids": ["fact-1"],
  "invalidated_facts": [],
  "hypothesis_updates": [{
    "id": "hyp-1",
    "status": "supported",
    "reason": "Default initialization at lua/ai/init.lua:31 runs after state restore at lua/ai/state.lua:54, overwriting the saved selection",
    "evidence": ["lua/ai/init.lua:31", "lua/ai/state.lua:54"]
  }],
  "new_findings": [{
    "id": "finding-1",
    "claim": "Provider registration in providers.lua:72 calls state.set_default() which clobbers the restored value",
    "confidence": "high",
    "evidence": ["lua/ai/providers.lua:72", "lua/ai/init.lua:31"],
    "verification": "Traced setup order: init.lua calls providers.setup() after state.restore(), and providers.setup() calls state.set_default()"
  }],
  "remaining_questions": [
    "Should an unavailable saved provider fall back with a notification?"
  ],
  "recommended_follow_up": "Add a startup-order regression test before implementing the fix",
  "workspace_observed": {
    "head": "8b712f1",
    "dirty": true,
    "warnings": []
  }
}
```

## Pi 的处理过程

### Step 1: 检查 workspace 兼容性

```
feedback.workspace_observed.head = "8b712f1"
current HEAD = "8b712f1"  → 匹配 ✓
feedback.workspace_observed.dirty = true
artifact dirty = true  → 一致 ✓
```

→ 无 stale 问题，继续处理。

### Step 2: 逐条评估 claims

| Claim | 评估动作 | Disposition | 理由 |
|-------|---------|-------------|------|
| `confirmed_fact_ids: ["fact-1"]` | 检查 fact-1 的证据 | `verified` | Codex 独立确认了状态文件内容 |
| `hyp-1 → supported` | 读 `lua/ai/init.lua:31` 和 `lua/ai/state.lua:54` | `verified` | 确认 init.lua:31 在 state.lua:54 之后执行 |
| `finding-1` (high confidence) | 读 `lua/ai/providers.lua:72` | `verified` | 确认 `state.set_default()` 调用确实覆盖了恢复值 |
| `recommended_follow_up` | 不验证 | `provisional` | 建议性内容，不影响当前结论 |

### Step 3: 决定用户通知

- `hyp-1` 从 `open` → `supported`：这是 Pi 已呈现给用户的调查进展 → **告知用户**
- `finding-1` 是新发现，confidence high，已 verified → **告知用户**，附带证据
- `recommended_follow_up` 是建议 → 作为下一步建议呈现，不标记为事实

### Step 4: 向用户报告

```
Codex 调查完成。

根因定位：启动顺序问题
  providers.setup() 在 state.restore() 之后执行，
  其内部调用 state.set_default() 覆盖了恢复的 provider 选择。

证据：
  - lua/ai/init.lua:31 — setup 调用顺序
  - lua/ai/state.lua:54 — state restore 位置
  - lua/ai/providers.lua:72 — set_default() 覆盖点

建议下一步：先添加启动顺序的回归测试，再实现修复。
```

## 如果 invalidated_facts 非空

假设 Codex 说 `fact-1` 是错的（"状态文件实际上不包含 provider"）：

1. Pi 检查引用的证据位置
2. 如果 Pi 的证据仍然成立 → 标记 `disputed`，保留双方，告知用户存在分歧
3. 如果 Pi 发现自己的证据确实有误 → 标记 `verified`（Codex 对了），告知用户修正
4. 无论哪种情况，**不用未验证的 invalidation 静默替换 material fact**
