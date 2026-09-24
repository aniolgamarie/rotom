---
description: Write tests for a module using the project's test framework
argument-hint: "<module-or-file>"
---


Write tests for **$1**.

## Workflow

1. **Locate** the module and its existing tests (`grep -r "$1" tests/ test/ __tests__/`).
2. **Identify** the test framework already used in this repo — do not introduce a new one.
3. **List untested behaviors** before writing code. Show me the list.
4. **Write tests one at a time**, following AAA (Arrange / Act / Assert):
   - Cover happy path, edge cases, and error branches.
   - One assertion concept per test.
   - Names describe behavior: `returns_X_when_Y`, not `test1`.
5. **Run after each new test** — confirm it fails for the right reason before implementing fixtures or mocks.
6. **Stop and ask** if coverage target is unclear (project default: 80% statement coverage).

## Constraints

- Do not modify production code to make tests easier — change the test instead.
- Do not mock what you can use real (in-memory DB, fake HTTP server, tmp dir).
- Do not write tests that pass without exercising the real code path.
- If a behavior is hard to test, surface the design smell — do not paper over it.


## 执行路由

遵循当前 AGENTS.md 的模式约束：普通实施由父会话执行，具体变更由 fresh reviewer 审查；
managed 任务使用 kernel_task。明确的外部委托使用 model_delegate 的对应用途模板，
backend/model 与工作区必须明确；模板不授予写入或额外权限。分别报告结果和实际验证证据。
