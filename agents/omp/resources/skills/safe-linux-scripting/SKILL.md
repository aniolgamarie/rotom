---
name: safe-linux-scripting
description: Use for Linux shell scripts requiring safe quoting, error propagation, cleanup, dry-run behavior, portability, ShellCheck, or isolated tests.
---

# Safe Linux Scripting

Check:

- target shell and portability requirements;
- quoting, splitting, and glob expansion;
- pipeline exit behavior;
- traps and cleanup;
- temporary-file safety;
- idempotency;
- privilege escalation;
- destructive commands;
- dry-run behavior.

Do not use `sudo` in automated verification.

Run destructive tests only against isolated temporary fixtures.

Verification order:

1. parser check;
2. `shfmt -d`;
3. `shellcheck`;
4. Bats or isolated fixture tests;
5. dry-run for destructive paths;
6. final diff inspection.
