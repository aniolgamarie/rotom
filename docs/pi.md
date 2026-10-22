# Manage Pi with agentcfg

The rebuilt adapter uses the unchanged official `@earendil-works/pi-coding-agent@1.3.0` Node CLI.
Node must be at least 22.19.0. Base and Pro share the static `catppuccin-pi-theme@0.1.6` source,
public rules and complete selected Skill directories, with independent profile lock slices and instance state.
Implementation, dependency preparation and native/account acceptance remain separate:
see the [implementation status](../specs/005-rebuild-pi-toolkit/implementation-status.md)
and [module admission record](../specs/005-rebuild-pi-toolkit/module-admission.md).
Historical four-recipe results do not certify this combination.

The official 1.3.0 npm tarball omits its LICENSE. A separately pinned upstream MIT notice is
verified from repository bytes and installed under the runtime's independent `licenses/` directory;
the npm host files remain unchanged. This legal-source commit does not establish the npm package's
gitHead: `host.source_commit` remains null. The notice declaration and hash enter recipe, closure
and profile identities; missing or changed legal material cannot be silently accepted.

Rotom fixes the official `PI_OFFLINE=1` startup policy for both new deployments and existing saved
launch contracts. This prevents Pi from installing or updating missing auxiliary tools and extension
packages during startup. It also suppresses upstream catalog refresh, version checks and related startup
updates. Model requests and configured MCP connections still follow their own declarations; this flag
is not a network sandbox. Rotom environment inheritance and unset options cannot override it.

Pi's `fd` and `rg` executables are external machine prerequisites, separate from the complete npm
closure. The official host checks its own tool directory and then `PATH`; without the offline policy,
missing Linux tools would be downloaded from the latest GitHub release. Prepare required tools explicitly
from a reviewed source before using their features. Missing tools can leave the UI usable while related
completion or search features remain unavailable; a successful UI check or offline doctor does not
certify those executables. Rotom preserves existing native tool caches and does not silently replace them.

## Choose and prepare

`pi-base` is the daily configuration. `pi-pro` currently shares that foundation; investigation
collaboration is **not ready**, and `collaboration.enabled=true` is rejected. Both profiles select
`builtin:codemode`, the three-row `pi-footer` status display and native project trust. MCP services
and other external plugins remain explicit choices with separate admission and runtime evidence.
No Task Keeper, model-delegate,
custom execution loop, Todo or automatic planning platform is loaded.

Start from [Base](../examples/pi-base.local.toml) or [Pro](../examples/pi-pro.local.toml)
using fictional examples as a shape reference. Keep the actual machine file and credentials
private (0600 files, 0700 directories). Use your own provider/model/editor binding; an example
model or empty key does not establish account readiness. Existing shared model defaults still
apply through the common catalog; inspect the resolved selection before using it.

```sh
./agentcfg init-local --machine workstation --profile pi-base
./agentcfg --machine workstation --profile pi-base lock --agent pi
./agentcfg --machine workstation --profile pi-base validate
./agentcfg --machine workstation --profile pi-base sync
./agentcfg --machine workstation --profile pi-base plan
./agentcfg --machine workstation --profile pi-base apply
./agentcfg --machine workstation --profile pi-base doctor
```

These are explicit user operations; actual maintenance/rebuild outcomes are recorded separately in
the [acceptance record](../specs/005-rebuild-pi-toolkit/acceptance.md).
`lock` resolves dependencies; `sync` consumes the existing complete lock; `apply` deploys
configuration; `run` does none of those implicitly. Missing/stale locks fail with exit 2,
missing/damaged runtime packages with exit 5. Unknown installation scripts cannot be activated.
The sequence above stops before native startup; `run` needs separate native authorization.
Real native loading, terminal interaction, account login and model calls require their own authorization
and evidence. Default tests use temporary homes, blocked network and fake processes.

## Dependency selections and explicit relocking

Rules, complete Skills, prompt templates, theme sources and builtin extension choices are dependency
inputs. A local selection change requires an explicit lock using that same effective binding:

```sh
./agentcfg --local /private/config/pi-base.toml --profile pi-base lock --agent pi
```

