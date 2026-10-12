---
description: Create a well-structured git commit with conventional commit format
argument-hint: "[message]"
---


Create a commit for the staged changes.

$@

## Process

### 1. Review Changes

```bash
git diff --cached --stat
git diff --cached
```

### 2. Craft Commit Message

Use conventional commit format:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code refactor (no feature/fix)
- `docs`: Documentation
- `style`: Formatting (no code change)
- `test`: Adding tests
- `chore`: Maintenance

**Scopes:**
- Module name
- Component name
- Feature area

### 3. Commit

```bash
git commit -m "type(scope): description"
```

## Guidelines

- Atomic commit (one logical change)
- Clear, descriptive message
- Reference issues/PRs if applicable
- No secrets or credentials

## Example Messages

```
feat(ai): add model switching command

Add /model command to switch between providers and models.
Supports Ctrl+P cycling through scoped models.

fix(state): correct state restoration on branch switch

State was not correctly restored when switching branches
in /tree view. Now properly reconstructs from session.

refactor(providers): simplify provider registration

Extract common logic into helper function. No behavior change.

docs(README): update installation instructions

Add note about --ignore-scripts flag.

test(state): add unit tests for state manager

Cover get, set, subscribe, and branch restoration.
```

## 执行路由

由当前父 Pi 会话直接处理普通任务，遵循业务仓库规则、用户授权和已明确配置的流程。
先确认实际可用的读取、编辑、搜索、Shell 和验证能力；缺少能力或授权时报告具体限制，不能假定可调用未提供的入口。
普通动作不转交任务管理器或子代理。涉及写入、提交、发布或外部调用时遵循实际授权与受管工具审批，模板本身不授予权限。
保留他人的变更，核对最终 diff；分别报告实际结果、已运行检查和未验证事项，不用成功文字代替证据。
