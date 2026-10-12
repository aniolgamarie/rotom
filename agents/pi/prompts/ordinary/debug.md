---
description: Debug the issue by following systematic debugging workflow
argument-hint: "<issue-description>"
---


Debug this issue: $@

## Systematic Debugging Process

### 1. Collect Information

- What is the expected behavior?
- What is the actual behavior?
- What are the error messages/logs?
- When did the problem start?
- What changed recently?

### 2. Determine Scope

- Which module?
- Which function?
- Which file?
- Which call path?

### 3. Simplify

- Create minimal reproduction
- Remove unrelated code
- Isolate the environment

### 4. Hypothesize and Verify

For each hypothesis:
- State the hypothesis clearly
- Design verification method
- Execute and record results

### 5. Identify Root Cause

Confirm the root cause with evidence:
- Code logic error
- Data issue
- Configuration issue
- Environment issue

### 6. Propose Fix

Based on root cause:
- What to modify?
- Why this modification?
- Any side effects?
- How to verify the fix?

## Output Format

After debugging:

```markdown
## Debugging Results

### Issue
[Issue description]

### Root Cause
[Root cause with evidence]

### Fix
[Fix proposal]

### Verification
[Steps to verify the fix works]
```

## 执行路由

由当前父 Pi 会话直接处理普通任务，遵循业务仓库规则、用户授权和已明确配置的流程。
先确认实际可用的读取、编辑、搜索、Shell 和验证能力；缺少能力或授权时报告具体限制，不能假定可调用未提供的入口。
普通动作不转交任务管理器或子代理。涉及写入、提交、发布或外部调用时遵循实际授权与受管工具审批，模板本身不授予权限。
保留他人的变更，核对最终 diff；分别报告实际结果、已运行检查和未验证事项，不用成功文字代替证据。
