---
description: Explain the code module in detail with examples
argument-hint: "<module-or-file>"
---


Explain this code in detail: $@

## Explanation Structure

### 1. Overview

- What is this module?
- What problem does it solve?
- Where is it used?

### 2. Public API

List all exported functions with:
- Function signature
- Parameter descriptions
- Return value
- Example usage

### 3. Key Concepts

- Core algorithms
- Design patterns
- Data structures
- Dependencies

### 4. Code Walkthrough

Walk through important functions:
- Input processing
- Core logic
- Output generation
- Error handling

### 5. Examples

Provide concrete examples:
- Basic usage
- Common patterns
- Edge cases

### 6. Gotchas

- Common mistakes
- Performance considerations
- Thread safety (if applicable)
- Breaking changes history

## Output Format

```markdown
## Module: <name>

### Overview
[Brief description]

### Public API

#### `function_name(param1, param2)`
- `param1` (type): Description
- `param2` (type): Description
- Returns: type - Description
- Example:
  ```lua
  local result = module.function_name(arg1, arg2)
  ```

### Key Concepts
[Concepts and patterns]

### Examples
[Concrete examples]

### Gotchas
[Common issues]
```

## 执行路由

遵循当前 AGENTS.md 的模式约束：普通实施由父会话执行，具体变更由 fresh reviewer 审查；
managed 任务使用 kernel_task。明确的外部委托使用 model_delegate 的对应用途模板，
backend/model 与工作区必须明确；模板不授予写入或额外权限。分别报告结果和实际验证证据。
