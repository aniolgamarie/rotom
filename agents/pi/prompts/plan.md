---
description: Create a detailed implementation plan before touching code
argument-hint: "<task-description>"
---


Create an implementation plan for: $@

## Plan Structure

### 1. Problem Statement

- What needs to be done?
- Why is it needed?
- What are the constraints?

### 2. Current State

- What exists now?
- What works well?
- What needs improvement?

### 3. Proposed Solution

- High-level approach
- Key decisions
- Alternatives considered

### 4. Implementation Steps

Break down into ordered steps:

```
Step 1: [Description]
  - Files to modify: [...]
  - Expected outcome: [...]
  - Verification: [...]

Step 2: [Description]
  ...

Step N: [Description]
  ...
```

### 5. Testing Strategy

- Test files to create/modify
- Test cases to cover
- Verification commands

### 6. Risks and Mitigations

- What could go wrong?
- How to handle issues?
- Rollback strategy

### 7. Estimated Effort

- Time estimate
- Complexity rating
- Dependencies

## Output Format

Write the plan to `.planning/<task-name>.md`:

```markdown
# Implementation Plan: <task-name>

## Problem Statement
[What and why]

## Current State
[Current situation]

## Proposed Solution
[Approach]

## Implementation Steps

### Step 1: [Name]
- Files: [...]
- Changes: [...]
- Verification: [...]

### Step 2: ...

## Testing Strategy
[Tests]

## Risks
[Risks and mitigations]

## Effort
[Estimate]
```

## 执行路由

遵循当前 AGENTS.md 的模式约束：普通实施由父会话执行，具体变更由 fresh reviewer 审查；
managed 任务使用 kernel_task。明确的外部委托使用 model_delegate 的对应用途模板，
backend/model 与工作区必须明确；模板不授予写入或额外权限。分别报告结果和实际验证证据。
