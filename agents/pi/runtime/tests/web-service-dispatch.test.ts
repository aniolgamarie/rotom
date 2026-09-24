import assert from "node:assert/strict";
import { test } from "node:test";
const slot = Symbol.for("agentcfg.pi.runtime.v1"), variable = "AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA";
test("SearXNG auth headers and Kagi/Ollama extraction use their declared API services rather than the public fetch transport", async () => {
  const requests = [], runtime = { owner: { role: "manager" }, instanceRoot: "/fixture/instance", manifest: {
    plugins: ["pi-web"], options: {}, web_services: { searxng: {}, kagi: {}, ollama: {} }, web_credential_variables: [variable],
    web_config: { searxngBaseUrl: "https://search.invalid", searxngHeaders: { "CF-Access-Client-Secret": "$" + variable },
      kagiApiKey: "$" + variable, ollamaApiKey: "$" + variable },
  }, web: { async fetch(service, url, options) {
    requests.push({ service, url, options });
    if (service === "searxng") return Response.json({ results: [{ title: "fixture", url: "https://8.8.8.8/article", content: "synthetic text" }] });
    if (service === "kagi") return Response.json({ data: [{ url: "https://8.8.8.8/article", markdown: "synthetic kagi text", title: "fixture" }] });
    if (service === "ollama") return Response.json({ title: "fixture", content: "synthetic ollama text", links: [] });
    throw new Error("unselected public transport");
  } } };
  globalThis[slot] = runtime; process.env[variable] = "synthetic-header";
  try {
    const { searchWithSearXNG } = await import("../../packages/web-vendor/searxng.ts");
    const { extractWithKagi } = await import("../../packages/web-vendor/kagi.ts");
    const { extractWithOllama } = await import("../../packages/web-vendor/ollama.ts");
    const search = await searchWithSearXNG("fixture"); assert.equal(search.results.length, 1);
    assert.equal(new Headers(requests[0].options.headers).get("CF-Access-Client-Secret"), "synthetic-header");
    await extractWithKagi("https://8.8.8.8/article"); await extractWithOllama("https://8.8.8.8/article");
    assert.deepEqual(requests.map(row => row.service), ["searxng", "kagi", "ollama"]);
    assert.equal(new Headers(requests[1].options.headers).get("Authorization"), "Bearer synthetic-header");
    assert.equal(new Headers(requests[2].options.headers).get("Authorization"), "Bearer synthetic-header");
  } finally { delete globalThis[slot]; delete process.env[variable]; }
});
