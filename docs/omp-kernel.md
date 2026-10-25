# The omp-kernel recipe

`omp-kernel` is the daily-use OMP recipe. It extends `omp-default`, whose public pool contains ten official model bindings: six Kimi Code, two GLM Coding Plan, and two DeepSeek. The initial public main model is Kimi Code. This guide covers private machine configuration, deployment, and managed launch. Linux glibc x64 evidence does not establish WSL validation; see [testing](testing.md) and the [support matrix](omp-support.md).

## Included configuration

The public [recipe](../profiles/omp-kernel.toml) adds three gateway providers and thirteen model bindings, including native Anthropic Messages, compatibility settings, costs, thinking levels, and execution fallback mappings. Together with the base pool, it declares twenty-three static model bindings. The two K3.1 TF bindings declare no cost because gateway pricing is unverified. Provider-specific transport and pricing stay attached to each binding; shared model specifications reuse catalog templates.

The recipe includes Bash approval patterns, five configured interceptors disabled by default, five agents, four complete skills, managed `RULES.md`, dark/light Catppuccin themes, a status line, and `default/smol/slow/plan/task` model roles. `agent_options.tiny_model = "local/lfm2.5-230m"` maps to native `modelRoles.tiny`. It is not a verified main model. Catppuccin resources come from fixed upstream sources.

This is an adapter-supported configuration, not a copy of a previous HOME. Initial `apply` creates an isolated managed native identity derived from the complete profile ID. Existing account data, authentication, and sessions stay in their original locations and are not copied.

The recipe sets `display.hideToolActivity=false`. UI visibility changes persist this field and can create managed drift; lasting changes should be expressed in public/private source and deployed. Private `native_model_roles` can bind OAuth-native model roles without inventing static API-key models. For Cursor K3, use the upstream logical model ID with effort (for example `cursor/kimi-k3:high`) rather than an old effort-member ID. The selector persists logical ID/effort; mismatched private source can cause `/modelRoles/default` drift. Review `plan` and align source/deployment instead of weakening drift checks. Such a binding requires selecting the corresponding OAuth provider and does not change the independent reviewer selection.

## Permission plugin and review models

The runtime is unmodified official OMP v18.12.6. The repository-owned permission plugin uses public extension APIs. It provides `permission_bash` and, with `native_bash=true`, a same-name native Bash wrapper that delegates through `ctx.invokeTool()`. Native `bash=prompt` remains the protection when the plugin is absent. Explicit deny/prompt rules retain their effect. See [approval design](design/approvals.md) and [diagnostics](omp-approval-diagnostics.md).

Choose the execution model inside OMP. Permission review is configured separately: explicit `reviewer_model` wins; omission follows the session model, and `reviewer_model="session"` explicitly requests that behavior. The public kernel reviewer is `omp-zhipu_tf-glm-5.3-flash`, with `omp-kimi_tf-kimi-for-coding` as remote fallback. Private overrides take precedence.

```toml
[overrides.profiles.omp-kernel.agent_options.permission_control]
reviewer_model = "omp-zhipu_tf-glm-5.3-flash"
remote_fallback_model = "omp-kimi_tf-kimi-for-coding"
fallback_model = "local/lfm2.5-230m"
review_max_output_tokens = 2048

[overrides.profiles.omp-kernel.agent_options.permission_control.review_timeouts]
primary_ms = 30000
remote_ms = 30000
total_ms = 60000
```

A valid allow/ask/deny is final; fallback is attempted only after primary unavailability, unsupported transport, or an invalid/failed response. It is independent of execution `retry.modelFallback`. Bad model references fail configuration validation.

Default review budgets are 30 seconds primary, 30 seconds remote, and 60 seconds total. If `review_timeouts` is supplied, all three fields are required. Primary/remote ranges are 1000–120000 ms; total is 1000–240000 ms and, with a fallback, at least their sum. Remote review starts its own budget when it begins and remains subject to the total deadline. `/permission-control status` reports actual budgets. `TIMEOUT` means a local plugin deadline expired, not proof of a remote service timeout.

Official OMP has no public installed-only tiny inference API. The local fallback identity remains configured but unavailable; the plugin neither uses private workers nor downloads resources. If remote layers fail, it asks the user, or blocks without UI. Native title generation and permission fallback are separate capabilities.

Permission configuration is deployed as `permission-control.json`, without private host fields in official `config.yml`. The independent raw Bash tool is noninteractive and does not inherit native services/jobs/PTY, direnv, interceptors, worktree rewriting, or background-job management. Native wrapping uses its validated public execution route. Neither integration is an OS sandbox, and other tools retain their own protections.

## Private machine setup

Use Python 3.11+ and the prepared repository `.venv`. WSL must use a supported Linux glibc architecture; native Windows, musl, and unknown architectures return 5. Keep the repository and private configuration/state/cache on the Linux filesystem. `/mnt/c` is unsuitable as the default basis for private 0600 files, 0700 directories, and atomic replacement.

```sh
./agentcfg init-local --machine omp-kernel --profile omp-kernel
OMP_LOCAL="${XDG_CONFIG_HOME:-$HOME/.config}/agentcfg/machines/omp-kernel.toml"
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel model status
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel model url kimi_tf
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel model url zhipu_tf
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel model key kimi_tf
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel model key zhipu_tf
```

URL/key entry is hidden. Real endpoints and credentials belong in private machine/secret files, never repository profiles or command arguments. Public catalog entries do not contain private gateway addresses. Gateway access and standalone downloads are independent network prerequisites.