The path is illustrative; use your private machine file. `validate`, `render`, `plan`, `apply` and
`sync` check the selected profile against current dependency inputs. `run` consumes its saved deployed
contract and checks configuration selections, guarded resources and the sealed runtime package; it
does not re-read the repository lock as a substitute for that saved contract. No command relocks implicitly. Model,
editor and UI changes do not enter the npm recipe, though they still change configuration or launch
validation and need the corresponding review. A source/backend semantic change still needs review
and verification even when the dependency digest stays unchanged.

An installed runtime alone does not establish startup readiness. Pi also compares the saved launch
contract with the current provider, model, role, settings and resource selections. After changing
those selections, review `plan` and explicitly `apply` each affected profile. If a dependency selection
changed, first resolve its lock and run `sync`; `apply` cannot repair a stale dependency lock.
`doctor` checks the deployed selection binding and reports a mismatch as requiring deployment, even
when the native files and runtime package have not changed. This check does not start Pi, inspect
accounts or verify model requests.

Current profile consumption is independent: changing an unselected profile's resources does not
invalidate the selected slice. Explicit `lock` using a machine configuration publishes both slices
from that same machine's effective Base and Pro selections. It does not replace the other profile's
local choices with public defaults. Public-only lock resolution still uses public defaults. Review
both slices before publication/use. Selecting `resources.themes=[]` excludes the theme package
from that profile's closure.

Only `roles.main` is supported. The admitted builtin extensions are `builtin:codemode` and
`builtin:tool-search`; Codemode is selected by default. MCP and external plugins accept only
registered, fixed module IDs. Unknown packages, arbitrary entries and held candidates fail validation.

Startup repairs must preserve the existing functional choices rather than replace them with public
defaults. Record the deployed resource and tool selections before applying a changed launch contract,
and keep those choices explicit in the machine overrides. `settings.defaultTools` preserves the
native tool selection, including Codemode when its builtin is selected. When it is omitted, the
adapter derives the standard tools and the tools of selected builtins. An explicit tool list takes
precedence. The fixed repository-owned
`/exit` alias uses Pi's public command/shutdown APIs and is included in the complete runtime lock.
Dependency integrity and a matching launch contract do not by themselves prove that a previous
configuration has been preserved.

## Ownership and resources

Each profile owns a stable `pi-home` and `pi-home/sessions` inside its isolated instance.
The official CLI receives both explicit session-directory settings, the four resource-discovery
disabling flags, and explicit local Skill/prompt/theme entries. Both profiles select
`agent_options.discovery.project_trust="native"`, retaining Pi's own saved decision or interactive
trust prompt. An explicit `project_trust="deny"` adds `--no-approve`. Native trust does not add
`--approve` or grant
trust automatically. The trust choice is part of the deployed launch contract. Project AGENTS.md
context remains available; these flags are not an operating-system sandbox.
Global `settings.json.packages` must be empty: even object-form declarations are refused
before managed startup. Loading drift is reported without deleting user content or installing packages.

UI fields initialize only eligible new/missing preferences. Later native theme changes are preserved;
the runtime accepts `catppuccin-latte`, `catppuccin-frappe`, `catppuccin-macchiato` or
`catppuccin-mocha` from that single locked source. Unknown themes fail rather than silently falling back.
Managed model/settings fields use common selector ownership. Unknown unmanaged native fields remain
untouched, and capture produces only a validated nonsecret proposal. Successfully managed shared-file
paths remain recorded across module disable/reselection; existing unmanaged fields are not adopted.
Older state that already lost a retired path is not silently repaired: the recorded native test used a
normal saved rollback followed by apply to recover provenance, then revalidated disable/reselection.

API model keys are guarded environment references, resolved only for the deployed launch contract.
OAuth, trust, sessions and history remain native instance state; no old or other-profile accounts
are imported. Ordinary native model/session/thinking arguments are supported within the selected
routes and stable session directory; resource/trust/installation overrides are refused.

## Run ownership and descendant release

