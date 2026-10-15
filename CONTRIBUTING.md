# Contributing

Rotom is a repository application, not a global agent installer. Changes should be narrow, reproducible, and explicit about their effects on configuration, credentials, dependencies, and native state.

## Development setup

```sh
uv sync --locked
.venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python scripts/check-public-docs.py
```

Python 3.11+ is required. The entry points use the prepared `.venv` directly. Default tests isolate HOME, DSH_HOME, and XDG paths, block network access, and use fake subprocesses and credentials. They must not launch third-party hosts or inspect real account state. See [testing](docs/testing.md) for separate native and live verification.

Read [AGENTS.md](AGENTS.md), the [constitution](.specify/memory/constitution.md), and the relevant adapter guide before changing implementation. Use double-quoted Python strings, two-space indentation, and focused tests for behavior that can fail. Follow existing comment conventions. Do not reformat unrelated files.

## Change requirements

1. Verify the actual branch, worktree, staged changes, and local instructions. Preserve other work, including uncommitted changes in other worktrees.
2. State the affected interface and ownership boundary. Unknown configuration fields must fail; unknown native fields must survive supported field merges.
3. Follow the [publication policy](docs/publication-policy.md) for code, documentation, commit messages, and reports. Use fictional credentials, reserved test addresses, and portable paths; retain required upstream attribution.
4. Use unmodified upstream hosts and public APIs. Record unsupported capabilities rather than patching host source, binaries, caches, or vendor copies.
5. Review dependency source, version, integrity, complete lock, licenses, and build inputs together. Normal sync and run must not update locks.
6. Apply the [merge gates](docs/worktrees.md) to every branch and worktree entering `main`. Run affected tests, inspect the stable final diff after writes finish, and record failures and untested scope. A native process returning zero alone is insufficient acceptance.

Use Conventional Commits, such as `fix(omp): preserve native role clearing`. Use only an explicitly approved public identity, including an approved noreply or bot identity. Configure `user.name`, `user.email`, and `user.useConfigOnly=true` locally in Git; never hardcode a person's name or address in shared rules. Before committing, compare the local configuration with both `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT`, including environment overrides. Both identities must match the approved identity. Do not inherit a global or automatically inferred identity. Keep private identifiers out of commit messages.

## Documentation and reports

English is authoritative. Use precise terms, copyable commands checked against `--help`, and relative links. Keep guides, reference, design explanations, and support claims separate. Translations should identify their source and scope. Avoid dated operational transcripts in public documentation; use a concise maintained issue or support summary.

Reports should contain the candidate commit or source digest, lock identity, platform category, command, exit code, and sanitized evidence location. Keep raw logs in private or ignored storage. Never attach authentication links, device codes, tokens, secret file contents, session transcripts, or identifiable business paths.

For vulnerability handling, use the [security policy](SECURITY.md). Changes to history, publication, or deployed user instances require their own explicit authorization and review.

After a history cleanup, retained private branches must follow the [history cutover procedure](docs/worktrees.md#history-cutover) before integration. An ordinary merge of old lineage can restore removed history.
