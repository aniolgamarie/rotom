# Configurable workspace interactions

This page describes the implemented Rotom selection flow. Screens below are explanatory sketches, not captured Herdr screens. The feature has isolated test coverage; native acceptance and deployment of this iteration remain outstanding. See the [usage guide](../herdr-workspaces.md) and [design boundaries](configurable-workspaces.md).

All commands assume an already prepared `work` entry and private machine configuration. Paths, IDs and labels are public examples. Interactive selection requires a prepared compatible fzf; complete CLI commands and direct TOML editing remain available without it. Nothing installs fzf or starts a tool merely to fill a candidate list.

## Choose a project or context

Run `work --machine workstation` after explicitly configuring `model = "structured-v1"`.

```text
Project >
  Rotom | project | /projects/rotom | development | builtin
  kernel | project | /projects/kernel | development | source
  current | project | /cases/current | investigation | explicit
  Investigation | named | investigation-main | investigation | explicit
  + Import search path
  + Import directory
  + Named workspace
  + New Git worktree
  Refresh
  Edit workspace configuration
  Read-only live status / unknown outcomes
  Rename named workspace
  Review current workspace close scope (guard unavailable)
```

Selecting a candidate requests ordinary entry. An initial workspace contains only its template's `initial` tab instance. Development defines five types (`shell`, `edit`, `build`, `test`, `agent`); investigation defines three (`code`, `agent`, `problem`). Other types appear on demand. Herdr owns the workspace/tab/pane layout and native navigation.

The built-in Rotom entry uses the verified checkout containing the executing entry, not invocation cwd or an assumed installation location. It does not write an explicit project entry. An explicit project wins over a source; the most specific matching source wins over a broader source; the built-in is a fallback. Refresh re-enumerates configured roots, without a background watcher or whole-HOME search.

Esc cancels the current selection; text prompts also accept EOF cancellation. Cancellation before saving or dispatch creates no workspace, branch or checkout. A separately confirmed earlier configuration save stays saved.

## Import a search path or one directory

```text
+ Import search path
  id: projects
  path: /projects
  Mode > Git checkout root
  Template > development
  Review machine.work fragment
  Review > Confirm: Save configuration only

+ Import directory
  path: /cases/current
  Mode > Selected directory boundary
  Template > investigation
  Review machine.work fragment
  Review > Confirm: Save configuration only
```

Search-path import saves a rule, rather than a snapshot of discovered projects. Interactive registration uses the source defaults: depth 1, hidden entries excluded, no symlink traversal and no extra basename exclusions. Use CLI flags or TOML for other policies. The source root itself is not a candidate. Git mode includes child checkouts with `.git` directories or valid `.git` files; directory mode preserves independent selected boundaries, including directories inside a larger repository.

Single-project import requires an existing path. In Git mode, selecting a subdirectory resolves and previews its actual checkout root; directory mode retains the exact canonical directory. Importing an existing worktree does not create a branch or checkout. Saving does not start Herdr, shells, editors or Agents.

The same operations are available without fzf:

```sh
work --machine workstation source add --id projects --path /projects --mode git --depth 1 --template development --dry-run
work --machine workstation source add --id projects --path /projects --mode git --depth 1 --template development
work --machine workstation project add --path /cases/current --mode directory --template investigation
work --machine workstation list --json
```

A complete add command authorizes its configuration save; `--dry-run` previews only. Missing required arguments fail rather than prompting in a noninteractive invocation. Imported projects and roots must exist; no future-project catalog is created.

## Create or rename a named workspace

```text
+ Named workspace
  id: investigation-main
  title: Investigation
  start_path: [leave empty]
  Template > investigation
  Review > Confirm: Save configuration only
```

A named workspace needs no project directory or problem binding. Empty `start_path` means capture HOME on first entry. A provided path must already exist. ID, title and start directory have separate roles: rename changes presentation while retaining identity; equal start directories do not merge different named IDs.

```sh
work --machine workstation named add --id investigation-main --title Investigation --template investigation
work --machine workstation named enter investigation-main
work --machine workstation named rename investigation-main --title Followup --dry-run
work --machine workstation named rename investigation-main --title Followup
```

Rename saves the title first, then updates an already verified live workspace when available. A native-update failure leaves the saved title and reports presentation pending or unknown, rather than claiming rollback or creating a replacement workspace.

## Configure through CLI, editor or TOML

These three entrances share the private machine document and strict validation:

| Entrance | Action |
| --- | --- |
| Selector | Review and confirm registration fragments |
| Explicit CLI | Supply full values; use `--dry-run` before a save |
| TOML/editor | Edit the same document, or `config edit` for the non-secret work fragment |

```sh
work --machine workstation config edit
work --machine workstation config check
```

The editor receives only `machine.work`, using the configured single executable. Other machine fields and credentials are not staged in the editor fragment. Saves preserve unrelated content and comments, check ownership/permissions and concurrent changes, then publish atomically. Unsafe/read-only saves provide a diagnostic and manual fragment. Validation does not silently migrate legacy configuration or guess a template/profile. The [complete example](../../examples/work-structured.toml) includes opt-in and both templates; replace its fixture paths and executables before use.

