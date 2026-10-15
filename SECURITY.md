# Security policy

Rotom manages trusted configuration and launches coding agents. It is not a general containment system for malicious code running as the same operating-system user.

## Reporting a vulnerability

Do not include secrets, account exports, authentication links, device codes, private session transcripts, or business data in a public issue. Use the repository's private vulnerability reporting feature when available. If it is unavailable, request a private reporting channel through a minimal public issue that omits exploit and sensitive details; no dedicated response-time guarantee is currently offered.

Provide the affected commit and integration, platform category, a minimal reproduction using temporary files and fictional credentials, the expected boundary, and the observed result. A suspected exposed credential should be revoked or rotated by its owner before history remediation. Do not paste it into a report.

## Security boundaries

- Machine and shared credential files are private; keys are resolved for the selected operation at launch time. OAuth and session state belong to the native instance.
- Public configuration is trusted input. Schema validation and ownership checks do not make an untrusted profile or plugin safe to execute.
- Private files require restrictive permissions, safe path ancestry, ownership checks, and no unsafe links. Active leases prevent concurrent managed writes; they do not isolate arbitrary processes owned by the same user.
- Configuration backups include managed configuration only. They do not back up credentials, OAuth databases, or session databases.
- DSH `workspace-write` limits supported filesystem operations through the actual sandbox backend. It is not general credential or network isolation. AI review does not replace that backend.
- OMP's permission plugin is an application-level approval mechanism, not an operating-system sandbox. Uncovered tools keep their native boundaries.

The default DSH recipe includes Perry auto-review with explicitly accepted unresolved limitations. In particular, session OFF/unload does not reliably invalidate a late approval, and OFF may reset on a later turn. See [known issues](docs/known-issues.md) before relying on mode changes. Persistent manual mode requires stopping the instance and applying the corresponding configuration change.

## Publication hygiene

The [publication policy](docs/publication-policy.md) covers public content and commit metadata; the [worktree policy](docs/worktrees.md) applies before any integration into `main`. Do not inspect real key, authentication, or session files as part of publication checks. Report suspected hits only as redacted location/category metadata.

Use fictional domains such as `example.invalid`, reserved test addresses, generic paths, and clearly marked synthetic canaries. Preserve legally required third-party attribution. Run the public-content check before submitting documentation. That check detects selected accidental machine identifiers and broken local links; it is not a comprehensive credential scanner.

Current-tree cleanup does not erase older commits, author metadata, clones, forks, cached views, or CI artifacts. The [history remediation plan](docs/history-cleanup.md) describes the separate, destructive process and its authorization boundary.

Store remediation backups outside the public repository with directory mode `0700` and file mode `0600`. Cleanup is not proof that no credentials were exposed. A cleanup limited to `main` leaves old history in retained private refs, worktrees, and backups; remote publication requires separate authorization.
