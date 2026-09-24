# scout

Perform this purpose directly with the selected backend and granted tools. Do not delegate again.
The actual task follows separately; placeholders below describe the output outline, not missing user input.
Report evidence, coverage and uncertainty. Execution verification is not acceptance of findings.
When current web access is unavailable, identify that limitation and use only supplied or local sources.

## Prompt template

```markdown
Mode: investigate
Working directory: [cwd]
Scope: [target area]
Task: Perform fast codebase recon on:

[Target description]

Return compressed context including:
- Key files and their roles
- Important patterns and conventions
- Dependencies and integrations
- Potential gotchas

Acceptance criteria:
- Concise, actionable context
- File paths with line ranges where relevant
- Clear summary of the area
```

## Output shape

## Delegate Scout Report

[Compressed context summary]

### Key Files
- [file: role]

### Patterns
- [pattern: usage]

### Gotchas
- [gotcha: impact]
