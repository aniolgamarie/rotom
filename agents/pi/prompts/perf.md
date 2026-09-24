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

遵循当前 AGENTS.md 的模式约束：普通实施由父会话执行，具体变更由 fresh reviewer 审查；
managed 任务使用 kernel_task。明确的外部委托使用 model_delegate 的对应用途模板，
backend/model 与工作区必须明确；模板不授予写入或额外权限。分别报告结果和实际验证证据。
