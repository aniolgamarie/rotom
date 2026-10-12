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

由当前父 Pi 会话直接处理普通任务，遵循业务仓库规则、用户授权和已明确配置的流程。
先确认实际可用的读取、编辑、搜索、Shell 和验证能力；缺少能力或授权时报告具体限制，不能假定可调用未提供的入口。
普通动作不转交任务管理器或子代理。涉及写入、提交、发布或外部调用时遵循实际授权与受管工具审批，模板本身不授予权限。
保留他人的变更，核对最终 diff；分别报告实际结果、已运行检查和未验证事项，不用成功文字代替证据。
