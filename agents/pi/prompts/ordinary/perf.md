---
description: Performance analysis - profile, identify hot path, propose fix
argument-hint: "<area or symptom>"
---


Performance investigation: **$@**

## Method

1. **Measure first**. If there's no benchmark, write one. If there's no profile, capture one.
   - Use the project's existing tooling (bench fixtures, perf scripts).
   - Pick a representative workload, not a microbenchmark of one function.
2. **Identify hot path**. Top 5 functions by self time or allocations.
3. **Form a hypothesis** about *why* it's slow:
   - Algorithmic (O(n²) where O(n) is possible)?
   - I/O bound (N+1 queries, sync where async fits)?
   - Allocation churn (GC pressure, copies in a hot loop)?
   - Cache misses (random access, large struct, no batching)?
   - Lock contention?
4. **Confirm** by predicting an experiment outcome before running it.
5. **Propose** the smallest change that addresses the root cause.
6. **Re-measure**. Report:
   - Before: <metric>
   - After: <metric>
   - Improvement: <percent>
   - Trade-offs: <complexity / memory / readability cost>

## Rules

- Do not "optimize" without measuring — you'll guess wrong.
- Do not change algorithm AND data structure AND I/O strategy in one pass; isolate.
- Beware of microbenchmarks that don't represent real workload.
- Beware of constant-factor wins that complicate code without solving asymptotic problems.
- If the bottleneck is in a dependency, evaluate switching the dependency before contorting your code.


## 执行路由

由当前父 Pi 会话直接处理普通任务，遵循业务仓库规则、用户授权和已明确配置的流程。
先确认实际可用的读取、编辑、搜索、Shell 和验证能力；缺少能力或授权时报告具体限制，不能假定可调用未提供的入口。
普通动作不转交任务管理器或子代理。涉及写入、提交、发布或外部调用时遵循实际授权与受管工具审批，模板本身不授予权限。
保留他人的变更，核对最终 diff；分别报告实际结果、已运行检查和未验证事项，不用成功文字代替证据。
