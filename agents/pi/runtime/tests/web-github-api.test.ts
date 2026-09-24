import assert from "node:assert/strict";
import { test } from "node:test";
import { checkRepoSize, fetchViaApi } from "../../packages/web-vendor/github-api.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1"), variable = "AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA";
function fixture() {
  const calls = [];
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-web"], options: {}, web_config: {},
    web_services: { github: {} }, web_credential_variables: [variable] }, web: { async fetch(service, url, options) {
      calls.push({ service, url, options });
      const path = new URL(url).pathname;
      const body = path.includes("/git/trees/") ? { tree: [{ path: "src/index.ts" }], truncated: true }
        : path.endsWith("/readme") || path.includes("/contents/") ? { encoding: "base64", content: Buffer.from("fixture repository content").toString("base64") }
        : { size: 512, default_branch: "main" };
      return Response.json(body);
    } } };
  globalThis[slot] = runtime; return { runtime, calls };
}
test("GitHub API reads use the explicit service without CLI, ambient token or global account discovery", async () => {
  const f = fixture(), saved = process.env.GH_TOKEN;
  process.env.GH_TOKEN = "synthetic-unselected-global-token";
  try {
    assert.equal(await checkRepoSize("fixture", "repo"), 512);
    const result = await fetchViaApi("https://github.com/fixture/repo", "fixture", "repo", { type: "repo" });
    assert.match(result.content, /fixture repository content/); assert.match(result.content, /tree truncated/);
    assert.ok(f.calls.every(row => row.service === "github" && row.options.headers.get("Authorization") === null));
    delete f.runtime.manifest.web_services.github; f.calls.length = 0;
    assert.equal(await checkRepoSize("fixture", "repo"), null); assert.equal(f.calls.length, 0);
  } finally {
    delete globalThis[slot]; if (saved === undefined) delete process.env.GH_TOKEN; else process.env.GH_TOKEN = saved;
  }
});
test("GitHub files preserve encoded paths and only the declared credential", async () => {
  const f = fixture();
  f.runtime.manifest.web_config.githubToken = "$" + variable; process.env[variable] = "synthetic-selected-token";
  try {
    const result = await fetchViaApi("https://github.com/fixture/repo/blob/main/a%20b.txt", "fixture", "repo", { type: "blob", ref: "feature/fixture", path: "a b.txt" });
    assert.match(result.content, /fixture repository content/);
    assert.match(f.calls[0].url, /contents\/a%20b.txt\?ref=feature%2Ffixture/);
    assert.equal(f.calls[0].options.headers.get("Authorization"), "Bearer synthetic-selected-token");
    await assert.rejects(fetchViaApi("fixture", "fixture", "repo", { type: "blob", ref: "main", path: "../private" }), /PATH_INVALID/);
    await assert.rejects(checkRepoSize("fixture/other", "repo"), /REPOSITORY_INVALID/);
  } finally { delete globalThis[slot]; delete process.env[variable]; }
});
