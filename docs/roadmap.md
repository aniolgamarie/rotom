# Roadmap

This roadmap records intended work, not release commitments. Recheck source, locks, upstream APIs, and support evidence before implementation. Concrete defects and unverified capabilities are tracked in [known issues](known-issues.md).

## Release preparation

| Priority | Work | Exit condition |
| --- | --- | --- |
| Required for broader Pi acceptance | Base/Pro official CLI is implemented; complete final-candidate rebuilding, native/account gates, status parity, held collaboration and selected optional-module integration remain separate | Match exact source/lock/runtime and each gate; no transfer of historical four-profile results |
| Ongoing publication hygiene | Cleaned `main` was manually pushed by the user and anonymously verified; review any other ref separately | Retained old-lineage refs require separate review and enter clean `main` only through reviewed replay; no ordinary merge |
| Required before tagging | Freeze a candidate and record validation | Relevant tests, lock checks, documentation links, source/license inventory, explicit unresolved limitations |
| Ongoing | Upstream DSH/Perry fixes | Repeat the real approval-chain and sandbox tests before changing accepted limitations |

## Project refactoring: concurrent runs and terminal scope

**Status: integrated into local `main`; authorized local DSH/OMP and terminal deployment completed. Linux acceptance and remaining platform scopes are recorded separately.**

The [project refactoring plan](design/project-refactoring.md) defines distinct
instance, runtime, run, native-session, Pi-attempt, worktree and credential identities.
Shared run admission and exclusive maintenance now cover DSH, Pi and OMP. DSH
preparation is journaled maintenance. The record's old Pi supervisor/evidence-store design is
historical; Base/Pro use independent main-run owners and retain unknown maintenance blocking. DSH/OMP lock publication and full sync
consumption are leased. Native and cross-platform coverage must remain explicit;
Pi now uses the common publisher/reader lease and recoverable publication protocol.

The same work implements deferred credential reads and an explicit migration to
remove mihomo management from `termcfg`, retaining zsh/tmux and their generic package
machinery. That terminal-only package is implemented with explicit v1 metadata
migration and isolated tests. A future independent proxy project is not implemented;
existing proxy services and private configuration are not moved or deleted.

## Execution-environment consistency

**Status: accepted and integrated into local `main` at `de43346`; existing local DSH/OMP instances and zsh configuration updated through the managers.**

The [execution-environment follow-up](design/project-refactoring.md#execution-environment-follow-up)
now separates caller development paths from native state ownership, restricted
workers, installation and tests. Persistent unset, name-only one-shot controls
and mandatory value-free difference warnings share one launch contract. OMP and
Pi main sessions retain caller paths; DSH preserves native TUI HOME and uses its
public subprocess provider plus separate stdio MCP exec configuration. Terminal
NVM/XDG behavior and the corresponding guides are corrected.

Native evidence is scoped by channel and lock. The authorized local deployment
passed offline doctor, zero-change plan and repeated apply checks. No managed Pi
instance was present, so none was created. Configuration rollback does not imply a
software or session database downgrade. Unverified platforms and native profile
combinations remain listed explicitly.

GPT-6.1 catalog support and its candidate host-stack upgrade are deferred by
maintainer decision. Do not add a provider replacement or force dependency ranges
for that model. Per-route proxy and lease-lifecycle redesign remain separate work.

## RM-001: Declared sources and on-demand dependencies

**Status: deferred design and migration; not delivered.**

Move toward immutable source declarations and profile-scoped materialization, retaining public configuration, locks, repository-owned adapters, and tests in Git. Third-party Git sources should record fixed commits, compatibility, licenses, and content identity; npm sources should record exact versions, resolved URLs, and integrity. Downloaded source and generated archives should live in verified caches where reproducibility permits.

The current repository retains both third-party source and generated archives. Historical measurements showed that the current snapshot, rather than history alone, accounts for much of clone size. This is not solved by deleting archives while runtime/build paths still require them. The old Pi executable package/vendor distribution has since been retired under an explicit source/consumer inventory. Required legal/source attribution remains; this does not erase Git history or alter installed private instances.

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

## RM-003: CLI interaction model

**Status: first delivery implemented and reviewed; final controlled Linux offline acceptance passed against main `9ab90f5` (4390 passed, 13 scoped skips, 7 subtests passed). The previous agent private-state validation gap and inherited stale model-default test are closed; no native deployment is included.**

The [CLI interaction strategy](design/cli-interaction.md) defines a common user
journey: choose scope, observe, diagnose or preview, explicitly act, and verify.
Keep the tools' existing execution and grammar contracts rather than forcing
identical commands. Prioritize context-correct next actions, status overviews on
current doctor/status entries, readable results and completion feedback, then
layered help and safe parameter guidance. Existing setup, model input, and progress
remain in place. Diagnostic scope must not become write authority. Preserve
structured output contracts, exit codes, native argument passthrough, and all
ownership, approval, and recovery checks.

A distinct saved-state agentcfg status command, additional human verbosity,
explicit multi-component terminal sync, and opt-in completion are conditional
follow-ups, not first-delivery requirements. Avoid hidden last-used targets,
implicit profile switching, automatic repair, or batching downloads with adoption
merely to reduce command count.

The old CLI worktree is retained, not ordinarily merged or restored wholesale.
Its retired proxy guidance and file-existence-based readiness hints are not part
of the new scope. The design records implemented contracts, controlled offline
acceptance and the remaining skipped/native/platform scopes; it does not authorize
deployment or remote updates.

## Other planned work

- Reevaluate held Pi collaboration candidates through public interfaces and prove the per-main-run investigation contract. The accepted status-information differences and current footer evidence are recorded separately. Do not restore Task Keeper or a custom execution scheduler.
- Evaluate explicit per-route proxy controls without conflating model, reviewer, ordinary tool, and download traffic.
- Extend native and account validation to additional platforms only when suitable authorized environments exist.
- Maintain English documentation and clearly scoped translations. Prefer durable guides and issue registers over public operational transcripts.

Parallel feature branches and staged work must satisfy the [worktree merge gates](worktrees.md), including the history cutover procedure where applicable. Roadmap entries do not authorize merging unfinished Pi/CLI changes, rewriting history, publishing releases, or modifying deployed instances.

## Pi Base/Pro remaining delivery gates

The current [Pi support matrix](pi-support.md) separates Linux manager rebuild/isolation from
bounded native/shared-model evidence from remaining account/performance/macOS scopes. Source retirement
does not close those gates. The future
collaboration contract allows at most two read-only investigations per main run, but the current
3.1.0 candidate is held and tintinweb 0.22.0 can bypass the foreground cap through background/resume.
The user retained community-only investigation plugins and deferred Pro until upstream improves;
the public footer alternative passed the status gate with three explicitly accepted display differences.

Fixed optional choices now connect complete locks and native resources, with bounded Context7,
Chromium, footer/cache, bounded real-tool and no-account Brave/Cursor evidence. Selected-combination
scenarios and startup/context/resource measurements are recorded in
[current delivery acceptance](../specs/005-rebuild-pi-toolkit/current-delivery-acceptance.md). The user
explicitly deferred Brave/Cursor real-account acceptance; Pro remains an upstream-dependent future gate. Linux child-subreaper observation can release the current owner only after
complete kernel evidence; unavailable coverage and old unknown records still block maintenance.
Neither timeouts nor forced owner cleanup is an accepted completion path.
