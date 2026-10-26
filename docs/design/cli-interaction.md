# CLI interaction model and optimization strategy

**Status: first delivery implemented and reviewed; final controlled Linux offline acceptance passed against main `9ab90f5` (4390 passed, 13 scoped skips, 7 subtests passed). The previous 86-case agent validation gap and inherited stale test are closed. Native deployment and conditional follow-ups remain outside this delivery.**

Initial design baseline: local `main` at `5e1a042ec05afe99a80ade84f4aded06cd7c1a9a`.
The successor branch `design/cli-ux-reboot` was created directly from that baseline.
It has since fast-forwarded to `a84710a98d1a687edb5033728178bf52ebc32214`, with the
reviewed CLI patch preserved and replayed. Integration retains main's strict
HOME/XDG discovery, fixed `unsupported-root-owner` diagnostics and controlled
Linux test entry; no ownership check is relaxed.

The old `cli-ux-help` worktree and its six staged files remain unchanged. Its old
parent history and file snapshots are not merged or copied into this branch.
Only reviewed design intent is carried forward, following the
[history cutover rules](../worktrees.md#history-cutover).

## Decision

Unify the user's decision model, not the two command grammars:

**Choose scope → observe → diagnose or preview → explicitly act → verify.**

Do not restart the original deployment-simplification project. The first delivery
should provide context-correct guidance, useful status overviews on existing
commands, layered result detail, discoverable help, and precise parameter errors.
Simplify redundant input and decision-making before adding command aliases,
wrappers, or remembered state. A new command must answer a different question,
not merely rename an existing one.

This is not a new menu, TUI, setup wizard, status daemon, automatic repair loop, or
combined agent/terminal manager. It does not change deployment, account, approval,
lease, or recovery policy. This document separates recommended first-delivery
changes from later candidates and rejected shortcuts.

## What the current baseline already provides

Source references below refer to the baseline, not a future implementation.

| Existing behavior | Source | Consequence for this work |
| --- | --- | --- |
| Profile listing, idempotent private initialization, and `setup` | [`commands.py`](../../src/agentcfg/commands.py), `cmd_profiles`, `cmd_setup`; [`local.py`](../../src/agentcfg/local.py), `initialize_local` | Keep these flows; do not add another installation command. |
| `run` infers the agent from the selected profile; explicit agent must match | [`cli.py`](../../src/agentcfg/cli.py), `build_parser`; [`commands.py`](../../src/agentcfg/commands.py), `workspace` | An agent argument is an assertion, not a profile switch. |
| Hidden model key/URL input, model status, presets, and model addition | [`commands.py`](../../src/agentcfg/commands.py), `cmd_model` | Do not replace working input flows or inspect native account stores. |
| Human/JSON selection, selector-preserving suggestions, stderr progress | [`presentation.py`](../../src/agentcfg/presentation.py), `command_line`, `emit_result`; [`progress.py`](../../src/agentcfg/progress.py) | Reuse the agent-side behavior instead of redesigning output formats. |
| Terminal-only ownership, explicit legacy migration, and recoverable writes | [`termcfg/cli.py`](../../src/termcfg/cli.py), `build_parser`, `main`; [terminal guide](../termcfg.md) | zsh/tmux only; mihomo appears only in retirement/migration explanations. |
| Caller-environment controls and diagnostic provenance without values | [`agentcfg/cli.py`](../../src/agentcfg/cli.py), `run` and `doctor` options | Preserve `--inherit-env`, `--unset-env`, `--proxy`, and `doctor --environment`. |
| Plugin source declarations and optional Pi project integration | [`termcfg/cli.py`](../../src/termcfg/cli.py), `lock`; [`agentcfg/cli.py`](../../src/agentcfg/cli.py), `project` | Keep `--repo`/`--entry`; do not advertise OpenSpec installation for DSH. |

The maintained [getting-started guide](../getting-started.md) already explains the
short deployment path. Longer help is not a substitute for fixing misleading
next actions or unreadable results.

## Interaction model and user journeys

### Commands answer different questions

| User question | agentcfg entry today | termcfg entry today | Design rule |
| --- | --- | --- | --- |
| What can this tool manage? | `--help`, `profiles`, `model presets` | `--help`, `components` | Static help and public catalogs; no private initialization or account inspection. |
| What am I targeting and what is the current situation? | Overview at the start of `doctor`; `model status` for model configuration only | `status` | Identify the scope and the evidence behind each state; missing/unknown is not healthy. |
| Why is it not ready? | `doctor`, explicit `--environment` / `--input`; `model status` for missing model fields | `doctor`, optional `--strict` | Explain blockers and prerequisites; do not automatically fix them. |
| What would change? | `plan` | `plan`, `rollback --plan-only` | Show changes, conflicts, adoption and consent requirements; not authorization to apply. |
| Prepare or change configuration | `init-local`, `model`, `setup`, or separate `sync` / `apply` | `init-local`, per-component `sync`, `apply` | Keep network, private-file writes, target writes, and prompts explicit. |
| Daily use | `run` | Use the configured shell/tmux normally; inspect with `status` when needed | No repeated setup, implicit sync/apply, or manager-initiated shell/server restart. |
| Recover or retire old ownership | Configuration `apply`/`rollback` as appropriate; distinct Pi execution `recover` | `recover`, `rollback`, explicit `migrate --drop-mihomo` | Different recovery domains must not be collapsed into one generic repair action. |

A first-time user follows a small recipe; an experienced user uses the same
commands directly. Human terminal use and scripting are not separate execution
engines. Only presentation and explicitly interactive input differ.

**First-use recipes:** agentcfg uses initialization → model-field inspection and
necessary input → setup → run. Termcfg uses component selection → doctor/plan →
optional locked-plugin sync → explicit apply → status. If the selected native
program is missing, the manager explains prerequisites rather than installing it.
A named machine retains its name throughout; a new profile does not silently
replace an existing machine's default profile.

**Change recipes:** distinguish private configuration updates from public-source
or dependency changes. Do not recommend `setup` or `lock` after every edit.
Use the existing [operations guide](../operations.md#change-configuration) for the
adapter-specific lock boundary. Merely updating a shared API key does not justify
redeploying all configuration; the existing model commands explain when rerun is
sufficient. After a successful operation, say what changed and what remains
unchecked, not only "success" or "ready".

### Status overview, diagnosis, and preview are separate views

Use a common first-screen vocabulary without flattening backend semantics:

| Dimension | What to display when known | What must not be inferred |
| --- | --- | --- |
| Target | Machine, profile/agent or selected components; explicit versus default selection when actually retained | A guessed current target from the last command, cwd, or another machine file |
| Configuration/deployment | Initialized, deployed, pending changes, or unavailable evidence | File existence means deployed; configured model means authenticated |
| Dependencies/environment | Checked installation or program availability, missing/damaged, optional degradation, not checked | Receipt presence alone proves integrity; optional plugins are required |
| Ownership/recovery | Conflict/drift, pending transaction, backup availability, migration requirement | No visible host means it is safe to remove a lease or overwrite a target |
| Effect scope | Offline observation, private diagnostic/cache write, download, target write, or native launch as applicable | Offline means no writes; applied files mean a running shell/server has reloaded them |
| Evidence limits | Observed in this invocation, recorded deployment fact, unverified, or not applicable | Offline-ready means live account/model readiness or every platform is accepted |

Show the command outcome separately from the state of the managed object. Keep
all blockers and consent-relevant IDs visible even if that exceeds a nominal
screenful. Unknown activity is not "stopped"; an active lease is not proof of a
particular native conversation. Do not add background polling or host/account
inspection just to populate a status row.

**Recommendation for the first delivery:** add a concise overview to existing
agentcfg `doctor` output and improve termcfg `status`/`doctor`. Keep `model status`
separate: it explicitly resolves referenced keys to report missing configuration
(`src/agentcfg/model_status.py:18-48`); do not silently invoke it from generic help
or an overview and widen that command's credential access.

**Conditional follow-up: agentcfg `status`.** A selected-instance view of saved
deployment, backup, and recovery facts has independent value. Recommend it only
as a later additive command with its own contract, not as an alias to `doctor`.
Current doctor resolves the workspace/current lock, checks runtime integrity,
may render a candidate, compares drift, and writes diagnostic files
(`src/agentcfg/commands.py:284-330`). Runtime status includes topology and content
checks (`src/agentcfg/runtime_packages.py:66-96`); current termcfg status also
reads target content for comparisons (`src/termcfg/environment.py:88-137`).
Neither is merely a cheap metadata snapshot; no latency measurement is claimed.

Before adopting the new command, demonstrate safe selected-state reads without
candidate rendering, diagnostic/cache creation, secret-reference resolution,
native account inspection, or network. Where the selected binding can be established
safely, it should still describe saved deployment facts when current public sources
or locks are invalid; do not guess another instance when binding resolution fails.
Define missing/uninitialized, corrupt, unsafe, and concurrently changing state
separately; fail closed for unsafe state and never reinterpret corruption as
"not initialized". Verify ownership/binding,
mark recorded versus freshly checked facts, and specify its own JSON schema and
exit behavior without changing doctor. A saved runtime ID must not be labeled
"installed and healthy" without the corresponding integrity check. If the
metadata-only boundary cannot be established, defer the new command rather than
weaken the old one. It is not required for the first delivery.

### Layered detail without hidden extra work

Use three information levels:

1. Default human result: scope, outcome, required action, effects, and limitations.
2. Detailed human result: explain the already collected component/target facts.
3. Existing machine-readable result: stable fields for scripts, not a human dump.

A presentation-only `--verbose` on agentcfg `doctor` or termcfg `doctor`/`status`
is a conditional extension, not a first-delivery prerequisite. The terminal
catalog currently has only four targets; a readable target table may already
suffice. Compare normal and long-report mockups before adding a flag to remember.
Existing model verbose options remain unchanged.

If adopted, verbosity must reuse the same collected facts: no additional scans,
probes, credential reads, or network. It is not an alias for `--live`, `--input`,
or `--environment`, and must not hide fields explicitly requested by those flags.
Use it only for genuinely lengthy noncritical evidence or complete capability
lists; do not add it to every command, dump unknown objects, or redact less.
With explicit JSON, verbosity must not alter the JSON fields or trigger extra
checks; all mandatory safety detail remains in the default human result.
These potential new verbose options are not accepted by the baseline parser.

For example, a proposed terminal overview could look like this. This is fictional
UI design, not captured output or a report of this machine:

```text
status  workstation / zsh, tmux
Result: action required (offline observation)
zsh: 1 conflicting managed target (zshrc)
tmux: no required blocker; optional plugins not synced
Recovery: no pending transaction observed
Next: ./termcfg --machine workstation plan --component zsh
JSON details: ./termcfg --machine workstation status --json
```

### Human and script contracts

| Invocation | Presentation | Execution boundary |
| --- | --- | --- |
| No command | Short static task map; exit 2, with existing output-channel rules below | No configuration/stat calls, prompts, state checks, or automatic default action |
| `--help` / `COMMAND --help` | Complete reference / scoped examples; exit 0 | No initialization or deployment checks |
| Explicit command in a TTY | Concise result; only existing required confirmations or model/selection input | Do not replace malformed arguments with an interactive wizard |
| Explicit command in a pipe or CI | Preserve existing format rules; scripts should request the documented structured format | No new surprise prompts or guessed answers; retain current non-TTY refusals and gates |
| Existing interactive command plus JSON | One final JSON object where that interface exists; existing prompts/progress stay on stderr | JSON is a format, not approval or a promise to disable all existing TTY prompts |

Retain agentcfg's `--format auto|human|json` on supported commands, pipe TSV for
`profiles`, and existing text/native-output exceptions. Retain termcfg's explicit
`--json`, including errors; do not silently introduce automatic JSON in pipes.
Use semantic consistency and common wording, not a forced shared parser, result
schema, or backend framework. Explicit live checks remain separately selected.

## Baseline gaps and implementation contracts

### 1. Preserve the context of next actions

At the baseline commit, terminal handlers, environment reports, and errors frequently construct
fixed strings such as `./termcfg doctor`, `./termcfg plan`, and `./termcfg recover`.
For a named machine these silently point back to `default`. Relevant sources are
`termcfg/cli.py:199-232,248-327`, `termcfg/environment.py:83-84,122,137`, and
`termcfg/config.py:86-100`.

Introduce a small terminal-owned command builder using validated context and
explicit argument tokens. Do not add an agentcfg dependency to termcfg or create
a shared command framework for this change.

- Keep the selected non-default `--machine` in every actionable suggestion,
  including success, failure, migration, and pending recovery. The default case
  may retain its existing short spelling.
- Retain `--component` only when meaningful and accepted by the destination
  command. `recover` and `migrate` are machine-wide; do not invent a component
  option for them. Preserve multiple selections for commands that accept them.
  For single-component destinations, use existing per-component hint slots or
  explicitly labeled human alternatives. Keep top-level `next_command` a single
  valid command, never a list, newline-separated script, or shell command chain;
  do not silently discard the remaining selected components.
- A diagnostic `--home` is not deployment authorization. Keep it only for
  compatible diagnostic suggestions, label the override, and require a fresh
  preview of the saved machine target before suggesting a write. Never transfer
  an override-target plan ID to the saved target or silently suggest applying to
  a different HOME.
- Use structured tokens and shell quoting, never `eval`, shell execution, or
  arbitrary parsing/replacement of an existing `next_command` string. Migrate
  the affected known producers and their nested component hints explicitly.
- Do not guess context from invalid raw arguments. Parser errors name only a
  recognized command/option and fixed guidance. Before a machine has been read,
  only separately validated selector values may be used; unknown or invalid
  context falls back to placeholders, not an inferred default machine.
- Rendering a suggestion must not read additional files, acquire leases, or run
  anything. The invoked command still performs its own validation and admission.

Examples of the intended shape, using fictional configuration names:

```sh
./termcfg --machine workstation doctor --component zsh
./termcfg --machine workstation recover
./termcfg --machine workstation migrate --drop-mihomo
```

These are conditional alternatives, not a sequence to execute automatically.
Recovery must be resolved before legacy migration when a journal is pending.

**Compatibility:** retain existing JSON field names/types, reason codes, and exit
codes, with these targeted, regression-tested corrections (not byte-identical JSON):

- `next_command` values preserve the target, prioritize recovery, offer optional
  component sync, and send an unchanged plan to status. Unknown legacy recovery
  state first points to status; failed recovery points to inspection, not blind retry.
- Invalid machine selectors are redacted: error `machine_id` is `<invalid>` instead
  of echoing arbitrary rejected input. Reason and exit code remain unchanged.
- Cached plugin activation records the existing `activate` stage before selection
  replacement, so subsequent failures correctly report the existing
  `private_package_or_selection_may_have_changed` side-effect value.
- Apply/rollback failure after backup/write/verify/commit, with no journal available,
  reports the existing `check_home_and_transaction_state` value rather than claiming
  `home_unchanged`. No journal does not prove that no write occurred.
- The existing read-only failure diagnostic supports strictly validated legacy
  journals, so legacy apply/rollback errors can now populate the already defined
  conditional `transaction_id` and `transaction_phase` fields and report recovery
  pending. This does not change admission to any write or migration operation.

No new JSON action framework or reason/exit code is introduced. Unrelated terminal
facts and all agentcfg structured payloads/readiness values remain unchanged.

### 2. Project terminal results into readable summaries

At the baseline commit, `termcfg/diagnostics.py:62-71` printed nested Python
dictionaries directly in non-JSON mode. Existing payloads already contain most necessary facts; no extra
inspection is needed to present them better.

Add command-specific, allowlisted human rendering while retaining `--json` as the
existing single-object interface. The human result order is:

1. Command outcome and selected scope.
2. Blocking facts, pending recovery/migration, and any partial side effect.
3. A primary next action, with prerequisites or alternatives clearly labeled.
4. Necessary IDs and detail, with the existing `--json` form for full structure.

Rules for the renderer:

- Distinguish "selection saved", "preview produced", "configuration applied",
  and "environment ready". A successful command or exit zero does not imply a
  fully usable shell, an authenticated agent, or a successful model request.
- Preserve `blocked`, `degraded`, `unverified`, and `ready` distinctions. Optional
  missing plugins are not mandatory blockers. Keep current `doctor --strict`
  semantics; do not infer an exit-code change from a new summary label.
- A missing required program needs a fixed explanation to prepare the documented
  toolchain, not only another `doctor` command. Do not guess a package manager or
  install automatically. For an invalid dependency lock, explain inspection or
  restoration first; regenerating a lock is deliberate maintenance, not routine repair.
- For plans, keep the plan ID, target/component IDs, actions, adoption requirements,
  and backup facts visible. `adopt-required` can coexist with `ready: true` in the
  current preview; it is not authorization to overwrite. Never hide consent-
  relevant details behind a count or automatically fill adoption/confirmation flags.
- For partial failures, put `side_effect`, transaction phase, recovery status,
  and affected target/component ahead of a generic retry suggestion. Pending
  recovery takes precedence over setup, sync, apply, or migration guidance.
- Do not recursively print unknown structures or fabricate readiness from absent
  fields. Unknown reason codes remain recognizable without exposing private
  values; missing facts are shown as unknown, not as success.
- Use plain text that remains readable at narrow terminal widths, over SSH/tmux,
  and without color. Escape control characters; do not truncate identifiers or
  commands into unusable fragments. No pager, terminal queries, or screen clearing.
- Keep prompts and progress on stderr. Preserve the current termcfg default of
  human output unless `--json` is supplied; do not introduce automatic piped JSON
  or a new `--format` option merely to match agentcfg.

Alongside the agentcfg overview above, emphasize recovery prerequisites before
displaying other next actions. Current readiness collection
can include recovery, sync, setup, and plan simultaneously
(`interaction_diagnostics.py:24-51`, `presentation.py:409-418`). Do not rewrite the
readiness policy, suppress JSON facts, choose apply versus rollback for the user,
or conflate Pi execution recovery with configuration rollback.

### 3. Make help a short map rather than another manual

Observed: terminal subcommands have very little help text
(`termcfg/cli.py:28-73`). Agent help lists commands but does not explain task order.
The old patch adds useful ideas, but also stale capabilities and unreliable file-
existence-based "ready to run" hints.

- Top-level `--help`: retain the complete command/options reference with a short
  task index: first use, daily use, diagnosis, maintenance, recovery/migration.
  Do not repeat the entire command table as a second long epilog.
- Subcommand `--help`: explain purpose, selector placement, side effects, common
  examples, and relevant safety prerequisites. Prioritize termcfg and current
  `migrate`, `lock --repo/--entry`, and agent environment controls. Clarify that
  agentcfg `init-local` takes both `--machine` and `--profile` after the command,
  while `profiles` and `model presets` do not accept global selectors. Preserve
  termcfg's existing before/after placement for `--machine` and `--json`.
  Categorize `capture` as producing an adoption proposal, not as recovery.
- Empty invocation: offer a compact static entry guide, keep exit code 2, and
  never initialize, prompt, inspect HOME, stat a machine file, or launch a host.
  Agentcfg's existing human stdout channel remains unchanged. For termcfg, retain
  the failure result on stdout and add a concise guide on stderr in human mode.
- Selector-only invocations remain missing-command errors, not implicit actions.
  No selected profile or machine is resolved merely to display help. Explain
  selector placement without echoing unvalidated argument values.
- `termcfg --json` without a command or with invalid arguments still produces
  exactly one final failure object on stdout. Explicit `--help` retains its
  existing text/exit-zero behavior, including when `--json` is also supplied.
- Route parameter errors to the narrowest recognized `COMMAND --help` without
  echoing rejected values. Unknown commands fall back to top-level help. Do not
  expand accepted syntax, introduce fuzzy aliases, or change duplicate-option
  semantics as part of an error-message improvement.
- Preserve `agentcfg usage --help` and `run -- --help` as native tails, not manager
  help. Preserve all existing argument boundaries and original argv values.

An OMP launch example must select the profile, not imply that `run omp` switches it:

```sh
./agentcfg --machine workstation --profile omp-default run --cwd "/path/to/workspace"
```

State that the selected profile must already be initialized and deployed. Reference
current integration guides for prerequisites rather than making help longer with
host-specific login instructions. Require parser tests for every example;
multiline shell examples must have a true final backslash, not trailing comments
or spaces.

### 4. Parameter guidance and deliberate simplification

Prefer removing uncertainty over removing explicit safety boundaries.

**Parameter errors:** report the recognized command, fixed reason, relevant
registered option names/choices, and a safe example plus local help. Distinguish
missing required arguments, invalid public enum choices, selector placement,
mutually exclusive flags, and repeated selectors. The parser's raw error string
and rejected values are not a safe diagnostic source. Use registered parser
metadata; never echo secrets, URLs, arbitrary paths, or unknown option tokens.

For example, missing termcfg sync arguments can name `--component` and its public
choices `zsh`/`tmux`, then point to `./termcfg sync --help`. Wrong agentcfg selector
placement can explain the before-command rule and the `init-local` exception.
Missing model subcommands should lead to `./agentcfg model --help`, still exit 2,
and not trigger prompts. Do not scan or reinterpret native tails to provide these
hints; preserve `usage` and the `run --` boundary.

**Simplification decisions:**

| Candidate | Decision | Reason and boundary |
| --- | --- | --- |
| Omit repeated agent/profile input when existing defaults suffice | Recommend now | Explain existing `default_profile` and `run` inference; show both a default-machine short recipe and a named-machine recipe. Never silently change an existing default. |
| Copyable next commands with validated selectors | Recommend now | Removes retyping without introducing hidden target state; no automatic execution. |
| Clearer parameter help, choices, defaults, and side-effect descriptions | Recommend now | Makes existing names and grammar usable without renaming flags or changing what is accepted. Defaults must be described accurately, including per-command exceptions. |
| New agentcfg `status` | Conditional follow-up | Useful only as the distinct saved-state view defined above; not a doctor alias or proof of runtime health. |
| New diagnostic `--verbose` | Conditional | Add only when mockups demonstrate useful noncritical detail that cannot fit the normal result. Explicit diagnostic flags remain visible without it. |
| Shell completion | Later opt-in | Prefer static registered commands/options/enums and, if needed, public profile IDs. No secret/account lookup, private machine-file enumeration, shell startup side effects, host execution, or new dependency merely for completion. Do not install completions automatically. |
| Arbitrary placement of agentcfg global options, new short aliases, or `help COMMAND` | Defer | Existing parser and native-tail contracts make these more than wording changes. First measure whether precise hints and examples solve the problem; any future grammar change needs its own ambiguity/compatibility matrix. |
| `run omp` automatically chooses an OMP profile | Reject | A tool can have multiple profiles; changing target is not a safe inference from an agent assertion. |
| Remember the last machine/profile, infer from cwd, or add implicit local selection files | Reject in this scope | Fewer keystrokes would hide target changes and risk acting on the wrong instance/HOME. Existing explicit selectors and declared defaults are sufficient. |
| Explicit multi-component termcfg sync | Conditional follow-up, not first delivery | A narrower way to reduce repeated optional downloads than a setup wrapper. Preserve single-component compatibility; define explicit selection, order/failure stopping, total timeout, per-component results, cancellation, and partial success. Do not imply cross-component atomicity. |
| New `termcfg setup`, implicit all-component sync, or broad batch operations | Defer | Two optional plugin groups do not yet justify bundling downloads with target adoption and writes. Omitting a required component must not become authorization to touch every component. |
| Add menus, a new wizard for parse failures, automatic correction or repair | Reject | They obscure repeatable command contracts and can turn discovery into side effects. Keep current model/selection input only where already explicit. |
| One universal `--yes` / `--force`, or fewer ownership/plan confirmations | Reject | Adoption, custom `.zshenv`, plan IDs, and recovery consent are distinct authorization boundaries. |

**Prompts and follow-through:** existing TTY prompts should identify scope and
proposed effects, provide a clear cancel route, and keep secrets hidden. Do not
insert a new confirmation into every existing explicit command, or interpret
JSON as consent. Preserve command-specific cancellation/exit behavior and report
partial effects from existing transaction facts. After a successful change,
distinguish "saved", "installed", "deployed", and "takes effect on next launch".
Use a specific verification suggestion when available; do not loop doctor → doctor
without explaining the prerequisite that the user must change.

A next-action presenter is not another state machine. Use the command's existing
facts/reason codes, with priorities: unsafe or unreadable state stops actionable
writes; pending recovery precedes migration or ordinary work; conflict/drift calls
for review; required dependencies or configuration come before optional cleanup.
Show one primary action when the evidence is sufficient. Label mutually exclusive
recovery alternatives and later prerequisites rather than presenting all commands
as an unconditional sequence. Missing facts should lead to a bounded explicit
inspection command, not speculative repair. Do not add a cross-command session,
persistent task queue, or new JSON action framework for this presentation policy.

## Wording and safety invariants

- `setup` performs validation and preview, rejects drift/conflicts before sync,
  reloads inputs after sync, and rechecks under the apply gate. It is not merely
  equivalent to typing `plan; sync; apply`.
- Agentcfg plan/doctor are offline by default and do not deploy the instance,
  but may write private diagnostic/proposal files (`commands.py:149-151,399-411`).
  Do not describe every offline command as "zero-write".
- Terminal apply can require separate confirmation for a custom `.zshenv`.
  Preserve plan-ID, adoption, secret-boundary, backup, and recovery requirements.
- Terminal migration changes validated metadata, not proxy services, target files,
  subscriptions, or account state. Legacy recovery remains explicit.
- `run` never installs or deploys implicitly. Activity/concurrency guards,
  environment warnings, credentials, native accounts, and current host policies
  remain outside this presentation change.
- No native host modifications, dependency/lock updates, permission relaxation,
  filesystem traversal shortcuts, or deployment to real instances.

## Delivery order and acceptance

Steps 0–4 below are implemented and validated within the limits recorded below.
This acceptance does not prove native or real-account behavior or support for the
original unsupported executor namespace, and does not authorize deployment or
remote updates.

| Step | Bounded change | Acceptance focus |
| --- | --- | --- |
| 0 | Fix the interaction contracts in focused tests and fictional output mockups | Default/named machines, ordinary/blocked/partial results, help/errors, TTY and scripts. Establish what the first screen must answer before adding flags. |
| 1 | Terminal next-command builder and affected known producers | Named machines, repeated components, migration/recovery, failure paths, safe quoting, diagnostic HOME isolation; JSON changes are limited to the documented hint/redaction and error-diagnostic corrections. |
| 2 | Terminal human result projection and completion feedback; agent doctor overview/recovery emphasis | Synthetic ready/blocked/degraded/unverified reports, recorded versus checked facts, partial effects, plan/adoption IDs, no unknown/private structure expansion; JSON payload/exit behavior unchanged apart from step 1. |
| 3 | Task index, subcommand help, static entry guidance, contextual parameter errors | No-config/no-I/O help, exit 0 for help and 2 for missing/invalid commands, accurate defaults, JSON errors, native tails, width handling, and valid examples; no grammar normalization. |
| 4 | Minimal maintained-guide updates and final review | Current English authoritative guides and scoped Chinese landing page; short default and named-machine recipes; no stale service/core promises or unsupported claims; public-content/link checks. |

The status collector, additional verbose options, explicit multi-component sync,
and completion remain separate conditional follow-ups. Completing steps 0–4 does
not implicitly approve their API or implementation. Compare mockups before
introducing verbosity; establish the saved-state boundary before introducing status.

Use representative transcript fixtures to check the interaction, not only isolated
formatting helpers:

| Scenario | Required observable outcome |
| --- | --- |
| Fresh default or named machine | Discovery does not inspect private state; explicit initialization/setup guidance stays on the intended target. |
| Healthy or unchanged result | Shows scope and evidence limits; does not demand another apply or claim a native session has reloaded. |
| Required blocker versus optional degradation | Required prerequisite is actionable; optional plugins do not become a hard failure. |
| Drift or adoption needed | IDs and review/confirmation requirements remain visible; no unconditional apply suggestion. |
| Pending recovery plus missing dependencies | Recovery prerequisite precedes sync/setup/migration; partial effects remain visible. |
| Invalid arguments, nested command, or native tail | Specific safe help, unchanged exit contract, no private-value echo and no reinterpretation of native arguments. |
| Pipe/JSON, narrow terminal, or explicit extra diagnostics | Stable machine interface; readable human fallback; requested environment/input/live scope stays visible without an extra detail flag. |

For each suggested executable command, parser-check it in the corresponding
synthetic context without dispatching it. Check that the user's target, blocking
reason, side effects, and next decision can be identified from the transcript.
These fixtures establish output contracts, not evidence of a real user study or
native/platform acceptance.

Use existing CLI, setup, presentation, termcfg status/plan/apply/recovery/migration,
security, and environment tests as regression anchors. Add focused tests for new
context and presentation contracts instead of making assertions only about whole
help snapshots. Test synthetic filenames containing spaces and non-ASCII text,
private argument canaries, and absence of metadata reads during help. Do not copy
real configuration or accounts into fixtures.

Before integration, check the final diff against then-current `main`, preserve
newer flags and behavior, run the relevant isolated regressions, and follow the
[worktree gates](../worktrees.md). Native or account validation requires its own
scope and authorization; it is not implied by this design.

## First-delivery implementation and validation

- Static `cli_help.py` modules describe the existing grammars and tokenized/scoped
  examples. Bare entry and parser failures do not probe state. Agentcfg retains a
  static `usage:` line as well as the task map, and preserves native argument tails.
- Terminal `guidance.py` retains explicit tokens in string-compatible hints. Known
  producers use these rather than building shell strings; the CLI resolves only
  registered top-level/component hint slots using validated presentation context.
  It does not parse old strings, execute suggestions, or change action admission.
- Terminal `presentation.py` projects known fields without additional I/O. It
  retains plan/adoption/backup/transaction facts and distinguishes operation effects
  from health. Agentcfg doctor names scope, prioritizes recovery alternatives,
  qualifies lock maintenance, and shows every required capability blocker rather
  than truncating that list. Explicit extra diagnostic facts remain visible.
- New contracts are in `tests/test_agentcfg_interaction.py`,
  `tests/test_termcfg_guidance.py`, `tests/test_termcfg_interaction.py`, and
  `tests/test_termcfg_presentation.py`. They include synthetic canaries, no-I/O
  sentinels, named machines, multiple components, diagnostic HOME separation,
  interrupted writes, JSON preservation, and parser-only help examples.

The following focused results are historical runs against the initial baseline;
the superseding integrated acceptance is recorded below.
The initial implementation run returned 244 passed. After the follow-up fixes below,
the expanded focused run returned **326 passed**, exit **0**. From this successor
worktree it used the already prepared root-checkout Python environment with this
argv; no installation, native host, account import, or live network was used:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../../../.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_termcfg_guidance.py tests/test_termcfg_interaction.py tests/test_termcfg_interaction_failures.py tests/test_termcfg_presentation.py \
  tests/test_termcfg_apply.py tests/test_termcfg_catalog.py tests/test_termcfg_drift.py \
  tests/test_termcfg_init_local.py tests/test_termcfg_interrupt.py tests/test_termcfg_migration.py \
  tests/test_termcfg_packages.py tests/test_termcfg_plan.py tests/test_termcfg_recovery.py \
  tests/test_termcfg_security.py tests/test_termcfg_shell_environment.py tests/test_termcfg_status.py \
  tests/test_agentcfg_interaction.py tests/test_agentcfg_doctor_identity.py tests/test_presentation.py \
  tests/test_cli.py::test_cli_help_needs_no_local \
  tests/test_omp_profiles.py::test_identity_diagnostics_reports_default_keybindings_digest_without_modifying_it \
  tests/test_omp_profiles.py::test_profile_rename_creates_new_identity_and_diagnostic_migration_hint
```

The broader existing agent CLI run used the same environment and these arguments:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../../../.venv/bin/python -m pytest -q -p no:cacheprovider --tb=short \
  tests/test_setup_cli.py tests/test_cli_presentation.py tests/test_cli.py
```

That run initially returned **51 passed, 87 failed**, exit **1**. One additional
failure was the missing bare-entry `usage:` header; it was corrected and the
existing four help cases were rechecked, including in the final passing run above.
The other **86** failures stopped at initialization/private-path safety checks
(returning 4). The earlier unchanged-main review had the same 86 failures, with
52 passing cases. A metadata-only probe found that the original executor's root
ownership was neither root nor the effective user. Those runs therefore did not
validate the private-state cases. The later controlled full run below closes this
gap without changing the original unsupported namespace's trust classification.
The [test environment requirements](../testing.md#default-offline-suite) remain in
force; no ownership, ancestor, symlink, permission guard or isolation fixture was
weakened.

A separate state-free syntax matrix compared the candidate with the baseline HEAD
parser: **235 agentcfg** and **243 termcfg** cases retained acceptance, namespace
values and exit behavior. Help/error wording was intentionally excluded from this
comparison; no commands were dispatched.

### Follow-up acceptance review and fixes

A further independent review traced actual collectors and failure paths, rather than
relying only on synthetic output payloads. It found six first-delivery omissions;
all six now have targeted fixes and regression coverage:

| Omission | Correction and evidence |
| --- | --- |
| OMP doctor hid collected identity/layout conflicts while showing offline-ready | Human output projects only known identity/plan-path conflict enums, limits its title and subsequent actions, and labels planned environment evidence as not deployed. `test_agentcfg_doctor_identity.py` has 24 cases using real temporary-directory identity collection, exact unchanged JSON, and no-I/O presentation sentinels. |
| General legacy entries suggested migration without checking pending recovery | Unknown recovery state first suggests scoped status; the existing failure diagnostic can expose a strictly validated legacy journal. CLI tests cover both legacy sources, six entry points, and human/JSON output. |
| A recovery target drift refusal was overwritten by another recover suggestion | Failed recovery keeps a scoped read-only status suggestion while retaining the journal/partial-effect warning. A real interrupted apply and external target edit reproduce this path. |
| Cached plugin activation could report that selection had not activated after replacement | Cached activation now records the same activate stage as a fresh download. Tests switch between two real synthetic cached groups, interrupt after replacement, and forbid another download. |
| Cleanup interruption after apply/rollback commit could report unchanged HOME | Failure diagnostics conservatively preserve possible effects after write/commit stages, even after journal removal; human output says cleanup/final state is unverified. Tests check the actual changed target and state. |
| First initialization cancellation incorrectly suggested edit | The hint uses the already observed existence of the machine; creation retries do not contain `--edit`, while editing retries do. Both modes and output formats leave the original files unchanged. |

The terminal follow-up contracts (`test_termcfg_interaction_failures.py` plus the
cached-activation tests in `test_termcfg_packages.py`) initially returned **34 failed,
2 passed**, exit **1**, reproducing the five terminal omissions. After the fixes,
the focused group with existing interaction/presentation/migration cases returned
**114 passed**, exit **0**. The OMP identity title case likewise failed before its
fix and passed afterward. All follow-up tests are included in the 326-pass run.

The OMP tests cover real identity collection into a synthetic doctor envelope and
the real presentation path; they do **not** replace full `cmd_doctor`, CLI or lifecycle
validation. The second independent read-only review found no remaining blocking
issue in the six corrected paths and no weakened safety checks.

### Acceptance after main integration

The candidate was fast-forwarded to `a84710a98d1a687edb5033728178bf52ebc32214`
after verifying a private backup of its staged patch and index. The patch was
replayed without a new commit. The two CLI conflicts preserve main's strict,
on-demand HOME/XDG discovery and fixed `unsupported-root-owner` propagation,
while retaining typed hints and interaction help. Main's parallel, uncommitted
work was not absorbed or modified; the old worktree's staged patch is unchanged.

Integration also adds fixed human explanations for `invalid_home` and the four
`invalid_xdg_*_home` reasons, including nested component blockers. These are
presentation-only prerequisites, not environment reads or a JSON change:
`--home` changes a diagnostic target, not invalid process HOME/XDG discovery.
The 86 new cases in `test_cli_environment_interaction.py` cover that separation,
help without private discovery, initialization before lease/input, saved edit
state, and synthetic root-error propagation. The latter is not real filesystem
acceptance. The focused integration group returned **269 passed**, exit **0**.

The formal entry was then invoked from the candidate's own script with the
prepared repository Python environment and explicit sandbox opt-in. Sanitized
command shape (absolute `VENV` and new private `EVIDENCE` selected beforehand;
exact argv retained privately):

```sh
PYTHONDONTWRITEBYTECODE=1 ../../../.venv/bin/python scripts/test-sandboxed.py \
  --allow-sandbox --suite full --venv "${VENV:?}" --evidence "${EVIDENCE:?}"
```

The controlled Linux user-namespace baseline returned **0**, with all 14 checks
true: selected Python/venv, trusted root ownership, synthetic HOME, hidden Git/cache,
real private create/read modes, symlink/hardlink rejection, read-only root/source/
venv/toolchain and the fixed blocked network probe. Network isolation is provided
by the executor's network namespace, not inferred solely from one failed probe.
No production path guard, UID result or pytest isolation fixture was weakened.
The original unsupported namespace remains unsupported; this is evidence for the
new controlled executor, not a repair of its outer root ownership.

The subsequent fixed full pytest command returned **0**: **4296 passed,
13 skipped, 7 subtests passed in 1644.63 seconds**. JUnit records confirm:

| Suite | Passed | Failed/error/skipped |
| --- | ---: | ---: |
| `test_setup_cli.py` | 21 | 0 |
| `test_cli_presentation.py` | 8 | 0 |
| `test_cli.py` | 109 | 0 |
| `test_paths.py` | 91 | 0 |
| `test_execution_environment.py` | 31 | 0 |
| `test_cli_environment_interaction.py` | 86 | 0 |

The original three-file agent CLI suite therefore has **138 actual passes and
no skips**; its previously blocked 86 cases are now validated. The new 86-case
environment-interaction file is separate evidence, not a substitute for them.

All 13 skips remain **NOT RUN**, not passes: seven retired historical OMP
host-patch cases; one unavailable locked standalone Bun asset; one unavailable
pinned SDK source; and four Pi cursor/readseek cases lacking Node or rg/Node in
the controlled executor. These do not validate those TypeScript integrations.
Native agents, real authentication, live shell/tmux sessions and other platforms
remain outside this first-delivery offline acceptance; nothing was deployed.

Private evidence record `cli-ux-validation-acrrrm6_` retains the candidate,
entry/stage argv, baseline/pytest exit records, logs, JUnit XML and source manifest.
The tested uncommitted snapshot has 2944 tracked files and source SHA-256
`9234caa235d5460868d8d2816ae82b63f16a6deecf9e78ade01d7674fb157428`.
All snapshot bytes and modes matched the frozen candidate after the run, including
all 31 task files and the new tests. Its 61 lock-identity entries have digest
`05d28a501e84fe2ec8c5d7e0124a272e29d124eb094f7ecf392d229e328c9ac3`
(SHA-256 of sorted-key JSON); no lock changed from the recorded main commit.
At that acceptance checkpoint, only this evidence prose and roadmap status were
amended afterward; document/link and whitespace checks were rerun, and all
non-document source and lock bytes and modes matched the tested manifest.
The later final-review corrections below have separate affected-check evidence;
the full-run digest is not presented as the final corrected source digest.

A further dispatch-free comparison against the integrated main parser covered
**276 agentcfg** and **156 termcfg** cases with unchanged acceptance, namespaces
and exit behavior; help/error wording is intentionally excluded. Final independent
read-only review found no new blocker in the scoped discovery, recovery,
side-effect, JSON and guidance contracts. The 25 changed Python files also passed
syntax checks. The six follow-up defects and first-delivery acceptance are closed.
The conditional APIs remain unimplemented. This checkpoint preceded commit and
integration authorization. Any integration must still bind validation to the
prepared commit and preserve unrelated work against the current main.

### Final pre-integration review

Two independent final reviews found no execution or authorization blocker and two
low-priority human-output issues. Both were corrected rather than waived:

- Agent help now limits native-tail transparency to the CLI parsing layer;
  existing managed-identity, credential and adapter boundary checks still apply.
  `usage --help` remains native, not manager-local help. Three new static-help
  cases failed before this wording correction; the corresponding focused group
  then returned **140 passed**, exit **0**.
- A legitimate diagnostic HOME containing control characters could be quoted
  correctly by typed guidance but then changed by human terminal escaping. The
  renderer now warns that such a suggestion cannot be copied faithfully and
  offers only registered local help, without printing a rewritten command.
  It does not parse arbitrary command strings or modify JSON, the original HOME,
  execution or write authority. The display-only `rollback-plan` label maps to
  `rollback --help`; unknown labels use root help. Literal backslashes remain
  literal. Thirty tests covering top/component slots and real temporary owned
  HOME paths across doctor/status/plan failed before the fix and passed afterward.

The final affected regression run returned **615 passed, no failures or skips**,
exit **0**, in **25.80 seconds**. It covers all terminal tests, agent interaction
and human presentation, environment discovery, parser/help boundaries and managed
native-tail refusal/query grammar. It uses the ordinary isolated offline fixtures,
not another controlled full-suite invocation or a native/real-account smoke.
The earlier controlled full result and this affected result are distinct. At this
review checkpoint on `a84710a`, the full suite had not yet been rerun after the
human-output-only corrections; the main-advance refresh below supersedes that
integration state.

Private `precommit-final-run` evidence retains the exact argv, exit status and
31-file candidate manifest, with the corresponding log and JUnit XML. At that
checkpoint, the only runtime changes after the controlled full snapshot were
`src/agentcfg/cli_help.py` and `src/termcfg/presentation.py`, accompanied by their
three regression files and the two evidence/status documents. The remaining
snapshot bytes/modes, execution guards, isolation fixtures, schemas and locks
matched that snapshot. No push or deployment is part of this delivery.

### Validation refresh after main advanced

Before any CLI commit, the target main advanced to
`9ab90f553417b0b81ea28d4b9e9f78ddbd4be845`, adding the DSH runtime upgrade and
headless SSH integration. Its 44 paths did not overlap the 31 CLI task paths.
A dry-run followed by an ordinary fast-forward aligned the candidate while
preserving every staged and unstaged CLI patch byte. Main was clean afterward;
no parallel work or old-worktree history was absorbed into a CLI commit.
Independent read-only interaction review found no new CLI compatibility blocker.

The renewed controlled full run, private record
`cli-ux-final-validation-3jv5atdf`, returned **FAIL / offline_pytest_failed**, exit
**1**: **4384 passed, 1 failed, 13 skipped, 7 subtests passed** in **1776.91 seconds**.
Its actual isolation baseline passed all 14 checks. The sole failing test,
`test_defaults_apply_to_future_profile_and_profile_local_roles_win`, was then
reproduced unchanged on clean main, also exit **1**. This failed run is retained,
not relabeled as passing evidence.

The main update intentionally moved `codex`/`cursor` from adapter-wide defaults
into the explicit `dsh-default` profile. The synthetic future-profile fixture
replaces that profile's provider list, so its old expectation of automatically
inheriting those OAuth providers was stale. Only `tests/test_model_defaults.py`
was corrected. Its provider expectation now contains the exact three API entries;
the eight-model list, main-role check and both provenance assertions are retained.
Five new pure-resolver cases protect profile-explicit selection.
The new cases cover the default profile, an unchanged copied choice, no OAuth
choice, both explicit choices, and one explicit choice; API-only local lists
still append rather than remove a profile's OAuth choice. Selected entity keys
are checked too. No production resolver, source recipe, guard or lock was changed.
The pure affected group returned **9 passed**, exit **0**, in **7.88 seconds**;
independent review found no remaining issue in this test-only correction.

The user requested another complete controlled full run, rather than accepting
only the focused closure. Private record `cli-ux-acceptance-8fty0ffv` now records
**PASS / offline_pytest_complete** for that complete rerun:

- Actual isolation baseline: exit **0**, **0.37 seconds**, all 14 checks true.
- Pytest stage: exit **0**, **1859.91 seconds**.
- Pytest summary: **4390 passed, 13 skipped, 7 subtests passed** in **1858.86 seconds**.
- Source snapshot: **2965 files**, SHA-256
  `f0db7abf381993d89587f2839aca226edb335a31ef25b9a61c0d5a43b978446c`.
- Lock identity: **68 entries**, sorted-key JSON SHA-256
  `8137a409df0d5eb00a22effb00951b96729ce68e8c5be78a33bec85b2297b778`.

The entry and both stage argv, exit records, logs and JUnit are retained privately.
The same 13 explicitly unexecuted cases remain: seven retired OMP host-patch
integrations, two standalone OMP asset/source gaps and four Pi Node/rg cases.
They are not counted as passing, and no native, real-account or additional-platform
acceptance is inferred. The original unsupported executor remains unsupported;
the controlled namespace and its measured baseline are the acceptance scope.

The final task has 32 paths, including the test-only integration correction.
Runtime and test bytes/modes remain frozen at this full-run snapshot; only this
progress/evidence document and roadmap status were amended during/after the run.
Final syntax, document/link, staged-content and whitespace checks cover those
amendments. Before the authorized fast-forward, the prepared commit must bind to
this snapshot and unchanged target main, with the approved public Git identity
and old-worktree preservation rechecked. No push or deployment is included.
