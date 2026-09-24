# review

Perform this purpose directly with the selected backend and granted tools. Do not delegate again.
The actual task follows separately; placeholders below describe the output outline, not missing user input.
Report evidence, coverage and uncertainty. Execution verification is not acceptance of findings.
When current web access is unavailable, identify that limitation and use only supplied or local sources.

## Prompt template

```markdown
Mode: review
Working directory: [cwd]
Scope: [files, diff, or design]
Task: Review the following from a independent perspective:

[Target: diff, code, or design]

Focus on:
- Correctness and potential bugs
- Edge cases and error handling
- Performance implications
- Security considerations
- Maintainability and clarity

Acceptance criteria:
- Specific findings with file:line references
- Severity levels (critical/warning/suggestion)
- Actionable recommendations
```

## Output shape

## Delegate Review

[Summary]

### Critical Issues
- [issue: file:line]

### Warnings
- [warning: file:line]

### Suggestions
- [suggestion: file:line]
