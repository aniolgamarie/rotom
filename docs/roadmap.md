# Roadmap

This roadmap records intended work, not release commitments. Recheck source, locks, upstream APIs, and support evidence before implementation. Concrete defects and unverified capabilities are tracked in [known issues](known-issues.md).

## Release preparation

| Priority | Work | Exit condition |
| --- | --- | --- |
| Required for broader Pi acceptance | PI-LOCK: full lock rebuilt and pi-default materialized; repeat remaining profile/platform native/cold scopes | Match exact source/lock/runtime; no digest-only refresh or transfer of historical results |
| Ongoing publication hygiene | Cleaned `main` was manually pushed by the user and anonymously verified; review any other ref separately | Retained old-lineage refs require separate review and enter clean `main` only through reviewed replay; no ordinary merge |
| Required before tagging | Freeze a candidate and record validation | Relevant tests, lock checks, documentation links, source/license inventory, explicit unresolved limitations |
| Ongoing | Upstream DSH/Perry fixes | Repeat the real approval-chain and sandbox tests before changing accepted limitations |

## Project refactoring: concurrent runs and terminal scope

**Status: implemented and verified in an isolated task branch on Linux; merge and real deployment are separate.**

The [project refactoring plan](design/project-refactoring.md) defines distinct
instance, runtime, run, native-session, Pi-attempt, worktree and credential identities.
Shared run admission and exclusive maintenance now cover DSH, Pi and OMP. DSH
preparation is journaled maintenance; Pi uses full owner identities and per-run
endpoints in its existing evidence store. DSH/OMP lock publication and full sync
consumption are leased. Native and cross-platform coverage must remain explicit;
Pi lock publication still requires a single publisher.

The same work implements deferred credential reads and an explicit migration to
remove mihomo management from `termcfg`, retaining zsh/tmux and their generic package
machinery. That terminal-only package is implemented with explicit v1 metadata
migration and isolated tests. A future independent proxy project is not implemented;
existing proxy services and private configuration are not moved or deleted.

## Execution-environment consistency

**Status: implemented and accepted in the task worktree; awaiting integration, daily deployment unchanged.**

The [execution-environment follow-up](design/project-refactoring.md#execution-environment-follow-up)
now separates caller development paths from native state ownership, restricted
workers, installation and tests. Persistent unset, name-only one-shot controls
and mandatory value-free difference warnings share one launch contract. OMP and
Pi main sessions retain caller paths; DSH preserves native TUI HOME and uses its
public subprocess provider plus separate stdio MCP exec configuration. Terminal
NVM/XDG behavior and the corresponding guides are corrected.

Native evidence is scoped by channel and lock. Keep the existing deployment until
the reviewed branch is explicitly integrated and deployed; configuration rollback does not imply a
software or session database downgrade. Unverified platforms and native profile
combinations remain listed explicitly.

GPT-6.1 catalog support and its candidate host-stack upgrade are deferred by
maintainer decision. Do not add a provider replacement or force dependency ranges
for that model. Per-route proxy and lease-lifecycle redesign remain separate work.

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
6. Consider any further source/archive history rewrite only after the new source workflow is reproducible; the completed privacy cleanup does not remove declared vendor dependencies.

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

Parallel feature branches and staged work must satisfy the [worktree merge gates](worktrees.md), including the history cutover procedure where applicable. Roadmap entries do not authorize merging unfinished Pi/CLI changes, rewriting history, publishing releases, or modifying deployed instances.
