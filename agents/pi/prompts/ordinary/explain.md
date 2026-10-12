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

由当前父 Pi 会话直接处理普通任务，遵循业务仓库规则、用户授权和已明确配置的流程。
先确认实际可用的读取、编辑、搜索、Shell 和验证能力；缺少能力或授权时报告具体限制，不能假定可调用未提供的入口。
普通动作不转交任务管理器或子代理。涉及写入、提交、发布或外部调用时遵循实际授权与受管工具审批，模板本身不授予权限。
保留他人的变更，核对最终 diff；分别报告实际结果、已运行检查和未验证事项，不用成功文字代替证据。
