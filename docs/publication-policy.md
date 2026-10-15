# Publication policy

This policy applies to public source, documentation, fixtures, commit messages, commit metadata, and reports. It also applies when private work is prepared for publication. The [security policy](../SECURITY.md) governs vulnerability reports; the [worktree policy](worktrees.md) governs integration into `main`.

## Public content boundary

Keep real usernames, private absolute or business paths, host metadata, personal email addresses, authentication links and codes, tokens, keys, session bodies, and private endpoints out of public material. Summarize operational findings without copying raw logs or transcripts. Public reports must not expose a private evidence location; use a sanitized evidence reference when necessary.

Use generic paths such as `/path/to/workspace`, `$HOME`, and XDG variables, reserved domains such as `example.invalid`, reserved test addresses, and clearly synthetic credentials or canaries. Retain required licenses, notices, upstream attribution, public source identifiers, and toolchain facts needed to reproduce a result. A public upstream URL or synthetic test value is not automatically a disclosure; review its provenance and purpose before changing it.

Do not read real key, authentication, or session files to perform publication checks. Configure scans to report redacted path, line or object location, category, and status only; never echo matching values, paste them into prompts, or publish raw scanner output. Keep private evidence in access-controlled storage. Remediation backups belong outside the public repository, with directories at `0700` and files at `0600`.

If an exposed credential is confirmed, its owner must revoke or rotate it before history remediation. Removing content or passing a bounded scan does not prove that credentials were never exposed, and cannot revoke copies already obtained by others.

## Public commit identity

Use only an explicitly approved public Git identity, including an approved noreply or bot identity. Store `user.name`, `user.email`, and `user.useConfigOnly=true` in repository-local Git configuration. Do not change global Git identity or place a real person's name or email address in shared policy.

Before every commit, inspect these values privately:

```sh
git config --local --get user.name
git config --local --get user.email
git config --local --get user.useConfigOnly
git var GIT_AUTHOR_IDENT
git var GIT_COMMITTER_IDENT
```

Check author and committer environment overrides as well. Both resolved identities must match the approved public name and email, and `user.useConfigOnly` must be true. Stop to resolve missing configuration or a mismatch; never fall back to global or inferred identity. Avoid recording a previously configured private identity in logs. Local configuration controls future defaults; it does not anonymize existing commits or override every explicit author option.

## Publication and history changes

Review staged content and the stable final diff, then run the public-content check and the affected validation required by the [merge gates](worktrees.md). The existing check detects selected machine paths and local link failures; it is not a comprehensive credential or history scanner. Review author and committer metadata and all history intended for publication separately.

The [history remediation procedure](history-cleanup.md) requires explicit scope and authorization. Preserve private backups, active work, legal notices, and source/dependency/lock consistency. A cleanup of `main` alone does not erase the whole repository: retained private branches, worktrees, refs, and backups can still contain old content and identities. Do not publish those refs without their own review. A local rewrite does not authorize a remote update, force push, deletion of another person's work, or removal of copies elsewhere.

After a cutover, follow the [migration rules](worktrees.md#history-cutover) before bringing retained work into clean history. Record the actual cleanup scope and remaining limits without claiming universal erasure.
