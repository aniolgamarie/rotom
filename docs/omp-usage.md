# Querying OMP usage

`agentcfg usage` supports native and managed modes. Isolated tests cover dispatch and protection boundaries; real-account usage results require separate validation. See [testing](testing.md).

## Native mode

With no manager `--profile`, `--local`, or `--machine`, the command uses OMP from PATH and preserves the caller's environment and working directory. It does not load rotom machine configuration, SecretStore, or deployment state.

```sh
./agentcfg usage --json
./agentcfg usage -- --provider openai-codex --json
```

Arguments following `usage` pass through to `omp usage`, removing at most one leading `--`. A trailing `--profile` belongs to upstream usage syntax; the manager does not reinterpret it as a global selector. Native environment selectors are interpreted by OMP.

## Managed mode

An explicit manager `--profile ID` selects that deployed OMP identity and locked binary. Global selectors precede the command:

```sh
./agentcfg --local /private/local.toml --profile omp-default usage -- --json
```

The child argv is `<locked-omp> --profile <native-name> usage <tail>` and cwd is the instance HOME. Managed usage checks ownership, pending state, configuration references, discovery, and runtime integrity, then holds the same shared lease as managed run. It may coexist with run sessions; configuration writers require exclusive access. Only environment/authentication needed for the query is used, so unrelated provider or MCP secrets do not block it.

`--local` or `--machine` without `--profile` returns 2. Selecting DSH or Pi also returns 2. The manager neither guesses an OMP profile nor aggregates profiles.

## Output and side effects

Native stdout/stderr pass through without manager text around machine output. Native exit status is preserved; signals follow `128 + signal`. Upstream defines unsupported providers, missing authentication, partial failures, reporting windows, and caches. Missing data is never rewritten as zero usage.

An explicit query may make native network requests, write caches, or refresh authentication. It does not install, deploy, log in interactively, or call a model. Native mode retains upstream authentication-sharing behavior. Managed mode disables broker/gateway access and uses the managed native identity.

| Condition | Result |
| --- | --- |
| OMP absent from PATH in native mode | 5; prepare it explicitly |
| Managed runtime missing or damaged | 5; explicit `sync`, then `apply` if needed |
| Ownership or pending-state conflict | 4; resolve the report before recovery |
| Tail attempts to override managed identity/discovery | 2; use manager selectors |
| Native login missing or provider unsupported | Preserve upstream output and status |

Historical review of OMP v18.3.0 found 20 usage providers, including `openai-codex`, `kimi-code`, and `zai`. This is historical registry evidence, not a current-version or real-account support claim. `zai` denotes the international service and does not establish support for domestic `zhipu-coding-plan`. The official [Coding Tool Helper](https://docs.bigmodel.cn/cn/coding-plan/extension/coding-tool-helper) documents a usage plugin, but its interface and OMP integration have not been validated here. agentcfg does not scrape cookies or provide a separate collector. Current validation gaps are tracked in [known issues](known-issues.md).
