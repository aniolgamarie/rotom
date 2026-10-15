# Pi MCP configuration and boundaries

MCP support is declared for the four Pi profiles. Source integration, isolated tests, and historical temporary installation are separate from native loading, OAuth, browser UI, and live-service acceptance. The complete Pi lock has been rebuilt; consult [testing](testing.md) and [known issues](known-issues.md) for the current feature-specific evidence.

## Service selection

Only registry services selected by the profile are loaded. Each needs a matching `agent_options.mcp.servers` binding. Global HOME, project MCP files, and environment service lists are not scanned.

- stdio: `command_ref` selects an explicit interactive `external_tools` binding. Registry command/args must match exactly. Processes use the existing manager/supervisor and declared file scope.
- HTTP/SSE: declare `network_route` and `authentication="none"`, `"bearer"`, or `"oauth"`. The route's `service_ids` must include `mcp:SERVICE`. Bearer/client secrets use that service's SecretRef.
- HTTP fixes the origin/route and does not follow redirects or fall back to direct access after proxy failure. Shutdown cancels active requests and unfinished bodies.

See [service examples](../examples/pi-services.toml). Bearer success does not establish OAuth support.

## OAuth and direct tools

Replace a service binding with an explicit OAuth declaration. Use real declared origins/URIs. Public clients omit registry `credential_ref`; confidential clients provide `client_id` and a reference to the client secret, not a reused bearer token.

```toml
[overrides.profiles.pi-default.agent_options.mcp.servers.documentation]
transport = "streamable-http"
network_route = "documentation-proxy"
authentication = "oauth"

[overrides.profiles.pi-default.agent_options.mcp.servers.documentation.oauth]
grant_type = "authorization_code"
allowed_origins = ["https://auth.example.invalid"]
redirect_uri = "http://localhost:8765/callback"
# client_id = "YOUR_REGISTERED_CLIENT_ID"
# auth_server_metadata_url = "https://auth.example.invalid/.well-known/oauth-authorization-server"

[overrides.profiles.pi-default.agent_options.mcp.servers.documentation.direct_tools]
enabled = true
tools = ["search"]
```

Local callbacks bind only the declared loopback port. HTTPS remote callbacks use the full callback URL for manual completion. `client_credentials` requires client_id and the service SecretRef and disallows redirect_uri. Discovery, exchange, refresh, and authorization URLs must belong to authorized origins. Secrets are literal values: `!` and environment-like text never execute or expand.

Credentials/cache are isolated by instance and authentication binding. Changed client identity cannot reuse the old account. Old plaintext files are neither imported nor deleted; system Keychain/keyring is not a fallback.

Direct tools default off. Omitting `tools` selects all discovered direct tools for that service; a list selects original names. Grouped `mcp__SERVICE` and direct tools both require real registered entries; a forged name prefix grants no permission. Only the main role can call them. Revocation invalidates old functions.

## Sampling

Sampling defaults off:

```toml
[overrides.profiles.pi-default.agent_options.mcp.sampling]
enabled = true
model = "agentcfg-example/fictional-exact-model"
max_tokens = 1024
auto_approve = false
```

The model must be an explicitly selected native provider/model in this instance. Omission uses the current main model within the same constrained set. Remote hints never trigger model switching or account discovery. Calls use the same ModelRuntime with zero retries; requests beyond the token cap fail.

Default confirmation occurs before sending a request and before returning its result to the service. Only explicit `auto_approve=true` removes these confirmations. Managed calls are rejected; active Task Keeper work still imposes ordinary helper boundaries.

## Elicitation

Enable `agent_options.mcp.elicitation=true` explicitly. Forms retain confirmation/submission steps. URL elicitation permits only HTTP(S), without userinfo or control characters. An OSC 8 link appears only after the user chooses to show it; the user opens a browser, and the plugin does not launch one. URL mock checks do not establish form-validator or real-terminal behavior. This is distinct from MCP Apps.

## Multi-tool scripting

Scripting defaults off and requires an explicit locked-version Node binding:

```toml
[overrides.profiles.pi-default.agent_options.mcp.scripting]
enabled = true
tool_ref = "mcp-script-node"
max_seconds = 30

[overrides.profiles.pi-default.agent_options.external_tools.mcp-script-node]
executable = "/absolute/path/to/node"
version = "v24.14.0"
args = []
```

The selected Permission Policy must also grant the command:

```json
{"id":"mcp-script-node","kind":"command","effect":"allow","command_ref":"tool:mcp-script-node","tool_ids":["bash"],"operations":["execute"]}
```

`mcpScript` is main-only. The supervisor fixes the entry/interpreter identity. Scripts arrive on stdin and run in per-execution private directories with no network, project worktree, account environment, or parent supervisor credentials. The JavaScript VM supplies computation context; the process sandbox enforces actual file/network boundaries.

`tools.call/search/describe` dispatch back to the parent and remain limited to selected MCP capabilities. Timeout/cancellation stops the supervised process and waits for physical termination. Shutdown also waits for dispatched requests. Unproven termination retains protection and is not success.

## MCP Apps

```toml
[overrides.profiles.pi-default.agent_options.mcp.apps]
enabled = true
browser_network = "user-browser"
host_port = 0
proxy_port = 0
max_seconds = 1800
allowed_browser_origins = []
permissions = []
```

Both ports bind only `127.0.0.1`; zero requests an OS-selected port, and fixed ports must differ. They share one existing-manager activity record; the supervisor tracks the parent Pi process. Shutdown closes connections and waits for outstanding requests. Unknown closure does not count as release.

Users open the terminal link in a standard browser. Remote use needs both loopback ports forwarded. External browser traffic uses the user's browser network, not agentcfg service proxies. External origins must be in `allowed_browser_origins`; camera, microphone, location, and clipboard permissions require explicit selection. App requests for a new agent turn also require Pi UI confirmation.

## Capacity and stdio networking

Finite execution tasks and long-lived stdio services use the same manager/supervisor with separate caps: at most 2 execution tasks, at most 16 services, and at most 16 total resource records. File scopes, worktree leases, and termination proofs remain effective. A service with a writable project root holds that write lease throughout its lifetime and cannot coexist with another writer in the same workspace. Only matched MCP stdio admission assigns the service category; a model cannot relabel a task to bypass limits.

stdio uses a no-external-network file sandbox and minimal environment without machine proxies, login environment, or system configuration. Services requiring remote network/authentication should use explicit HTTP/SSE bindings. Selecting an arbitrary network-dependent local program as stdio does not grant networking.

## Validation

Type checks, isolated regressions, and temporary installs establish only their stated layers. Current-lock freezing, native behavior on each platform, browser interaction, and live MCP/OAuth services require matching evidence. No MCP live pass is implied; see [Pi diagnostics](pi-diagnostics.md) and [roadmap](roadmap.md).
