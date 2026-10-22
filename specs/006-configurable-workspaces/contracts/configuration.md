# Configuration contract (implemented; native acceptance separate)

This implementation contract refines [the specification](../spec.md) and [research](../research.md). It describes current validation and saving behavior; structured mode still requires explicit opt-in and this file does not deploy it. See [CLI](cli.md), [lifecycle](lifecycle.md) and [data model](../data-model.md) for related contracts.

## Selection and compatibility

Use the existing machine-private TOML selected by global `--machine ID` or `--local FILE`, which are mutually exclusive. With neither, retain the current default-selection rules; do not persist an implicit selection. No project database is introduced. The containing document retains `schema_version = 1` and the existing machine schema. Existing machine IDs and shared profile identifiers retain their current validation.

`machine.work.model = "structured-v1"` is the explicit opt-in. Without `model`, retain the legacy Git-only seven-role contract. Structured-only fields (`include_rotom`, `rotom_template`, `sources`, `templates`, `workspaces`) without that opt-in fail. An unknown model or invalid structured document fails without legacy fallback. Loading configuration does not migrate, adopt, restart, ungroup or rebind active work.

Every object rejects unknown fields, including nested source, template, type, cwd and workspace objects. New source IDs, template keys, type keys and named IDs match `^[A-Za-z][A-Za-z0-9_-]{0,63}$`. Duplicate IDs and ambiguous definitions fail. Keys, identifiers and published example comments use ASCII; literal Unicode paths, titles and existing comments remain supported as data.

## Fields

| Object | Accepted fields and rules |
| --- | --- |
| `machine.work` | `model`, `herdr_binary`, `session`, `pi_profile`, `dsh_profile`, `codex_binary`, `codex_daemon`, `include_rotom`, `rotom_template`, `sources`, `templates`, `workspaces` |
| Existing launch fields | `herdr_binary` and `session` remain required; existing executable/session/profile validation applies. `codex_daemon` defaults to `false`. Pi/DSH profiles must be explicitly selected when their launcher is used; no profile guessing. |
| Built-in candidate | `include_rotom` defaults to `true`; `rotom_template` defaults to `"development"`. No template is injected. Enabled inclusion requires a defined template even if a higher-priority candidate wins. Disabled inclusion with omitted `rotom_template` imposes no implicit reference; an explicit value always validates. |
| Source | Required `id`, `path`, `mode`, `template`; `mode` is `git` or `directory`. Optional `depth` is an integer from 1 through 32, default 1; `exclude_hidden` defaults to `true`; `exclude` is an array of basename globs, default empty; `follow_symlinks` defaults to `false`. |
| Template | Keyed under `templates`; required `order`, `initial`, `tab_types`. `order` is duplicate-free and its set equals the type-key set exactly. `initial` references one defined type. No semantic TOML table ordering. |
| Type | Required `label`, `launcher`; optional `cwd`. Launcher is exactly `shell`, `editor`, `pi`, `dsh` or `codex`. Labels are nonempty literal text. No command strings or additional launcher options. |
| Type cwd | Omitted means `{ from = "workspace_start" }`. Accept exactly that form or `{ path = "literal" }`; mixed forms, empty paths and other selectors fail. |
| Project workspace | Required `kind = "project"`, `path`, `mode`, `template`; no `id` or title. Path must exist; mode is explicitly `git` or `directory`. |
| Named workspace | Required `kind = "named"`, `id`, `title`, `template`; optional existing `start_path`. No project path/mode. Title is nonempty literal text. Omitted start means caller HOME. |

Configuration `source.path`, project `path` and explicit named `start_path` accept absolute, `~/` and relative literal paths. Relative values resolve against the selected local TOML file's parent directory; `~/` uses caller HOME. Explicit CLI/TUI paths instead resolve against invocation cwd and are saved as canonical absolute paths. Sources and projects must resolve to existing canonical directories. Git mode resolves a selected subdirectory to its checkout root and previews the actual registration; directory mode retains its selected boundary inside a larger checkout. Rereading configuration may resolve changed paths, but does not change active bindings.

A project's workspace start is its canonical project boundary. A named context captures caller HOME at first entry when `start_path` is omitted, or captures its resolved explicit start then. Only `type.cwd.path` resolves relative values against that fixed workspace start; its `~/` expansion captures caller HOME at first type binding. Absolute values remain absolute. No other expansion/evaluation or directory creation occurs. Missing or unusable directories fail without fallback. Later configuration reads and changes to cwd/HOME do not alter active workspace/type bindings.

`editor` uses the existing single executable in `machine.editor`, without shell parsing. Pi and DSH use their explicitly chosen managed profiles; Codex uses its existing independent CLI contract. Check the preparation needed for the selected launch only when launching it. A shell-only workflow does not require an unused editor or Agent to be prepared. Offline configuration checks validate declared structure, references and paths, without credential loading, dependency installation or host execution.

## Discovery and identity

Depth 1 enumerates direct children, never the source root itself. Git sources recognize checkout roots, including `.git` files, without following external worktree metadata or treating checkout subdirectories as separate projects. Directory sources enumerate independent child boundaries. Hidden and basename-glob exclusions prune discovery. With symlink following enabled, canonical targets must still remain inside the canonical source root and traversal must detect cycles; enabling it never grants external coverage.

Deduplicate by canonical project boundary: explicit project entry outranks the most specific matching source, which outranks the verified executing Rotom checkout candidate. Incompatible equal-priority definitions fail. Compatible repeat registrations are idempotent. Show path alongside duplicate display names. An unverifiable built-in root yields a diagnostic while other candidates remain usable; never infer it from PWD or a guessed main checkout. No watcher or whole-HOME scan is introduced.

