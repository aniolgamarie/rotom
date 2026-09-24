import assert from "node:assert/strict";
import { test } from "node:test";
import { assertOAuthConfiguration, assertOAuthAuthorizationUrl, declaredMcpServer } from "../../packages/mcp-vendor/agentcfg-bindings.ts";

const slot = Symbol.for("agentcfg.pi.runtime.v1");
test("OAuth provider accepts only its selected server configuration and browser authorization origins", () => {
  const variable = "AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA";
  const original = process.env[variable]; process.env[variable] = "synthetic-client-secret";
  const oauth = { grantType: "authorization_code", clientId: "fixture", clientSecret: "${" + variable + "}", redirectUri: "https://callback.invalid/oauth" };
  const definition = { url: "https://service.invalid/mcp", auth: "oauth", oauth };
  globalThis[slot] = { owner: { role: "manager" }, manifest: { plugins: ["pi-mcp"], options: { mcp: { servers: {
    fixture: { oauth: { allowed_origins: ["https://auth.invalid"] } },
  } } }, mcp_config: { mcpServers: { fixture: definition } } } };
  try {
    declaredMcpServer("fixture", structuredClone(definition));
    assertOAuthConfiguration("fixture", definition.url, { ...oauth, clientSecret: "synthetic-client-secret" });
    assert.throws(() => assertOAuthConfiguration("fixture", definition.url, { ...oauth, clientSecret: "unselected" }), /CONFIG_MISMATCH/);
    assert.throws(() => assertOAuthConfiguration("fixture", "https://another.invalid/mcp", oauth), /UNSELECTED/);
    assertOAuthAuthorizationUrl("fixture", new URL("https://auth.invalid/authorize?state=fixture"));
    for (const url of ["https://unselected.invalid/authorize", "https://user:secret@auth.invalid/authorize", "http://auth.invalid/authorize"]) {
      assert.throws(() => assertOAuthAuthorizationUrl("fixture", new URL(url)), /AUTHORIZATION_ORIGIN/);
    }
  } finally { delete globalThis[slot]; if (original === undefined) delete process.env[variable]; else process.env[variable] = original; }
});

test("OAuth secrets stay literal and stored accounts follow client binding changes", async () => {
  const { resolveOAuthClientSecret, mcpAuthenticationAccount } = await import("../../packages/mcp-vendor/agentcfg-bindings.ts");
  const variable = "AGENTCFG_PI_CREDENTIAL_BBBBBBBBBBBBBBBB", old = process.env[variable];
  process.env[variable] = "!never-execute $env:NEVER_EXPAND";
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-mcp"], options: { mcp: { servers: { fixture: { oauth: { client_id: "first" } } } } },
    mcp_config: { mcpServers: { fixture: { url: "https://service.invalid/mcp", auth: "oauth", oauth: { clientId: "first" } } } } } };
  globalThis[slot] = runtime;
  try {
    assert.equal(resolveOAuthClientSecret("${" + variable + "}"), "!never-execute $env:NEVER_EXPAND");
    assert.throws(() => resolveOAuthClientSecret("${UNSELECTED_SECRET}"), /CREDENTIAL_REQUIRED/);
    const first = mcpAuthenticationAccount("fixture");
    runtime.manifest.mcp_config.mcpServers.fixture.oauth.clientId = "second";
    assert.notEqual(mcpAuthenticationAccount("fixture"), first);
    assert.throws(() => mcpAuthenticationAccount("unselected"), /ACCOUNT_UNSELECTED/);
  } finally { delete globalThis[slot]; if (old === undefined) delete process.env[variable]; else process.env[variable] = old; }
});
