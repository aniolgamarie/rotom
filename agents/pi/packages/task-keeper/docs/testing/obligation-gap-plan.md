# 义务缺口处理计划

## 当前状态（基于 report.json 2026-09-10T01-18-04-512Z）

- Total missing: 106
- By category:
  - needs_impl_or_review: 5 (CFG-001:U, REC-012:U, VAL-001:U, T43:U, TK08:U)
  - needs_layer_check: 82
  - needs_live_binding: 6 (阻塞，需要Qwen binding)
  - needs_oracle: 7 (VAL-001:V, VAL-005:V, VAL-006:V, VAL-007:V, VAL-008:V, VAL-011:V, VAL-015:V)
  - not_in_handoff: 6 (T66:U, T66:V, T68:U, T68:V, T69:U, T69:V)

## 处理计划

### 1. not_in_handoff (6项)
这些义务不在交接文件§4表格中，需要：
- 检查是否需要实现测试文件 cases-g33-u.test.ts 和 cases-g33-v.test.ts
- 或者在其他测试文件中添加 evidence() 调用

### 2. needs_impl_or_review (5项)
需要实现生产规则接口或审查：
- CFG-001:U: tests/workflows-policy.test.ts；tests/workflows-recovery.test.ts
- REC-012:U: tests/cases-stream-terminals-s.test.ts；tests/cases-timeout-authority.test.ts
- VAL-001:U: 按coverage-cases.csv的production_targets定位
- T43:U: tests/workflows.test.ts；tests/workspace.test.ts
- TK08:U: tests/cases-coordination-status-s.test.ts；tests/cases-project-policy-e.test.ts

### 3. needs_oracle (7项)
需要添加V层级oracle：
- VAL-001:V, VAL-005:V, VAL-006:V, VAL-007:V, VAL-008:V, VAL-011:V, VAL-015:V
- 主要在 tests/gap-g30-v.test.ts 中

### 4. needs_layer_check (82项)
需要逐项核对层级/observer：
- 按工作包分组：W1: 22, W3: 18, W4: 22, W5: 20
- 需要检查每个义务的测试文件是否存在，是否有 evidence() 调用

### 5. needs_live_binding (6项)
阻塞：需要用户提供Qwen binding参数

## 优先级

1. not_in_handoff (6项) - 快速修复
2. needs_impl_or_review (5项) - 需要实现
3. needs_oracle (7项) - 需要实现
4. needs_layer_check (82项) - 大量工作
5. needs_live_binding (6项) - 阻塞

## 进度跟踪

- [ ] not_in_handoff: 0/6
- [ ] needs_impl_or_review: 0/5
- [ ] needs_oracle: 0/7
- [ ] needs_layer_check: 0/82
- [ ] needs_live_binding: 0/6 (阻塞)
