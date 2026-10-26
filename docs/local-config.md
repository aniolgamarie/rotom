# Local machine configuration

Machine files use **agentcfg framework TOML**, not native agent configuration. They default to `$XDG_CONFIG_HOME/agentcfg/machines/<name>.toml`, falling back to `$HOME/.config/agentcfg/machines/<name>.toml`. List recipes with `./agentcfg profiles`, then initialize or add missing placeholders:

```sh
./agentcfg init-local --machine workstation --profile omp-kernel
./agentcfg --machine workstation --profile omp-kernel model status
```

Subsequent commands use global `--machine NAME` or `--local /path/to/private/local.toml` before the subcommand. They are mutually exclusive; omitting both selects machine `default`. Existing machine defaults apply when profile is omitted; a new machine defaults to `dsh-default`. Explicit init-local profile selection adds fields without changing an existing default recipe.

## Initialization and private files

Init-local derives placeholders from the selected recipe and inherited public model pool. Missing URL values go into `[local_values]` in the machine file; missing keys go into the shared secret file. For omp-kernel this includes two TF URLs and six independent keys: two Coding Plan keys, one official DeepSeek key, and three TF keys. Repeated references create one placeholder.

Existing values, comments, other settings, and secret groups are preserved; no missing fields means no rewrite. Existing inline secret declarations are not copied or migrated. Initialization does not fill actual credentials, contact services, or deploy. Unknown fields, malformed input, mismatched machine IDs, and unsafe permissions fail instead of being reset from a template. Writes check snapshots; a failed associated write attempts to undo that shared-secret update without overwriting concurrent changes.

Files must be owned by the current user, regular, single-link, mode 0600; private directories use 0700. Reads also reject symlinks, hardlinks, ownership/permission violations, and read races. These protections are checked on every read, not just initialization. The manager does not import another tool's authentication or verify API keys online.

## Model pool and service credentials

[`shared/defaults/models.toml`](../shared/defaults/models.toml) adds Kimi Code, GLM Coding Plan, and metered DeepSeek to DSH/Pi/OMP. Each tool's default selection contains ten official model IDs. DSH/Pi use OpenAI-compatible routes; OMP uses Anthropic-compatible routes. Each service's two protocols share its matching `kimi_code_key`, `glm_coding_key`, or `deepseek_key` reference.

Unless explicitly overridden, main remains Kimi Code `kimi-for-coding`. Pool membership does not assign a role or authorize an automatic paid fallback. Existing explicit TF/Cursor roles take precedence. Unbound Pi resource roles inherit main. Provider/model selections append with deduplication across layers; rules, skills, plugins, and MCP arrays still replace. See the [model catalog](model-catalog.md) and [OMP presets](omp-model-presets.md).

