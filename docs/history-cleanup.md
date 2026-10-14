# Publication privacy and Git history remediation

Current-tree cleanup and historical erasure are separate operations. This preparation removes public operational transcripts, replaces private machine paths, and preserves useful support conclusions. It does **not** rewrite Git history, change author identity, delete other worktrees, or update remote refs.

## What was found and retained

The bounded repository scan found local absolute paths and environment details concentrated in dated handoffs and raw acceptance output. Selected history searches confirmed such text had been committed. Commit author metadata also links identities. Pattern hits in synthetic tests, loopback protocol addresses, RFC private-network checks, public upstream URLs, and required third-party notices are not automatically disclosures.

The scan did not inspect real key/authentication/session files, browser data, keychains, or other applications' account stores. Named credential-like tracked paths were excluded from body inspection. This is not a claim that all historical credentials have been exhaustively checked.

Publication cleanup retains:

- English functional/configuration guides, architecture/design explanations, testing policy, release scope, Roadmap, and known issues.
- Project-owned `specs/`, `.specify/`, and `openspec/` records, with private path redaction where needed. Directory names alone never authorize deletion.
- Immutable upstream source identities and required LICENSE/NOTICE/attribution material.
- Concise historical support summaries that state their original scope rather than transferring acceptance to a new candidate.

Raw retired files are not publicly attested by rewritten hashes. An ignored local backup may aid review but is not a public release artifact and should be removed or stored privately after review.

## Reviewable remediation procedure

History rewriting is destructive and needs separate explicit approval, coordinated branch handling, and a publication decision. The following is a procedure for a **new disposable clone**, not a command to run in a working repository with active worktrees.

1. Freeze the proposed publication candidate and inventory branches, tags, remote refs, pull-request refs, existing clones, and author metadata. Preserve active/staged work separately. Retain a private access-controlled backup outside the publication clone.
2. Build a reviewed path-removal list and literal replacement list in private files. Include historical renamed paths. Avoid broad patterns that remove project specifications or third-party attribution. If any actual credential is confirmed exposed, its owner must revoke or rotate it first.
3. Decide whether author metadata should use an approved public identity. Changing current Git config does not anonymize old commits. Never invent or silently substitute a contributor's identity; retain legally required attribution.
4. In the disposable clone only, use a verified `git-filter-repo` version supporting `--sensitive-data-removal` (at least 2.47 per GitHub's documentation). Example forms, after the lists are reviewed:

   ```sh
   # Remove reviewed paths, including their former names; list is private.
   git filter-repo --sensitive-data-removal --invert-paths --paths-from-file /private/reviewed-paths.txt
   # A separate alternative/pass for reviewed literal replacements.
   git filter-repo --sensitive-data-removal --replace-text /private/replacements.txt
   ```

5. Inspect changed-ref and commit maps, rescan all intended publication refs, verify notices/licenses and current file content, and rerun source/lock validation. Rewriting source bytes can invalidate content identities; do not modify a lock merely to silence that failure.
6. Present the exact ref changes, backup location, identity decision, tests, and force-update plan for approval. No remote update is included in this preparation.
7. After an approved remote rewrite, coordinate fresh clones or carefully migrated work. Old branch merges can reintroduce removed history. Review releases, CI artifacts, cached views, pull-request refs, forks, and mirrors separately.

Literal text replacement does not automatically sanitize content inside compressed archives. Inventory affected blobs separately and choose exact removal paths or a properly rebuilt declared artifact, preserving required licenses and source/lock closure. Do not assume a clean text scan covers binary history.

A history rewrite changes commit IDs and may invalidate signatures and existing evidence references. It cannot erase copies held by others. Public repository ownership, package/source URLs, license notices, and prior public associations can still identify the project; machine-path cleanup is not anonymity.

GitHub describes credential rotation, clone coordination, cached/PR references, and rewriting side effects in its [sensitive-data removal guide](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository). Use the [git-filter-repo documentation](https://github.com/newren/git-filter-repo/blob/main/Documentation/git-filter-repo.txt) for exact supported options. Both should be rechecked at execution time.

## Preventing recurrence

Use generic `$HOME`, XDG, and `/path/to/workspace` examples. Keep machine overrides, keys, sessions, raw logs, and test accounts outside Git or under explicitly ignored private directories. Run `scripts/check-public-docs.py`; it reports selected path/link findings without echoing matched values. Review staged content and use a credential scanner configured for redacted output in a controlled publication clone if full historical credential assurance is required. Do not publish raw scanner output or add secrets to an AI prompt to investigate a hit.
