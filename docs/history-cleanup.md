# Publication privacy and Git history remediation

The authorized **local `main`-only history cleanup was completed on 2026-10-15**. Other branches, worktrees, remote-tracking refs, and private backups retain their original history. No remote fetch, push, tag, or release was performed. This is a bounded publication cleanup, not whole-repository erasure or an anonymity guarantee.

The durable rules are the [publication policy](publication-policy.md) and [worktree merge gates](worktrees.md). Every future integration into `main` must satisfy those gates. Retained old-lineage branches must start from cleaned `main` and replay only reviewed changes; an ordinary merge would reconnect the history removed from `main`.

## Scope and completed evidence

The rewritten base is `a43dc4445da49e15179d6f0a90343e2b7a214fa5`, with tree `546b64df73c3e8e956231c5d63bc3de83460bc12`. The following documentation-only completion record builds on that base. Platform: Linux x86_64, CPython 3.11.11. `git-filter-repo` reported version identifier `a40bce548d2c`.

| Check | Result and boundary |
| --- | --- |
| Private backup | PASS: all 17 original refs bundled and verified; staged and unstaged patches saved for four original worktrees, without copying native credentials or sessions |
| Restore trial | PASS: all refs and the original `main` tree restored in isolation; both worktrees with unfinished changes reproduced exactly, including staged/unstaged status and patch bytes |
| Rewrite scope | PASS: only `refs/heads/main` changed; the other 16 refs and three retained development worktrees remained unchanged |
| Retired documents | PASS: 1,118 exact retired document/report paths removed throughout `main` history, with Git-quoted non-ASCII filenames decoded before filtering |
| Retained historical text | PASS: known local username/private-email literals absent from 3,650 distinct text blobs and commit messages; this is not a general credential scan |
| Commit metadata | PASS: all 119 commits retained; approved public attribution uses a GitHub noreply address; the existing GitHub bot committer is preserved |
| Immutable material | PASS: 123,094 per-commit lock, vendor, upstream, and legal entries unchanged; the current complete file tree is byte-identical before and after filtering |
| Source archives | PASS within scope: 27 source archives, 4,449 members, and 3,214 safe text members checked for known identifiers; no matches |
| Compressed test fixture | PASS within scope: the public synthetic gzip corpus was checked in memory, expanding to 8,347,197 bytes; no known-identifier matches |
| Remote history, other clones, other operating systems | NOT RUN; outside this local cleanup |

The archive check did not read 279 credential-named members and did not text-scan 956 other members. The main text scan excluded 35 binary/non-UTF-8 blobs; the bounded archive and gzip checks cover selected compressed content separately. No real key, authentication, or session store was read. These limits do not establish that historical credentials never existed or that every binary is free of private data.

Private evidence includes exact local commands, filtering callbacks, before/after refs, commit maps, checksums, and restoration results. It is retained outside the public repository with directories at `0700` and files at `0600`; its machine-specific location is not published here. Local Git identity now requires explicit repository configuration, retains the approved public name, and uses a publicly derived GitHub noreply address. Private account email settings were not inspected.

## What was removed and preserved

Retired handoffs, raw acceptance output, repeated progress reports, and their historical file contents were removed from `main`. Confirmed machine identifiers in retained project-owned documentation, specifications, examples, and tests were replaced precisely. Personal email metadata was normalized to the approved public identity.

Project-owned `specs/`, `.specify/`, and `openspec/` records remain. Maintained English guides, design explanations, Roadmap, known issues, and concise historical support summaries remain. Required LICENSE/NOTICE files, upstream attribution, public source identifiers, dependency locks, and current runtime/configuration resources remain unchanged. Synthetic test values, loopback addresses, and public upstream identities were not treated as private data merely because a pattern matched them.

This operation did not alter any deployed agent, key, account, session, proxy, shell, or terminal setting. Existing functional checks retain their original source/digest and execution scope in [release verification](release-verification.md); they are not relabeled as new test runs after a metadata rewrite. Historical commits whose text was redacted are not newly attested reproducible releases, and original commit IDs may no longer resolve from cleaned `main`. Original signatures are not valid attestations of rewritten commits. The private commit map preserves the correspondence.

## Recovery and remaining publication work

Recovery uses a **new private directory**, never an automatic reset of an active worktree. The backup contains an original all-ref bundle, a separate public-policy increment, a cleaned-main bundle, worktree patches, and manifests. The original bundle restore and unfinished-patch replay were tested. Inspect the manifests and verify bundle checksums before choosing the original or cleaned history; apply each patch only to its recorded base. Restoring old history is a deliberate privacy reversal and must remain private.

The backup preserves Git content and unfinished tracked work, not a full machine or native-account backup. Configuration rollback, software redeployment, and session-database downgrade are separate operations. No credential or session migration is implied by this history cleanup.

Cached `origin/main` still refers to old history. A local ahead/behind report after the cutover is expected; ordinary pull/merge would reconnect that history. Do not use `git push --mirror`. Any remote rewrite needs a separately authorized, reviewed ref-update plan and coordination for collaborators. Remote-only refs, pull-request refs, releases, CI artifacts, cached views, forks, and mirrors were not inventoried or erased here.

GitHub describes credential rotation and remote/cached-copy limits in its [sensitive-data removal guide](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository). The [git-filter-repo manual](https://github.com/newren/git-filter-repo/blob/main/Documentation/git-filter-repo.txt) documents partial rewrites and callbacks. The executed operation used a fresh local mirror with `--no-local`, explicit `--no-fetch`, and `--refs refs/heads/main`; it did not bypass fresh-clone checks with `--force`.
