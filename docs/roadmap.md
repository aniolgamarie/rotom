# Roadmap

This roadmap records intended work, not release commitments. Recheck source, locks, upstream APIs, and support evidence before implementation. Concrete defects and unverified capabilities are tracked in [known issues](known-issues.md).

## Release preparation

| Priority | Work | Exit condition |
| --- | --- | --- |
| Required for a Pi deployment claim | PI-LOCK: rebuild the stale Pi lock through the official repository workflow | Complete source/lock closure and current native/cold evidence; no digest-only refresh |
| Required for privacy-sensitive publication | Review the [history remediation plan](history-cleanup.md) | Approved disposition of historical machine identifiers and author metadata; current-tree cleanup alone is insufficient |
| Required before tagging | Freeze a candidate and record validation | Relevant tests, lock checks, documentation links, source/license inventory, explicit unresolved limitations |
| Ongoing | Upstream DSH/Perry fixes | Repeat the real approval-chain and sandbox tests before changing accepted limitations |

## RM-001: Declared sources and on-demand dependencies

**Status: deferred design and migration; not delivered.**

Move toward immutable source declarations and profile-scoped materialization, retaining public configuration, locks, repository-owned adapters, and tests in Git. Third-party Git sources should record fixed commits, compatibility, licenses, and content identity; npm sources should record exact versions, resolved URLs, and integrity. Downloaded source and generated archives should live in verified caches where reproducibility permits.

The current repository retains both third-party source and generated archives. Historical measurements showed that the current snapshot, rather than history alone, accounts for much of clone size. This is not solved by deleting archives while runtime/build paths still require them. Some Pi packages contain historical integration changes and cannot be replaced by an upstream URL without behavior analysis.

Implementation stages:

1. Classify every source as repository-owned, unmodified upstream, derived plugin, or historical host deviation; map actual imports and profile use.
2. Separate structural lock validation from downloading/materializing assets; use immutable verified caches and staged publication.
3. Compute the selected profile's transitive closure, avoiding static imports that silently require unselected plugins.
4. Replace historical adaptations with unmodified upstream packages and public extensions where possible; record unsupported behavior otherwise.
5. Verify cold acquisition, warm offline deployment, cancellation, failure recovery, upgrades, and protection of old installations before removing vendor inputs.
6. Consider a separately authorized history rewrite only after the new source workflow is reproducible.

No floating latest versions at launch, unreviewed lifecycle scripts, force/legacy peer bypasses, or patched hosts. Preserve required notices and licenses. Measure clone size and selected-profile download cost after migration rather than inferring improvements from deleted file counts.

## RM-002: Lease descriptor lifecycle

**Status: open design; no lifecycle redesign in this release preparation.**

A background descendant may inherit an instance/state/runtime lease and retain it after the visible host exits. Design the lifetime boundary so unrelated descendants cannot indefinitely prevent deployment while active hosts, recovery, and concurrent access stay protected. Simply deleting lock files or dropping all leases is unacceptable.

Validation must cover foreground commands, native exit, manager failure, daemon descendants, concurrent deployment, and PID reuse. An implementation must use public process and host interfaces; it must not patch an agent.

## Other planned work

- Establish a matching independent TypeScript development lock for Task Keeper and real SDK typechecking.
- Evaluate explicit per-route proxy controls without conflating model, reviewer, ordinary tool, and download traffic.
- Extend native and account validation to additional platforms only when suitable authorized environments exist.
- Maintain English documentation and clearly scoped translations. Prefer durable guides and issue registers over public operational transcripts.

Parallel feature branches and staged work must be reviewed separately. Roadmap entries do not authorize merging unfinished Pi/CLI changes, rewriting history, publishing releases, or modifying deployed instances.