Gateway providers resolve `local:tf_openai_url` and `local:tf_anthropic_url` from `[local_values]`. DeepSeek and Kimi gateway bindings share the OpenAI URL reference but use separate keys. Use `model key deepseek_tf` for the third service. `model url` validates and atomically saves the private address without echoing its previous value. Missing URLs are listed by `model status`; `setup/apply/run` fail when a selected provider lacks its required address. Profiles not selecting those providers are unaffected. Preserve the declared model IDs and protocols rather than substituting a similarly named official endpoint.

Keys default to the XDG-aware `~/.config/agentcfg/secrets.toml`. Gateway references are `omp_kimi_tf_key`, `omp_zhipu_tf_key`, and `omp_deepseek_tf_key`. Official subscription commands `model key kimi-code` and `model key glm-code` use `kimi_code_key` and `glm_coding_key`; official metered DeepSeek uses `model key deepseek` and `deepseek_key`. Services do not automatically share or migrate old keys. Missing keys may still allow the UI to start while the corresponding models/fallbacks remain unready. A key-only change needs a fresh run, not apply. See [local configuration](local-config.md).

Adding models to the pool does not change existing execution roles. Five native model presets are documented in [model presets](omp-model-presets.md); see also the [catalog](model-catalog.md).

## Deploy and launch

Global selectors precede subcommands. A new machine initialized for this recipe uses it as default; an existing machine retains its previous default, so explicit selectors are recommended:

```sh
OMP_WORKSPACE="$HOME/src/your-project"
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel setup
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel run --cwd "$OMP_WORKSPACE"
```

`setup` previews redacted changes, prepares the locked standalone if needed (possibly using the network), rechecks, and deploys. For separate review, use `validate`, `plan`, `sync`, `apply`, and `doctor`; `render` is optional cache generation. `run` uses only the deployed runtime and never implicitly downloads or deploys. Normal managed launches add `--no-title`, avoiding automatic title-model requests.

Repeat `setup` to update an existing instance. Exit active OMP sessions first; the manager rejects writes to an active instance and does not stop it. `init-local` may be repeated to add newly declared placeholders without overwriting existing values:

```sh
./agentcfg init-local --machine workstation --profile omp-kernel
./agentcfg --machine workstation --profile omp-kernel model status
./agentcfg --machine workstation --profile omp-kernel setup
./agentcfg --machine workstation --profile omp-kernel run omp --cwd "$PWD"
```

For offline configuration-only updates with dependencies ready, review `plan` and use `apply`. `setup` consumes the checkout's lock; it neither pulls Git updates nor selects upstream latest. Conflicts, drift, or pending recovery stop unsafe progress. Inspect them with the same selectors before changing files.

The recipe enables Vim input. `Esc` enters `NORMAL`; `i` returns to `INSERT`. The status line's `vim` segment shows input state; `mode` describes other session modes. For lag while already in INSERT, run `doctor --input` from another terminal. `input_diagnostics.diagnostic_terminal` describes that diagnostic terminal, not the OMP terminal. `readiness` is offline readiness; OMP `host_events` expose recent `ui.loop-blocked` time, PID, elapsed/CPU duration, and phase only, without keystrokes or log bodies. No event does not prove that input reached the terminal.

## Discovery and environment

New execution contracts preserve caller HOME/XDG/cwd while keeping native account/session storage in the managed state home. Older deployments require explicit `plan/apply`; see [profiles](omp-profiles.md#storage-and-execution-environment).

Ordinary repositories may contain disabled compatibility providers' `.agents/`, `.agent/`, `.claude/`, `.codex/`, `.gemini/`, and top-level context files. These do not load automatically. Effective native sources such as `.omp` settings/agents/tools/hooks/skills/MCP, dotenv, and SYSTEM/TITLE/APPEND_SYSTEM remain checked. The kernel recipe does not enable project resources by default. Declare project skills/MCP through the [discovery policy](omp-profiles.md#discovery-policy), rather than allowing an entire directory of settings or credentials.

Native Bash review validates the managed execution-route contract and public settings. Common shells, including zsh, retain their environment, while ordinary local tools use the upstream Brush backend. Unknown/ACP or unbound contexts retain manual protection. `/permission-control explain` reports shell family, route, and fixed context reasons. Explicitly enabled interceptors can still reject a tool preference after permission review; the default kernel interceptors are disabled.

## Codex delegation and tiny models

`codex-delegate` runs only when the user explicitly requests Codex. Hosts with the Pi integration use `codex_delegate`; OMP can use the installed skill's relative `scripts/run-codex.sh`. That runner requires Linux Bash, `jq`, util-linux `setsid`, `/proc`, and `codex`, plus independent `CODEX_HOME` authentication. Deployment does not install these prerequisites or log in.

The runner does not inherit caller proxy variables. A machine needing a proxy can set `CODEX_DELEGATE_PROXY_URL` in private `[machine.environment.values]`. It must contain no userinfo, token, query, or fragment. It reaches only the Codex child and is not emitted in receipts/stdout. There is no assumed machine proxy address.

Explicit native tiny-model use may require an existing model cache or network retrieval. This is separate from `sync`'s standalone cache and does not enable the unavailable permission fallback.

## Download recovery and evidence

Retry `sync` with the same local/profile after interruption to reuse a safe content-addressed partial file. Complete length and SHA-256 are required before publication. Never rename a `.part` file or bypass its lock digest. See [dependency diagnostics](omp-dependencies.md#download-interruption-diagnostics).

Current implementation, historical native smoke, real-service observations, and outstanding product acceptance are separate facts. Refer to [testing](testing.md), [known issues](known-issues.md), and [releases](releases.md). Machine-specific model choices and private deployment transcripts are not portable recipe defaults.
