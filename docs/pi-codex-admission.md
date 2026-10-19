# Restricted admission for the official Codex CLI

> Historical reference for the retired Pi SDK/four-profile integration. Its commands, roles,
> plugins and support claims do not apply to current Base/Pro and must not be used as current
> operating instructions. The original body remains for historical scope only. See the
> [current Pi guide](pi.md), [migration boundary](pi-migration.md) and [support matrix](pi-support.md).


agentcfg pins official Codex 0.154.0. model-delegate manages its native tools, sandbox, and physical lifecycle. When configuration sources cannot be verified, execution is refused; this deliberately leaves compatibility gaps.

Linux packages include the matching official bwrap at `bin/codex-resources/bwrap` with its license. All four platform packages also include the primary release's `codex-code-mode-host` and `codex-responses-api-proxy`, which are internal CLI dependencies rather than additional delegation entry points. Installing only the Codex executable archive is insufficient. Older system bwrap versions may lack required options. The CLI verifies the bundled bwrap's compiled digest; agentcfg also verifies release digests and architecture. See the pinned [upstream implementation](https://raw.githubusercontent.com/openai/codex/rust-v0.154.0/codex-rs/linux-sandbox/src/bundled_bwrap.rs).

## Admission conditions

- `/etc/codex` is absent or empty with verifiable identity/permissions. Any content, including an empty configuration file, rule, skill, or broken link, is rejected.
- macOS `com.openai.codex` preferences contain neither `config_toml_base64` nor `requirements_toml_base64`. The check uses the same CoreFoundation API as the CLI; inspecting plist files alone is insufficient.
- The selected instance's `codex-home/auth.json` is current-user-owned, mode 0600, and an ordinary single-link file. Explicit API-key mode or recognizable personal OAuth plans `free/go/plus/pro/prolite` can proceed; authentication itself remains the official CLI's responsibility.
- Organization accounts, unknown plans, mixed identities, Agent Identity, PAT, Bedrock, and other unverifiable combinations are rejected without switching accounts.
- Machine management configuration and account ownership/type remain stable during execution. Parent and worker recheck before start. This is not an atomic same-process configuration guarantee and does not cover concurrent administrator changes or account-type changes after refresh.

Every start/resume rechecks admission. Policy `official-cli-restricted-v1` participates in execution identity; an older policy cannot authorize a new run.

## Explicit service endpoints and search

The seven purpose presets, including `research`, add no authorization. `native_execution.web_search` defaults to `disabled`; only explicit `cached` or `live` enables the corresponding official search capability. It is part of frozen execution policy. `tool_network="none"` continues to deny local-tool networking; official server-side search uses the selected model-service route.

The default is the official OpenAI endpoint. API-key mode may explicitly set `agent_options.model_delegate.codex.api_base_url` in private machine configuration for a compatible Responses service. It never falls back to `OPENAI_BASE_URL` or native user configuration. Use HTTPS without userinfo, query, or fragment; isolated tests may use HTTP with a numeric loopback address. The address is frozen into execution policy/identity; changing it prevents reuse of old admission.

Custom endpoints require an explicit API-key account, checked by both parent and worker. Personal OAuth/unknown accounts are rejected before CLI start so personal tokens cannot reach a custom service. Keep keys in native instance `codex-home/auth.json`, never in the URL.

## Refusal codes

| Code | Meaning and response |
| --- | --- |
| `CODEX_SYSTEM_CONFIG_PRESENT` | System directory has content; retain administrator configuration and use a compatible environment |
| `CODEX_SYSTEM_CONFIG_UNVERIFIED` | Directory access/identity/permissions cannot be verified; administrator review is required |
| `CODEX_MANAGED_PREFERENCES_PRESENT` | macOS managed preferences make this route unsupported |
| `CODEX_MANAGED_PREFERENCES_UNVERIFIED` | CoreFoundation query failed/unavailable; absence cannot be assumed |
| `CODEX_ORGANIZATION_ACCOUNT_UNSUPPORTED` | Organization account is outside restricted support |
| `CODEX_ACCOUNT_CONFIG_UNVERIFIED` | Unsafe/unknown authentication format or account type; use the instance's explicit login flow |
| `CODEX_LOGIN_CONFIG_UNVERIFIED` | Login cannot ignore existing instance config.toml; use a clean instance without automatic deletion |
| `CODEX_CUSTOM_ENDPOINT_REQUIRES_API_KEY` | Keep personal OAuth on the official endpoint or explicitly choose API-key authentication |
| `CODEX_CONFIG_PLATFORM_UNSUPPORTED` | No admission implementation for this OS |

Admission failures return 5; missing authentication still returns 3. Refusal occurs before model execution. Diagnostics expose only fixed reason codes, not configuration bodies, tokens, emails, or account IDs. `doctor` reports `configuration_admission` conditions as `not-inspected` without reading authentication files.

## Process termination boundary

On Linux, the entire delegation runs in a separate PID namespace created by bundled bwrap. A first-party PID 1 waits for a supervisor start byte. The supervisor verifies and records initializer/wrapper identities before releasing execution; closed input does not release it. Native Codex policy still enforces frozen model file permissions.

Stop uses pidfd against the verified PID 1. When it exits, the kernel terminates all namespace processes, including separate process groups and reparented descendants; see [Linux PID namespaces](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html). Missing kernel support, handshake, or identity verification refuses execution without falling back to a weaker process-group model.

Version 3 normal-exit records verify both initializer and bwrap wrapper. A proven terminated namespace cannot revive; later unrelated PID reuse does not revoke that proof. Old v1/v2 and escaped/unknown records retain protection and are not cleared by upgrading. macOS uses its separate libproc/helper route and requires independent native evidence. This adds neither an MCP bridge nor another task queue.

## Evidence boundary

Native readonly/write cases use synthetic API keys and an isolated loopback Responses service through the real model-delegate entry. Readonly checks native reads and write refusal; write uses an independent Git worktree to check explicit authorization, receipts, and original-project preservation. Implementing these cases or passing offline regressions does not establish execution on the final candidate. The complete Pi lock has been rebuilt; the historical Codex native/cold evidence here still belongs to candidate `9d6a9270…`. See [Pi diagnostics](pi-diagnostics.md), [testing](testing.md), and [known issues](known-issues.md).