## Open a default or an extra instance

Inside the selected workspace's usable shell, run `work --machine workstation open`.

```text
Terminal type >
  Shell | Default: focus or create
  Editor | Default: focus or create
  Build | Default: focus or create
  Test | Default: focus or create
  Agent | Default: focus or create
  Build | default | tab-reference | verify before focus
  Build | extra | tab-reference | verify before focus
  Build | Review explicit rebind (requires zero active instances)
```

The sketch combines possible rows; uncreated types have no recorded instances. Selecting an instance verifies live ownership and membership before focus. Hand-created tabs and splits remain available through native navigation and are not silently adopted as managed types.

A type removed from the current template appears only through recorded instance rows labelled `Removed type: focus only`; it has no create or rebind action. It is absent from the `open --new` selector, and absent from ordinary selection when no recorded instance remains. The selected instance still requires live verification before focus.

```sh
work --machine workstation open build
work --machine workstation open build --new
work --machine workstation open --new
```

Ordinary open focuses the verified default or creates it. Every `--new` creates an extra, including when no default exists. An extra never becomes the default automatically. Existing focus does not execute commands, reset cwd or restart a program. A shell launcher attached to `build` or `test` waits for commands from the user.

First instantiation fixes type cwd, captured HOME and relevant launch contract. Omitted cwd equals `cwd = { from = "workspace_start" }`; relative `path` uses that fixed start, and `~/` uses captured HOME. Later runtime `cd` or a different caller HOME does not redirect extras. Configuration drift preserves verified focus but blocks contradictory creation. Removed definitions remain focusable through their existing binding, while new creation requires a current definition.

Rebind previews the new launch contract and requires zero active instances with no unresolved handoff. Interactive confirmation authorizes replacement; noninteractive use needs `work --machine workstation rebind TYPE --accept`. It never closes a running instance to make rebind eligible.

## Create a Git worktree

```text
+ New Git worktree
  Registered Git repository > kernel
  Branch mode > New local branch from explicit local base
  Branch name: fix-example
  Local base: refs/heads/main
  Destination: /projects/kernel-fix
  Template > development
  Review repository, destination, resolved commit and template
  Confirm > Create only
          > Create, then enter workspace
          > Cancel
```

The repository must be registered through an explicit Git project or Git source. A built-in Rotom entry alone is insufficient. Destination must not exist, its parent must exist, and visible configured-source coverage must allow the exact destination under depth, hidden, exclusion and symlink rules.

If coverage is missing, the form offers a separate parent-source save:

```text
Review > Separately import destination parent as Git search path
  New source ID: additional-projects
  Review source fragment
Review > Save parent source only; checkout creation still requires review
  Read fresh configuration
  Make a new creation preview
Confirm > Create only / Create, then enter workspace / Cancel
```

Canceling at the final step keeps the earlier confirmed source save but creates no branch, checkout or workspace. The save is not permission to create later without a fresh review. CLI users can perform the same source add separately, then rerun worktree preview.

```sh
work --machine workstation worktree create --repo /projects/kernel --path /projects/kernel-fix --template development --new-branch fix-example --base refs/heads/main --dry-run
```

Remove `--dry-run` to authorize the reviewed creation. Add `--enter` only if workspace entry is also requested. Creation otherwise finishes without starting Herdr. If entry fails after successful Git creation, the checkout stays and explicit `enter` retry guidance is printed.

Existing-branch mode remains visible as a capability-limited choice: read-only preview is available, but dispatch currently returns 5 because Git's public short-branch interface lacks the required atomic guard against deletion and remote-tracking fallback. No successful existing-branch creation is claimed. New-branch mode and importing an existing checkout are separate supported paths. This release treats existing-branch dispatch as unsupported; enabling it in the future requires a public atomic guard and explicit review.

Creation rechecks reviewed facts immediately before its one dispatch. Dirty work stays in the original checkout; hooks, external fsmonitor and recursive submodule actions are disabled per invocation. Executable checkout filters are refused. No fetch, bootstrap, dependency installation, stash, reset, force or automatic deletion is performed. Timeout/nonzero/uncertain results retain partial effects and records, rather than retrying creation.

## Review close scope and inspect unknown results

The selector's close action runs a read-only preview:

```sh
work --machine workstation close --dry-run
```

It lists the current workspace's complete tab/pane membership, including manual members, and shows that all viewers would be affected. The reviewed scope excludes sibling workspaces, checkout files, branches, saved configuration and the server itself.

**Current capability: unavailable.** The admitted public native API has no atomic membership guard. Even `close --scope TOKEN --yes` rechecks scope then returns 5 without a destructive request. A successful preview is not a successful workspace close. Detach leaves tasks running; collapsing a UI item only changes presentation. Neither operation means close completed.

```sh
work --machine workstation status --json
work --machine workstation reconcile --json
work --machine workstation list --live --json
```

These commands report observations without clearing unknown results, retrying mutations, closing tasks or rewriting receipts. Display labels, environment IDs and private records alone do not prove ownership. Unknown membership or handoff results stay unknown and require review. Native deployment, acceptance and any migration remain separate authorized work.