Same-profile main runs have independent owner records. Active or unknown runs block exclusive
maintenance; one run ending never clears another. On Linux, a successfully established kernel child
subreaper tracks descendants of this one launch, including detached children. Only a complete
observation that all related children have exited releases that run. Parent exit alone leaves live
or unobservable descendants **unknown**. Manager crashes, unsupported platforms and failed coverage
retain protection; a later launch cannot clear an older unknown run. Timeouts and manual assurances
do not clear ownership. Do not delete owner records or kill processes to bypass it.
The kernel mechanism has isolated tests and an own-code double-fork probe. Linux native acceptance
also verified two simultaneous main runs: maintenance returned 4 with two active runs and again
with one remaining run, then returned 0 after both exited. All recorded A/B/C owners reached
idle_confirmed; this does not release older unknown records or prove every future descendant path.

For old IDs and retained data see [migration](pi-migration.md). Configuration rollback covers managed
configuration only; it does not downgrade software or restore databases or executed tasks.

## Verification boundaries

Current isolated entry points are
[test_pi_reboot_configuration.py](../tests/test_pi_reboot_configuration.py),
[test_pi_reboot_dependencies.py](../tests/test_pi_reboot_dependencies.py),
[test_pi_reboot_runtime.py](../tests/test_pi_reboot_runtime.py) and
[test_pi_reboot_pipeline.py](../tests/test_pi_reboot_pipeline.py). Their fake processes do not
prove native loading or model access. Offline `doctor` distinguishes configuration, dependencies,
deployment, loading, account and runtime evidence; installed dependencies do not imply later stages
passed. `doctor --live` reports reachability only.

The [quickstart](../specs/005-rebuild-pi-toolkit/quickstart.md) describes T036 dependency-only
rebuilding. Its command examples are not execution results. Authorized Linux local no-account
A/B/C native checks passed for official Pi 1.3.0/theme 0.1.6, footer 0.5.1 with the revised observer,
and cache-hit-monitor 0.1.1 separately. All three passed version/help and real tmux 3.5a TUI checks
at 60/90/130 columns with Chinese multiline bracketed paste, Ctrl+C clearing, reload and Ctrl+D exit.
The default combination also passed a bare PTY check and preserved a native Frappe theme choice
after apply. Exact candidates, locks, commands and results are in the
[acceptance record](../specs/005-rebuild-pi-toolkit/acceptance.md).

Those initial runs used isolated temporary instances, fictional bindings and synthetic placeholder keys;
each host launch entered a fresh network namespace with loopback only and no routes. There were
zero real logins or model requests at that checkpoint. Later authorized shared-default requests passed
continue/fork/compaction/model switch with all model tools disabled; footer input/output values matched
SDK usage while unconfirmed billing remained unknown. Context7 native connection and separate service
queries, fixed Chromium synthetic-page operations and no-account Brave/Cursor loading have bounded
evidence in [supplementary acceptance](../specs/005-rebuild-pi-toolkit/remaining-native-acceptance.md).
The [current delivery acceptance](../specs/005-rebuild-pi-toolkit/current-delivery-acceptance.md)
adds one explicitly authorized bounded real-tool task, running cancellation/recovery, branch statistics
through compaction, positive cache usage, and the user's acceptance of three display differences.
T037/T038/T058/T059 are complete for the recorded Linux scope. Loopback SSH is actual SSH transport
and PTY evidence; the non-root server's exit255 limitation is retained. Other platforms are unverified.

Explicit `pi-footer@0.5.1` uses a public-event observer. The accepted differences are branch-average
output speed, some statistics in details on narrow screens, and a clear permission explanation:
the host exposes no queryable permission state, so this display does not indicate protection.
Actual billing remains unknown where rates or upstream confirmation are missing. See the
[status guide](pi-status.md).
`pi-powerline-footer@0.20.2` and `@mjakl/pi-subagent@3.1.0` remain held. The future collaboration
contract permits at most two read-only investigations per main run; two independent main runs
would have independent quotas. This is a future admission requirement, not a supported worker
command or scheduler. The user retained the community-only route and deferred Pro until upstream
satisfies the full boundary; no custom investigation executor is introduced. See
[support and source evidence](pi-support.md).

