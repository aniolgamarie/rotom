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

由当前父 Pi 会话直接处理普通任务，遵循业务仓库规则、用户授权和已明确配置的流程。
先确认实际可用的读取、编辑、搜索、Shell 和验证能力；缺少能力或授权时报告具体限制，不能假定可调用未提供的入口。
普通动作不转交任务管理器或子代理。涉及写入、提交、发布或外部调用时遵循实际授权与受管工具审批，模板本身不授予权限。
保留他人的变更，核对最终 diff；分别报告实际结果、已运行检查和未验证事项，不用成功文字代替证据。
