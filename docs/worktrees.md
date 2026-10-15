# Worktrees and merge gates

Every branch and worktree must satisfy these gates before integration into `main`, including private branches retained during a publication cleanup. A worktree being old, previously tested, or already based on `main` does not exempt it. Preserve other agents' edits and user work throughout preparation.

## Prepare an integration candidate

Inventory the target `main` commit, candidate HEAD, branch, worktree status, staged and untracked files, and file ownership before writing. Distinguish task-owned changes from other work and coordinate a single writer for shared files. Do not discard, reset, or absorb unrelated work to make the candidate clean. Prepare focused, clean commits for the intended integration.

Review the final candidate for:

- The complete final diff and affected behavior, with applicable repository instructions and ownership boundaries.
- Private information in content, messages, author and committer metadata, and history that integration would introduce, following the [publication policy](publication-policy.md).
- Dependency sources, versions, licenses, integrity, complete locks, vendor content, and build inputs as one consistent change. Do not update a lock merely to hide a source mismatch.
- Affected offline tests and any required native or platform checks. Keep default checks isolated from real accounts and third-party hosts. Live smoke, login, and model calls retain their separate authorization requirements.

Choose checks by scope. Documentation-only changes can use structure, links, public-content, and diff checks. Runtime or dependency changes require the relevant behavior and failure-path checks. A platform result applies only to the platform actually exercised.

## Evidence and final review

Record the candidate commit or source digest, target `main` identity, lock identity, platform/environment category, actual argument vector, exit code, result, and sanitized evidence reference. Keep raw logs private. A temporary source digest may identify an uncommitted candidate; bind the final evidence to the prepared commit before integration. Track work as completed, in progress, failed pending decision, or unverified because the environment is unavailable.

Unexecuted or unavailable checks are not passes. Record their reason and limits; they need not block unrelated work. Known failures require an explicit decision accepting the precise integration scope, or a fix. Existing test files, task checkmarks, CI configuration, and a native process returning zero do not alone prove acceptance.

Perform final review after all writes finish, against a stable diff or commit. If later edits affect checked behavior, rerun the affected checks and review the resulting candidate. If target `main` advances, re-evaluate the diff, ancestry, conflicts, and affected evidence against the new target before integration. Do not repeatedly rerun unrelated checks without new evidence.

Integrate only within the user's authorization, using a fast-forward or an explicitly reviewed merge. A merge commit must not introduce unreviewed parent history. Do not force-update refs or discard user work to bypass these gates. Report the integrated candidate, actual checks, failures, and unvalidated scope.

## History cutover

A cleanup limited to `main` leaves old lineage in retained private branches and worktrees. Retaining them protects ongoing work; it is not whole-repository erasure and does not make their history suitable for publication.

Do not ordinarily merge an old-lineage branch into cleaned `main`. Start a new candidate from the clean `main`, then replay only the branch's own reviewed changes. Carefully selected cherry-picks may be appropriate, but inspect the resulting content and messages and normalize author and committer identity to the approved public identity. Preserve required upstream attribution. Check copied artifacts and dependencies for information removed during cleanup.

Merging clean `main` into an old branch does not clean that branch's other parents. An ancestry or merge-base check showing clean `main` as an ancestor likewise does not prove that every reachable old parent is clean. Review the actual history that the candidate would introduce and run all gates again. Keep old refs private until separately reviewed; deleting, rewriting, or publishing them requires its own authorized scope. Remote updates remain a separate authorization decision.