Kimi Code addresses are `https://api.kimi.com/coding/v1` (OpenAI) and `https://api.kimi.com/coding/` (Anthropic); GLM Coding Plan addresses are `https://open.bigmodel.cn/api/coding/paas/v4` and `https://open.bigmodel.cn/api/anthropic`. See the [Kimi model guide](https://www.kimi.com/code/docs/en/kimi-code/models.html) and [BigModel Coding Plan guide](https://docs.bigmodel.cn/cn/coding-plan/tool/others). Use matching plan-console credentials. A nonempty local key and configured address do not establish entitlement or connectivity.

The old general Kimi/GLM provider/model entries and `model enable kimi|glm` are removed. Use `kimi-code` and `glm-code`. Existing `kimi_key`/`glm_key` secrets remain readable and are neither deleted nor reused automatically. Overrides referencing removed entities fail explicitly; update them according to the actual service.

```sh
./agentcfg --machine workstation model key kimi-code
./agentcfg --machine workstation model key glm-code
./agentcfg --machine workstation model key deepseek
./agentcfg --machine workstation --profile omp-kernel model status --verbose
```

Model status reports missing fields, provider origins/status, role bindings, file locations, TOML groups, secret names, and provider associations. Verbose adds the full catalog and selector-preserving fill commands. It hides actual private URL/key values and does not check deployment freshness or account connectivity.

Model key accepts hidden terminal input only; blank cancels and no key value is accepted on the command line. A missing shared file is created with 0600. Configured means nonempty, not authenticated. Missing model keys allow startup but cannot support requests. After key-only changes, exit and run again. After URL/provider/model/role changes, stop the host, setup, then run; active processes do not refresh automatically.

## Shared secret storage

The default shared file is `$XDG_CONFIG_HOME/agentcfg/secrets.toml` or `$HOME/.config/agentcfg/secrets.toml`, shared across tools, machines, and recipes. New machine files contain no keys. The format below contains empty placeholders only:

```toml
schema_version = 1

[shared]
kimi_code_key = ""
glm_coding_key = ""
deepseek_key = ""

[providers.kimi_tf]
omp_kimi_tf_key = ""

[providers.zhipu_tf]
omp_zhipu_tf_key = ""

[providers.deepseek_tf]
omp_deepseek_tf_key = ""
```

New public-pool keys are grouped under `[shared]`; additional provider keys use `[providers.<provider-id>]`. Legacy Kimi/GLM storage groups remain compatible. Model key shows the destination/group before input. Groups organize storage, not profile access isolation, and do not change `secret:<name>` references. Names must be unique across the whole file, even for empty placeholders; multiple recipes sharing a provider reference one entry.

Legacy flat `[secrets]` in shared files remains readable/updateable and is labeled legacy in status. Existing keys retain their group and comments. New and old groups may coexist without duplicate names. Updates change the target entry rather than migrating/reordering the whole file.

A top-level machine `secrets_file = "~/private/agentcfg/secrets.toml"` selects another shared file. Only absolute paths and leading `~/` are accepted; no environment expansion. It cannot point at the machine file or inside the repository. Missing means not yet filled; existing files must pass private-file checks.

Legacy inline machine `[secrets]` remains supported. Empty inline placeholders do not hide shared values; two nonempty values for the same reference fail rather than choosing an account silently. Updating an existing inline key explains that it stays in its original location. Separate files reduce accidental reading/sharing; they do not isolate credentials from other processes of the same user. Do not paste real contents into chat.

## Public presets, TF URLs, and interactive additions

`./agentcfg model presets` requires no machine file. It distinguishes subscription and metered routes; verbose adds public addresses, specifications, dated pricing, and sources. Subscription entries do not invent per-token prices. DeepSeek pricing remains a dated snapshot rather than a live quote. To add the other supported protocol explicitly, use `model enable kimi-code|glm-code|deepseek`; for example, OMP can select `--protocol openai`. Enabling a route does not replace main.

OMP TF definitions are in `agents/omp/content.toml`; omp-kernel selects three TF providers and thirteen bindings. They are not global defaults. DSH has its own explicit bindings described in [DSH](dsh.md). DeepSeek TF shares `local:tf_openai_url` with Kimi TF but has the independent `secret:omp_deepseek_tf_key`, fillable with `model key deepseek_tf`. Shared templates do not guarantee gateway IDs, capability, billing, or official-plan entitlement.

Private URLs belong in machine local_values. Public provider definitions use `base_url_ref = "local:<name>"` instead of literal base_url:

```toml
# Public registry: a reference only.
[providers.kimi_tf]
protocol = "openai-compatible"
auth_kind = "api-key"
base_url_ref = "local:tf_openai_url"
credential_ref = "secret:omp_kimi_tf_key"
```

```toml
# Private machine file: fictional example addresses.
[local_values]
tf_openai_url = "https://gateway.example.invalid/v1"
tf_anthropic_url = "https://gateway.example.invalid/anthropic"
```

```sh
./agentcfg --machine workstation --profile omp-kernel model url kimi_tf
```

Model url reads the actual address with hidden input. Status reports only presence and location. Missing URLs do not block status/key entry or unrelated recipes, but selected providers must have valid URLs before deployment/startup. URLs must be absolute HTTP(S), without userinfo, credential query parameters, or control characters. A private literal base_url may replace a public reference and vice versa, but both cannot appear in the same layer.

Local values are not key storage or general interpolation. Unused values are not rendered. Referenced URLs must appear in private native configuration for the host to connect, so do not share complete deployed artifacts. Missing URLs in unselected recipes defer URL-dependent adapter checks; selection/deployment requires complete validation.

`./agentcfg --machine workstation model add` adds a static API-key provider/model, selections, and roles interactively to an existing machine. It requires a hidden key, validates schema/adapter/candidate output, shows a nonsecret summary, and writes only after `yes`. Private configuration and shared keys use 0600 with concurrent-update protection and attempted secret rollback if configuration commit fails. Unchanged comments/fields remain. Complex multiline TOML or tables that cannot be safely located cause refusal without rewriting. OAuth and existing-entity changes use explicit configuration editing.

## Field reference

| Field | Meaning | Default/constraint |
| --- | --- | --- |
| `schema_version` | Framework format version | Required integer 1; no silent migration |
| `machine.id` | Nonempty single path component | Unicode/spaces allowed; no slash, backslash, controls, `.` or `..` |
| `machine.default_profile` | Declared recipe ID | `dsh-default`; explicit global --profile wins |
| `machine.editor` | One executable name or absolute executable path | Otherwise use allowed terminal environment; no arguments/shell command |
| `machine.paths.instances_root` | Instance root | XDG_DATA_HOME/agentcfg/instances |
| `machine.paths.state_root` | State, locks, previous backup | XDG_STATE_HOME/agentcfg |
| `machine.paths.cache_root` | Private output/install cache | XDG_CACHE_HOME/agentcfg |
| `machine.environment.inherit` | Allowed nonsecret variable names | Empty array; never the whole parent environment |
| `machine.environment.values` | Nonsecret names mapped to strings | Empty table; no eval or command expansion |
| `machine.environment.unset` | Remove declared ordinary variable names | Empty array; distinct from an empty string; cannot conflict with inherit/values |
| `overrides.providers.<id>` | Add/override provider | Unselected entities stay disabled |
| `overrides.models.<id>` | Add/override logical model | Matching names across providers do not prove matching capabilities |
| `overrides.mcp.<id>` | Add/override private MCP | No services selected by default |
| `overrides.profiles.<id>` | Override an existing recipe | Cannot change agent or create a recipe implicitly |
| `local_values.<name>` | Private strings used for provider URL references | Selected references must be nonempty; values are not echoed |
| `secrets_file` | Shared secret file path | Default XDG configuration path above |
| `secrets.<name>` | Legacy inline secrets | Supported; new keys default to shared storage |

Unset XDG data/state/cache roots fall back to `$HOME/.local/share`, `$HOME/.local/state`, and `$HOME/.cache`. TOML path fields accept absolute paths or leading `~/`, including Unicode/spaces; no relative paths, `~otheruser`, variables, or command substitution. Empty is not omission. CLI `--local` separately allows relative paths, including checked `../` ancestors. `editor = "nvim -f"` is invalid.

Provider protocol/auth_kind are required. Static API-key providers need base_url or base_url_ref and a credential_ref. Dynamic OAuth providers may have no static URL; do not fabricate one. Adapter bindings own native routing/authentication.

Public specifications live in `shared/model-templates.toml`. A binding may reference one template and override model fields. Templates omit provider, URL, credentials, price, and native compatibility. Unknown fields, missing templates, or duplicates fail; templates expand before recipe selection. Private model overrides keep their existing format and do not support template declarations. Public `native.pi.disabled_thinking_levels = ["off"]` becomes Pi `thinkingLevelMap.off = null`; conflicting mappings fail and the custom source field is not passed to native configuration.

Models require provider, remote_id, and known input capabilities. Optional context_window/max_output_tokens must be verified positive integers; max_output_supported can record a distinct server limit. Name, reasoning, reasoning_efforts, and source record verified display/capability facts; omit unknown values. Native Pi/OMP compatibility fields are schema-limited. DeepSeek thinking/history/tool constraints follow its documented integration. MCP command/args are argv; adapter checks determine whether remote URLs/credential references are supported.

Pricing records currency, per-million input/output/cache rates, query date, and sources, with off_peak/schedule where relevant. It is a catalog snapshot. Native cost fields cannot accurately represent CNY or DeepSeek time bands, so prices are retained in catalog output rather than projected misleadingly. DSH currently projects capacities only; OMP/Pi also project reasoning capabilities. See [catalog](model-catalog.md).

Allowed recipe overrides cover provider/model/rule/skill/plugin/MCP selections, role aliases, and adapter-validated agent_options. Merge order is registry/tool defaults → recipe → private overrides → explicitly supported one-shot parameters. Objects merge recursively and scalars replace. Providers/models append with deduplication; other arrays replace completely. `mcp = []` clears, and `terminal_images = false` stays false. Omission inherits. Removing a referenced registry ID fails.

## Private gateway example

```toml
schema_version = 1

[machine]
id = "workstation"
default_profile = "dsh-default"
editor = "nvim"

[overrides.providers.private_gateway]
protocol = "openai-compatible"
auth_kind = "api-key"
base_url = "https://gateway.example.invalid/v1"
credential_ref = "secret:private_gateway_key"

[overrides.models.private_main]
provider = "private_gateway"
remote_id = "fictional-private-chat"
input = ["text"]

[overrides.profiles.dsh-default]
providers = ["private_gateway"]
models = ["private_main"]
mcp = []

[overrides.profiles.dsh-default.roles]
main = "private_main"
```

```sh
./agentcfg --machine workstation --profile dsh-default model key private_gateway
```

Replace the address/model with verified service values and confirm adapter protocol support first. See `examples/*.example.toml` for framework examples. An override alone cannot create an undeclared recipe such as dsh-ssh.

Ordinary sessions use a declared development environment. OMP and Pi preserve the caller's HOME/XDG; DSH preserves its native TUI HOME and forwards the development environment through its public subprocess provider and a separate stdio MCP exec configuration. Native account and session paths remain instance-owned. This is environment selection, not filesystem or credential isolation.

Caller proxy variables are never inherited implicitly. Declare named proxies once in the local machine file and select one per session, avoiding repeated variable lists:

```toml
[machine.proxies.work]
url = "http://proxy.example:8080"
no_proxy = "localhost,127.0.0.1"

[machine.proxies.office]
url = "http://proxy-office.example.invalid:3128"

# Optional persistent default; `run --proxy <name>` overrides it for one launch.
[machine.environment]
proxy = "work"
```

A selection injects `HTTP_PROXY`/`HTTPS_PROXY`/`http_proxy`/`https_proxy` from `url`, `ALL_PROXY`/`all_proxy` from `all_proxy` (defaulting to `url`), and `NO_PROXY`/`no_proxy` when `no_proxy` is set. URLs must be http/https without userinfo, query, or fragment; only an HTTP CONNECT proxy works and no host supports SOCKS. A selection conflicts with `inherit`/`values`/`unset` entries naming the same variables — adjust the profile instead. Pi reads these through its global undici proxy dispatcher, OMP through its own `PI_PROXY`-aware resolver plus the runtime fetch, and DSH through its startup dispatcher. Declare host-specific overrides such as OMP `PI_PROXY`/`PI_PROXY_<PROVIDER>` explicitly via values. Raw non-HTTP transports (Cursor subscription HTTP/2 model streams, Codex WebSocket) bypass environment proxies entirely; see the per-host notes.

```toml
[machine.environment]
inherit = ["CUSTOM_BUILD_ROOT"]
unset = ["VIRTUAL_ENV"]

[machine.environment.values]
BUILD_MODE = "debug"
```

The precedence is caller defaults, machine inherit/values/editor, machine unset, named proxy selection, then one-shot changes. An empty value is present; unset removes it. Machine inherit is optional when absent. A changed declaration requires `plan` and `apply`; inherited values are resolved anew on each run. Shell expansion and command substitution are not performed.

```sh
./agentcfg --machine workstation --profile dsh-default run --inherit-env CUSTOM_BUILD_ROOT
./agentcfg --machine workstation --profile pi-default run --unset-env VIRTUAL_ENV
./agentcfg --machine workstation --profile omp-default run --proxy office
./agentcfg --machine workstation --profile omp-default doctor --environment
```

One-shot options accept names only. An explicit missing inherited variable, repeated/conflicting options, unsupported operation or protected variable fails before resolving credentials or starting the host. One-shot inherit can restore a machine-unset variable from the caller. Options after `--` still belong to the native program. Installers and restricted workers do not acquire these ordinary-session overrides.

Each launch warns when caller inputs are omitted or overridden, including intentional changes. Ordinary names and reason categories are bounded; protected inputs are counted without reading/comparing their values. `doctor --environment` shows a value-free preview of the deployed host contract and pending declaration changes, not proof of every downstream process. No values or hashes are logged.

Environment tables and one-shot options cannot override managed HOME/XDG, DSH_/AGENTCFG_ prefixes, NODE_OPTIONS/NODE_PATH, credential destinations or startup/preload controls. Pi Cursor proxy clearing and other adapter restrictions remain enforced; an incompatible explicit override is rejected rather than silently undone. Keep secrets out of ordinary environment settings and use the credential workflow. Machine editor overrides EDITOR/VISUAL before explicit unset.

Edit only relevant tables, preserving other recipes, comments, and secrets; if a local rewrite cannot be safe, prepare a partial proposal instead.

Parse/encoding failures return 2 with safe one-based line/column coordinates, for example `parse @ local.line.8.column.12.TOML`. `local` identifies the selected private source without printing its path/body/secret fields. Public locations use registry.N/profile.N/adapter.N.agent|bindings|plugins. Shared/profile files load in sorted filename order, then adapter registries in `ADAPTER_TYPES` order in workspace.py. Indices are per-load positions, not permanent IDs. Fix syntax and retry without dumping private files.

Render/plan do not change instances; apply deploys and maintains the previous backup. Rotated keys are resolved on the next launch and never need to enter rendered configuration. Configuration backups do not include secret-bearing machine files. See [operations](operations.md) for deployment/recovery and [known issues](known-issues.md) for current blockers.

## Optional project terminal selection

`machine.work` configures the separate `./work` entry. Without an explicit model, existing Git-only seven-role behavior remains legacy. Set `model = "structured-v1"` to opt into configured `sources`, ordered `templates` with local tab types, and explicit project or named `workspaces`. Structured-only fields without that model and unknown models fail validation; there is no silent fallback. Saving configuration does not enter a workspace or migrate active layouts.

Both modes require `herdr_binary` (one executable) and `session` (1–64 ASCII letters/digits/underscore/hyphen, starting with a letter/digit). Optional `pi_profile` and `dsh_profile` select existing prepared recipes; `codex_binary` selects the independent Codex executable; boolean `codex_daemon` defaults to false. Unknown fields fail. This table contains ordinary choices only, with no credentials, resume session, command strings or recent-project inference.

Legacy `open edit` and structured types with `launcher = "editor"` use the existing single `machine.editor` executable, preferably the independent Avalon profile launcher. Type names in structured mode come from the selected template. `--machine NAME` and `--local FILE` are mutually exclusive global options before the subcommand, for example `./work --machine workstation open edit`. See the [complete structured example](../examples/work-structured.toml) and [workspace guide](herdr-workspaces.md) for source coverage, named contexts, fixed launch bindings and separate save/entry commands. Shell/editor selection does not resolve the secret store. Agents keep the existing `agentcfg run` environment and identity; Herdr variables are not automatically inherited.
