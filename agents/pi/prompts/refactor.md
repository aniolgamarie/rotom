---
description: Refactor the code module for better maintainability
argument-hint: "<module>"
---


Refactor $1:

## Goals

- Remove duplication
- Simplify logic
- Improve naming
- Add type annotations
- Reduce coupling

## Steps

1. Analyze current structure
2. Identify refactoring opportunities
3. Apply changes incrementally
4. Verify with tests
5. Update documentation

## 执行路由

遵循当前 AGENTS.md 的模式约束：普通实施由父会话执行，具体变更由 fresh reviewer 审查；
managed 任务使用 kernel_task。明确的外部委托使用 model_delegate 的对应用途模板，
backend/model 与工作区必须明确；模板不授予写入或额外权限。分别报告结果和实际验证证据。
