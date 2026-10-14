# OMP model presets

The model pool provides candidates; presets combine models for ordinary work, lightweight tasks, planning, and deeper analysis. rotom maps `agent_options.model_presets` to official OMP `modelPresets`, using public OMP 18.8.6 configuration/commands without upstream patches.

`omp-default` provides basic and deepseek-payg, with basic initial roles. `omp-kernel` adds tf, cursor, and deepseek-tf-payg, for five presets. Kernel's global initial roles retain the existing TF choices; explicit private Cursor role overrides still win. Adding presets does not switch deployed roles or log in accounts automatically.

## Role combinations

| Role | basic: official Coding Plan | tf: private gateway | deepseek-payg / deepseek-tf-payg |
| --- | --- | --- | --- |
| main / native default | Kimi Code · high | Kimi TF `kimi-for-coding` · high | Corresponding endpoint Flash · high |
| smol | GLM `glm-5.3-flash` · low | GLM TF Flash · low | Flash · low |
| slow | Kimi Code · max | Kimi TF `k3` · high | Flash · max |
| plan | GLM `glm-5.3` · high | GLM TF `glm-5.3` · high | Flash · high |
| task | Kimi Code · high | Kimi TF `kimi-for-coding` · high | Flash · high |
| advisor | GLM `glm-5.3` · high | GLM TF `glm-5.3` · high | Flash · max |
| vision | GLM Flash · high | GLM TF Flash · high | Flash · high |
| tiny | Local `lfm2.5-230m` | Same | Same |

Kimi Code means `kimi-for-coding`; basic and official DeepSeek use the repository's default Anthropic-compatible endpoints. DeepSeek Pro, other K3 variants, and HighSpeed remain in the pool without being added to these base role combinations or automatic paid fallback chains.

Cursor uses these logical selectors:

| Role | Native selector |
| --- | --- |
| main | `cursor/kimi-k3:high` |
| smol | `cursor/composer-2.5:low` |
| slow | `cursor/kimi-k3:max` |
| plan | `cursor/glm-5.2:high` |
| task | `cursor/composer-2.5:medium` |
| advisor | `cursor/grok-4.7:high` |
| vision | `cursor/kimi-k3:high` |
| tiny | `local/lfm2.5-230m` |

These candidates came from an account-scoped local OMP model-catalog cache dated 2026-10-06, not a universal public catalog or successful live inference. Kimi K3 declares low/high/max; Cursor GLM 5.2 high/max; Composer 2.5 minimal/low/medium/high; Grok 4.7 low/medium/high/xhigh. GPT/Claude/Gemini candidates absent from that catalog were not added. Cursor GLM 5.2 is a distinct route from official Coding Plan GLM 5.3; names do not authorize automatic upgrades.

Cached contexts were Composer 200000, Grok 256000, GLM 1000000, and Kimi 1048576. Check context budgets before moving a long conversation to a smaller model. Images also depend on actual transport. TF image requests, current account permissions, and quotas require live verification. Custom private Cursor selectors validate selected OAuth provider, syntax, and known effort levels; a static declaration does not prove account entitlement.

## Switching and configuration ownership

After deploying, enter native commands inside OMP:

```text
/modelpreset list
/modelpreset switch basic
/modelpreset switch tf
/modelpreset switch cursor
/modelpreset switch deepseek-payg
/modelpreset switch deepseek-tf-payg
```

`./agentcfg model presets` lists rotom's official optional model pool; OMP `/modelpreset` switches role combinations.

`modelRoleStorage: project` stores native switches in the current cwd's `.omp/config.yml`, preserving global managed initial roles. Presets specify all eight supported roles and remote efforts without defaultThinkingLevel, so switching does not alter global thinking level. Restarting in that directory reads project roles; entering a subdirectory does not inherit the ancestor file. Ancestor role files still pass source validation, and valid role-only files do not block child-directory startup.

Project configuration may contain only modelRoles, assigning some/all of default/smol/slow/vision/plan/advisor/task/tiny. Empty files/maps restore global roles. Each assignment must match the exact model/effort in a declared preset or explicit global initial role; tiny accepts only the fixed local model. Pool membership alone does not authorize an execution role: unassigned DeepSeek Pro or undeclared Cursor selectors fail. For persistent custom roles, first declare private role intent or agent_options.model_presets. For one-off selection, use native `/switch`.

Startup rejects other project settings, duplicate keys, YAML aliases, links, nonregular files, and excessive size. Project role support does not enable project skills, MCP, plugins, permissions, or authentication.

Rotom owns each `/modelPresets/<name>` it declares, preserving other user names created with `/modelpreset save personal`. User presets assigning undeclared combinations also need private intent before their project roles can persist. Native save over a managed name causes drift; edit private agent_options.model_presets, then plan/apply. Private roles determine global initial configuration; explicitly selected project presets take precedence according to OMP's public rules.

## Execution fallback and permission review

Native presets switch roles, not retry.fallbackChains. Chains match endpoint, model, and effort: basic stays within official Kimi/GLM; tf stays within Kimi TF/GLM TF; cursor retains only two Composer 2.5 → Kimi 2.7 Code chains.

K3 uses three empty chains keyed by actual catalog member IDs `cursor/kimi-k3-low`, `cursor/kimi-k3-high`, and `cursor/kimi-k3-max`, without effort suffixes. Empty GLM 5.2 high/max and Grok 4.7 high chains remain. The logical picker selector `cursor/kimi-k3:<effort>` resolves via current member metadata to its empty chain, preventing a role/default fallback. A logical picker name is not a registered model ID and is not used as a chain key. There is no provider-wide Cursor empty-chain override.

Cursor K3 rejects assistant history produced by another model, including error/aborted assistant entries. Restart K3 in a **new session**. The fallback configuration prevents further automatic mixing but does not repair already affected history. See [known issues](known-issues.md). Kernel's former generic role-based TF chain/old GLM default dependency is removed. Roles sharing a model/effort also share its execution chain. Metered DeepSeek is absent from subscription/TF/Cursor automatic chains.

DeepSeek presets require an explicit user switch. They neither cross official/TF endpoints automatically nor fall back to Pro automatically. Other failures use native retry/error behavior; optional pool membership is not paid-fallback authorization.

Permission review is independent. Kernel's public reviewer_model is GLM TF Flash, with Kimi TF kimi-for-coding as remote_fallback_model. Valid allow/ask/deny decisions are not reviewed again; only runtime failure triggers the remote fallback. Tiny remains an installed-only conservative ask/deny fallback. Explicit private reviewer/fallback/mode settings take precedence, and preset switching does not change the permission sidecar.

Private `reviewer_model = "session"` explicitly restores session-following review; omitting it retains the public default. Remote fallback must name a selected concrete model and cannot be session. Session-following still applies the documented unsupported-transport fallback behavior. See [OMP](omp.md) and [approval diagnostics](omp-approval-diagnostics.md).

Offline configuration checks and the historical local deployment establish configuration/ownership behavior within their recorded scope, not current live Cursor/TF inference, image transport, or account availability. Official plan keys and independent TF keys must be entered as needed. See [testing](testing.md), [releases](releases.md), and [local configuration](local-config.md).
