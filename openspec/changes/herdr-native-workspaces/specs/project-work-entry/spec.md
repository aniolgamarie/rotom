## ADDED Requirements

### Requirement: Project identity is the canonical checkout within one server

The first implementation SHALL accept Git checkout paths only and use the actual checkout root after resolving symlinks, scoped to one explicitly selected Herdr server. A Git worktree SHALL use its own top level, not its common Git directory. Names, branches, pane titles and current shell cwd SHALL NOT replace project identity. Automatic non-Git project binding SHALL remain unsupported until a separate native identity contract is established.

#### Scenario: A non-Git directory is selected

- **WHEN** `work enter PATH` receives an existing directory outside a Git checkout
- **THEN** it exits 2 before starting or mutating a server, explains the initial Git-only scope, and directs the user to the native temporary workspace workflow

#### Scenario: Two worktrees or repositories share a display name

- **WHEN** their canonical checkout paths differ
- **THEN** they enter separate workspaces

#### Scenario: A project is entered through a symlink or a subdirectory

- **WHEN** both selections resolve to the same checkout root
- **THEN** they find the same workspace; spaces and Unicode remain literal path data

#### Scenario: The shell visits an external build directory

- **WHEN** a pane changes its cwd without an explicit project operation
- **THEN** its project association is unchanged

### Requirement: Enter is duplicate resistant and fails safely on uncertainty

`work enter PATH` SHALL find and focus the matching workspace, creating only when absence is established. Concurrent calls from this entry SHALL serialize query/create within the same server. An API request ID SHALL NOT be assumed to provide idempotency. Conflicting native objects or uncertain creation SHALL be reported before another mutation.

#### Scenario: Two entries target the same checkout concurrently

- **WHEN** both use the same configured server
- **THEN** only one managed project workspace is created and both resolve its returned native identity

#### Scenario: A create request times out after reaching the server

- **WHEN** the result is unknown
- **THEN** the entry queries current native state and either reconciles a provable result or returns an unresolved-operation conflict; it does not blindly create again

#### Scenario: The server is restarted and identity cannot be proved

- **WHEN** restored native metadata cannot establish the original project association
- **THEN** the entry reports the limitation without guessing from a title, dynamic cwd or numeric ID reused by the new server

### Requirement: Open reuses stable purposes without executing into existing work

`work open ROLE` SHALL support `shell`, `edit`, `build`, `debug`, `pi`, `codex` and `dsh`. It SHALL focus a proven managed primary instance when one exists; `--new` SHALL create an additional instance without replacing an existing proven primary. If no primary can be proved after a cold restore, an explicit `--new` SHALL establish a new primary for that role while leaving restored terminals unmanaged. Build/debug/shell SHALL start ordinary interactive shells, not inferred build or debugger commands. Unmanaged native panes SHALL NOT be adopted by matching names. Unknown role identity SHALL NOT be treated as confirmed absence.

#### Scenario: A cold restore has cleared role metadata

- **WHEN** restored panes exist but `work open build` cannot prove the current role identity
- **THEN** it exits 4 with an explanation, without adopting, closing or creating a terminal; the user may use native navigation or explicitly request `--new`

#### Scenario: A new role is explicitly requested after a cold restore

- **WHEN** role identity is unknown and the user invokes `work open build --new`
- **THEN** it creates and marks a fresh instance for that role without touching restored panes; future calls may reuse the newly proved primary

#### Scenario: A build pane is busy

- **WHEN** `work open build` is invoked again
- **THEN** the entry only focuses it and does not type a command, send Enter, interrupt it or change its cwd

#### Scenario: A second Agent instance is requested

- **WHEN** `work open pi --new` is invoked
- **THEN** it creates a new instance without replacing the primary or its state

### Requirement: Launch arguments survive the entire native path

Executable paths and arguments SHALL remain data through the final process launch, using a verified public native interface. Calling Herdr itself with an argv array SHALL NOT alone establish this property. If the selected release internally requires a shell string, the implementation SHALL use a single documented quoting boundary on a newly created owned terminal and verify adversarial path cases; it SHALL NOT use eval or type launch commands into reused terminals.

#### Scenario: A checkout path contains shell metacharacters

- **WHEN** an editor or Agent starts in that checkout
- **THEN** spaces, Unicode, quotes, dollar syntax and backticks remain literal, or the unsupported input is explicitly rejected before creation; no injected command runs

### Requirement: Editor and Agent startup retain existing contracts

The editor role SHALL use the existing `machine.editor` single executable launcher. Agent roles SHALL invoke explicitly selected deployed profiles using `agentcfg … run --cwd CHECKOUT`, without invoking sync/apply or replacing HOME. Independent Codex SHALL use its configured official executable and daemon policy.

#### Scenario: The requested Agent profile is not ready

- **WHEN** its existing run contract rejects launch
- **THEN** the entry reports that failure without installing dependencies or changing other instances

### Requirement: Native targets are freshly resolved and client effects are explicit

Each operation SHALL resolve the selected server, calling client and current native pane/workspace membership. Environment IDs SHALL be hints requiring revalidation. A moved pane SHALL NOT receive commands through an old ID or silently change its launch project. If native focus is shared among clients, that behavior SHALL be documented and tested rather than claiming client isolation.

#### Scenario: A managed pane is moved after startup

- **WHEN** a subsequent open operation uses an environment hint from before the move
- **THEN** current native membership is queried and project/role ownership is checked before focusing or creating

#### Scenario: Work is invoked from ordinary SSH outside Herdr

- **WHEN** the selected server is available
- **THEN** the entry uses a verified attach-and-select path; it does not merely change an unseen server selection or nest Herdr silently inside tmux

### Requirement: The entry has no hidden manager lifecycle

The entry SHALL use the prepared repository Python environment and terminate after the requested operation or native attach. It SHALL NOT introduce a daemon, a persistent terminal inventory, task dispatch, Agent completion decisions, HOME scans or process-wide environment inheritance.

#### Scenario: Dependencies or the environment are missing

- **WHEN** the prepared Python environment or approved Herdr baseline is unavailable
- **THEN** the entry gives an actionable error without downloading or updating software
