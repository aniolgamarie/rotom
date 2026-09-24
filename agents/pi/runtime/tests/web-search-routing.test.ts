import assert from "node:assert/strict";
import { test } from "node:test";
const slot = Symbol.for("agentcfg.pi.runtime.v1"), variable = "AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA";
test("actual aggregate search dispatches only selected providers, including explicit provider arrays", async () => {
  const calls = [];
  const runtime = { instanceRoot: "/fixture/instance", owner: { role: "manager" }, manifest: { plugins: ["pi-web"], options: {},
    web_services: { brave: {} }, web_config: { provider: "brave", braveApiKey: "$" + variable }, web_credential_variables: [variable] },
    web: { async fetch(service, input) {
      calls.push(service); return Response.json({ web: { results: [{ title: "Fixture result", url: "https://example.invalid/result", description: "Fixture evidence" }] } });
    } } };
  globalThis[slot] = runtime; process.env[variable] = "synthetic-brave";
  try {
    const { search } = await import("../../packages/web-vendor/gemini-search.ts");
    const result = await search("fixture query", { provider: ["brave"] });
    assert.match(result.answer, /Fixture/); assert.deepEqual(calls, ["brave"]);
    const combined = await search("fixture query", { provider: "all" });
    assert.match(combined.answer, /Fixture/); assert.deepEqual(calls, ["brave", "brave"]);
    const before = calls.length;
    await assert.rejects(search("fixture query", { provider: "exa" }), error => error.code === "WEB_SERVICE_NOT_SELECTED" && error.exitCode === 2);
    assert.equal(calls.length, before);
  } finally { delete globalThis[slot]; delete process.env[variable]; }
});
