---
description: Draft a pull request description from branch commits
argument-hint: "[base-branch]"
---


Draft a PR description comparing the current branch to **$1** (default `main` if empty).

## Steps

1. `git fetch origin` first.
2. `BASE=$(git rev-parse --abbrev-ref --symbolic-full-name @{upstream} 2>/dev/null || echo main)`
3. Inspect: `git log --oneline ${BASE:-main}..HEAD` and `git diff ${BASE:-main}...HEAD --stat`.
4. Group commits by intent (feature / fix / refactor / docs / test / chore).
5. Output the PR description in this exact shape:

```markdown
## Summary

<2-4 sentences: what changes, why, user impact>

## Changes

- **<area>**: <one-line change>
- **<area>**: <one-line change>

## How to Verify

- [ ] <reviewer step 1>
- [ ] <reviewer step 2>

## Risks

<edge cases, known limitations, follow-ups deferred>

## Related

<links: issues, design docs, related PRs — do not invent>
```

## Rules

- "Summary" is the only required section.
- Do not list every commit; consolidate by topic.
- Risks section is honest: empty section is allowed, fake reassurance is not.
- Do not push or open the PR unless I ask.


## 执行路由

由当前父 Pi 会话直接处理普通任务，遵循业务仓库规则、用户授权和已明确配置的流程。
先确认实际可用的读取、编辑、搜索、Shell 和验证能力；缺少能力或授权时报告具体限制，不能假定可调用未提供的入口。
普通动作不转交任务管理器或子代理。涉及写入、提交、发布或外部调用时遵循实际授权与受管工具审批，模板本身不授予权限。
保留他人的变更，核对最终 diff；分别报告实际结果、已运行检查和未验证事项，不用成功文字代替证据。
