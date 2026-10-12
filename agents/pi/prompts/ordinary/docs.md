---
description: Generate or update documentation for code
argument-hint: "<file-or-symbol>"
---


Write or update documentation for **$1**.

## Steps

1. **Read** the code. Do not document from filename guesses.
2. **Detect doc style**: project's existing docs (TSDoc/JSDoc/Sphinx/rustdoc/godoc/Markdown). Match it exactly.
3. **Write for the reader who will use this**, not the reader who reads it cover-to-cover:
   - **What it does** (one sentence)
   - **When to use it / when NOT to use it** (often more useful than what)
   - **Parameters / returns / errors** (every public param, every thrown error)
   - **Example** (real, runnable, copy-pasteable)
4. **Skip the obvious**. If the name says it, don't repeat in prose.
5. **Mark stability** if applicable: `@experimental`, `@deprecated`, internal-only.

## Rules

- Do not invent behavior. If something is unclear from the code, **ask** or **read more** — do not guess.
- Examples must be runnable. Don't write `// ... rest of code` placeholders.
- Don't use marketing language ("powerful", "robust", "elegant"). State facts.
- Don't document what changed in this version — that's the changelog's job.
- Update related docs (README sections, CHANGELOG, type-doc index) if behavior changed.


## 执行路由

由当前父 Pi 会话直接处理普通任务，遵循业务仓库规则、用户授权和已明确配置的流程。
先确认实际可用的读取、编辑、搜索、Shell 和验证能力；缺少能力或授权时报告具体限制，不能假定可调用未提供的入口。
普通动作不转交任务管理器或子代理。涉及写入、提交、发布或外部调用时遵循实际授权与受管工具审批，模板本身不授予权限。
保留他人的变更，核对最终 diff；分别报告实际结果、已运行检查和未验证事项，不用成功文字代替证据。