Directory identity is verified endpoint plus canonical project boundary, independently for each checkout. Named identity is verified endpoint plus stable local ID. Titles, current cwd, branch, shared HOME and Git common directory do not merge identities. At initial entry create exactly one default instance of the template's initial type; other types are on demand. First instantiation fixes that type's resolved cwd and launcher contract. Extras reuse it after runtime `cd`; focus injects no input. Configuration drift preserves existing focusable instances and blocks contradictory new creation until explicit safe rebind or a new workspace. `problem1` through `problem3` denote instances of one `problem` type.

In structured mode, `--new` always creates an extra, even before a default exists. It never promotes that extra to default; a later plain open creates the default safely using the same fixed binding. Legacy behavior is unchanged. Endpoint identity uses the canonical discovered socket address, so aliases of the selected local configuration do not split one endpoint's identities. Private binding/receipt storage under `$XDG_STATE_HOME/rotom/work/v2` is not a project registry. Socket identity evidence and a random workspace epoch support verification; a lost native marker after cold restore leaves stale/unknown ownership, never automatic adoption.

## Saving and editing

CLI, selector and `work config edit` validate the same complete proposed document and use one stable configuration lock keyed by canonical selection. Hold the lock throughout fragment editing, validation and publication. Direct manual editing remains supported between saves; users avoid overlapping it with saves. Observed external changes cause refusal. Advisory locking and atomic replacement do not provide compare-and-swap against an editor ignoring that convention in the final replacement window.

Preserve unrelated content, comments and original permissions; enforce existing private ownership/link boundaries and use a same-directory temporary file plus atomic replacement. Do not digest secret-bearing whole files or create generic backups/editor copies of them. `work config edit` stages only the non-secret `machine.work` fragment in private storage and invokes `machine.editor` as one executable. It never opens the whole machine file or installs an editor. Invalid edits leave the original intact. Unsafe/read-only saves provide a diagnostic and a manual work fragment without partial write or false success. Saving completes before any separate native/Git lock or lifecycle preview; do not nest those locks. No-op saves leave bytes unchanged.

Registration previews show the resulting canonical candidates with mode, template, origin and path, including an explicit zero-candidate count. Discovery diagnostics appear before confirmation and in the selector/configuration check; an unverifiable built-in root does not hide other valid candidates. Preview results are not saved as an inventory.

When initial private-file checks reject configuration, no body is read or permission repaired. Complete explicit add inputs can produce a standalone `machine.work.sources` or `machine.work.workspaces` fragment; its header requires manual merge and states that existing template references and conflicts remain unverified. Invalid explicit data produces only correction guidance. `config edit` without safely validated work data emits commented editing guidance rather than invented configuration or an editor launch. A safe 0600 configuration whose publication fails retains the validated work proposal as its manual fragment. All refusal paths keep the failure exit code and avoid claiming a completed save.

Saving registration is separate from entry: it creates no checkout, directory or native object and launches no shell/editor/Agent, except the expressly requested fragment editor. Dry run and cancellation before confirmation write no configuration, new lock file or operation receipt. A separately confirmed source save remains saved if a later worktree creation is cancelled.

## Complete illustrative document

This is illustrative input requiring real local path/tool substitutions, not a deployed configuration. Paths are fictitious; replace them with existing temporary fixture paths before future validation. These `dev5` and `investigation3` templates are explicit local examples, not injected defaults. Both named contexts below start at the same caller HOME and remain independent. All type cwd values use workspace start, so there are no additional literal-path requirements.

```toml
schema_version = 1

[machine]
id = "workstation"
editor = "fixture-editor"

[machine.work]
model = "structured-v1"
herdr_binary = "fixture-herdr"
session = "structured-trial"
pi_profile = "pi-base"
dsh_profile = "dsh-default"
codex_binary = "fixture-codex"
codex_daemon = false
include_rotom = true
rotom_template = "dev5"

[[machine.work.sources]]
id = "projects"
path = "/projects"
mode = "git"
depth = 1
template = "dev5"
exclude_hidden = true
exclude = ["cache", ".cache"]
follow_symlinks = false

[[machine.work.sources]]
id = "cases"
path = "/cases"
mode = "directory"
depth = 1
template = "investigation3"
exclude_hidden = true
exclude = ["cache"]
follow_symlinks = false

[machine.work.templates.dev5]
order = ["shell", "edit", "build", "test", "agent"]
initial = "shell"

[machine.work.templates.dev5.tab_types.shell]
label = "Shell"
launcher = "shell"

[machine.work.templates.dev5.tab_types.edit]
label = "Editor"
launcher = "editor"
cwd = { from = "workspace_start" }

[machine.work.templates.dev5.tab_types.build]
label = "Build"
launcher = "shell"

[machine.work.templates.dev5.tab_types.test]
label = "Test"
launcher = "shell"

[machine.work.templates.dev5.tab_types.agent]
label = "Agent"
launcher = "pi"

[machine.work.templates.investigation3]
order = ["code", "agent", "problem"]
initial = "problem"

[machine.work.templates.investigation3.tab_types.code]
label = "Code"
launcher = "editor"

[machine.work.templates.investigation3.tab_types.agent]
label = "Agent"
launcher = "dsh"

[machine.work.templates.investigation3.tab_types.problem]
label = "Problem"
launcher = "shell"

[[machine.work.workspaces]]
kind = "project"
path = "/cases/current"
mode = "directory"
template = "investigation3"

[[machine.work.workspaces]]
kind = "named"
id = "investigation-main"
title = "Investigation"
template = "investigation3"

[[machine.work.workspaces]]
kind = "named"
id = "investigation-secondary"
title = "Second investigation"
template = "investigation3"
```