The [optional module recipes](../specs/005-rebuild-pi-toolkit/optional-module-recipes.md) and
[all-off services example](../examples/pi-services.toml) distinguish implemented choices from
research candidates. Explicit `pi-footer`, `cache-hit-monitor`, `pi-context7` and `pi-brave` selections bind
the complete lock and launch configuration. Only the footer is selected among these plugins and
services by default; changing a selection requires
explicit lock, sync and apply. Selecting the `playwright-cli` Skill also binds its exact CLI package
and complete upstream support directory. Other candidates remain unavailable. Footer and cache
diagnostics have real usage evidence. Context7 connection and separate service queries and synthetic
Chromium operations passed; selected combinations, disable/restore and measurements are recorded
in current delivery acceptance. The user deferred Brave/Cursor real-account acceptance; their existing
implementation and no-account evidence do not prove authentication, entitlement, search or billing.

`pi-cursor@1.4.39` is an optional, unofficial subscription bridge. Select plugin `pi-cursor` together
with provider ID `cursor`, protocol `oauth-dynamic` and auth kind `oauth`; the declared native route
and authentication owner are `cursor` and `pi-cursor`. The provider accepts no API-key reference or
base URL. Use an exact selected remote model ID; an unknown or unentitled model does not fall back
to another provider. The adapter does not claim the bridge has authenticated or discovered that model.

The bridge can use only this instance's native Pi OAuth store. Managed launch fixes
`PI_CURSOR_SYSTEM_CREDENTIALS=0`, clears inherited Cursor tokens and route overrides, and fixes its
cache/journal directory inside the instance. It does not import Keychain, IDE or another instance's
credentials. Offline management never opens the native auth file. Native login, catalog refresh,
model requests and usage queries need separate authorized execution. Model/context data can leave
the machine, and the private journal may retain recovery material; entitlement, actual models,
retention and billing remain unverified. Disable stops subsequent loading while preserving auth,
cache and journal; cleanup belongs to their owner. This choice is shared by Base/Pro sources and
does not enable Pro investigations.

The [managed browser Skill](../shared/skills/playwright-cli/SKILL.md) adds one guarded CLI entry to
the current main run's PATH, with its own session and private cwd, HOME, XDG and browser cache.
It refuses personal-browser attachment, persistent profiles, arbitrary configuration, session
overrides, installation commands and global session shutdown. An unexpected automatic config file
is refused without reading it. Browser binaries are a separately prepared prerequisite; none are
downloaded by selection or npm installation. Managed `open` fixes the public `--browser=chromium`
option and requires full Chromium; headless-shell alone does not satisfy that option. One explicitly
prepared Chromium 1247 synthetic-page test confirmed normal browser/daemon exit. `open` can leave a daemon,
so page closure, daemon
exit and descendant release require separate evidence. Disable preserves native state and does
not terminate running processes. Browser scripting, uploads and storage changes remain actions
for an explicitly authorized main-session task; the wrapper does not constrain arbitrary Bash.

## Optional investigation and long-command methods

The `cpp-bounded-investigation` and `long-command-handoff` Skills are shared method resources,
registered for Pi and omitted from defaults. Select them through the common `skills` array and
explicitly lock, sync and apply. Complete directories are copied and hashed; choosing these Skills
does not add npm dependencies, tools or background processes.

The [C++ method](../shared/skills/cpp-bounded-investigation/SKILL.md) starts with bounded file search.
It uses ast-grep only when the project already supplies a verified binary and supported flags;
it does not install the unverified 0.3.1 extension. AST matches establish syntax, while overload,
template and type conclusions require the project's compiler conditions or existing clangd.
No global index or new semantic server starts with the Skill.

The [long-command method](../shared/skills/long-command-handoff/SKILL.md) hands explicitly requested
work to an existing tmux session owned by the project/user, with its cwd, logs and next action.
Stop requests, acknowledgements, process/descendant exit, result completeness and observed effects
remain distinct. Pi does not install tmux or take over termcfg. `pi-processes@0.13.2` and a PTY owner
remain research candidates; neither is loaded. Session memory or a shutdown signal does not promise
recovery after a restart. Configuration rollback does not restore command effects.
