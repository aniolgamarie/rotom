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

遵循当前 AGENTS.md 的模式约束：普通实施由父会话执行，具体变更由 fresh reviewer 审查；
managed 任务使用 kernel_task。明确的外部委托使用 model_delegate 的对应用途模板，
backend/model 与工作区必须明确；模板不授予写入或额外权限。分别报告结果和实际验证证据。
