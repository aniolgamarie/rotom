# pi-mcp-adapter in agentcfg

Derived from pi-mcp-adapter 2.32.1 (MIT); SOURCE.json records the original npm integrity and file digests. This fork is 2.32.1-agentcfg.1. The full patch is agents/pi/build/mcp-agentcfg.patch in the source repository.

Configuration comes only from the selected agentcfg manifest. Stdio uses the existing supervisor and AgentManager with a declared command. HTTP/SSE and OAuth use explicit routes and allowed origins; credential commands and OS keyring fallback are not used. Credentials and caches belong to the instance and authentication binding. Old plaintext credentials are neither imported nor deleted.

Sampling uses the constrained ModelRuntime and explicit limits. Scripting uses a supervised private Node process with no direct workspace, account environment or network access. Direct tools and namespace proxies use registered service ownership and main-role admission.

OAuth callbacks and MCP Apps loopback listeners are owned by the existing manager within the supervisor-owned Pi process. Apps host/proxy ports share one record, and shutdown waits for owned requests. Browser origins and permissions need explicit selection. Apps, OAuth and elicitation URLs are handed to the user's browser through terminal links; automatic desktop/Glimpse/global-npm discovery is replaced by this common browser flow. App requests for new agent turns require interactive confirmation.

The source is registered in all four recipes. Final dependency locks, native loading, OS listener behavior, browser UI and live service acceptance remain unverified. Original helper modules retained for source history are not an authorization to run their old discovery or credential paths.

Direct and namespace registrations are bound to their adapter generation and
runtime. Cleanup from an older generation cannot remove a current registration.
MCP and Web registrations share tool-name ownership, including reserved native
and ReadSeek names.
