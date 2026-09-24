import assert from "node:assert/strict";
import { test } from "node:test";
import { authenticatedWebFetch } from "../web-auth-fetch.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1"), variable = "AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA";
function fixture() {
  const calls = [], controller = new AbortController();
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-web"], options: {}, web_credential_variables: [variable],
    web_auth_fetch: { docs: { origins: ["https://private.example.invalid"], cookie_reference: "$" + variable } } },
    web: { current: () => ({ controller }), async fetch(service, url, init) { calls.push({ service, url: url.href, init }); return new Response("fixture page"); } } };
  globalThis[slot] = runtime; process.env[variable] = "session=synthetic-fixture";
  return { runtime, calls, controller, cleanup() { delete globalThis[slot]; delete process.env[variable]; } };
}
test("authenticated pages use the selected profile cookie and require manual redirect checks", async () => {
  const f = fixture();
  try {
    const result = await authenticatedWebFetch(f.runtime, "docs", "https://private.example.invalid/path", { redirect: "follow", headers: { accept: "text/html" } });
    assert.equal(await result.text(), "fixture page"); assert.equal(f.calls.length, 1);
    assert.equal(f.calls[0].service, "authenticated"); assert.equal(f.calls[0].init.redirect, "manual");
    assert.equal(f.calls[0].init.headers.get("cookie"), "session=synthetic-fixture");
  } finally { f.cleanup(); }
});
test("foreign origins, methods and credentials fail before dispatch", async () => {
  const f = fixture();
  try {
    for (const url of ["http://private.example.invalid", "https://sub.private.example.invalid", "https://private.example.invalid:8443", "https://user:secret@private.example.invalid"]) {
      await assert.rejects(authenticatedWebFetch(f.runtime, "docs", url), /ORIGIN/);
    }
    await assert.rejects(authenticatedWebFetch(f.runtime, "missing", "https://private.example.invalid"), /NOT_SELECTED/);
    await assert.rejects(authenticatedWebFetch(f.runtime, "docs", "https://private.example.invalid", { method: "POST", body: "unexpected" }), /METHOD/);
    await assert.rejects(authenticatedWebFetch(f.runtime, "docs", "https://private.example.invalid", { headers: { cookie: "unselected" } }), /OVERRIDE/);
    assert.equal(f.calls.length, 0);
  } finally { f.cleanup(); }
});
test("cancellation and runtime replacement cannot obtain or send another session's cookie", async () => {
  const f = fixture();
  try {
    f.controller.abort(); await assert.rejects(authenticatedWebFetch(f.runtime, "docs", "https://private.example.invalid"), /abort/i);
    globalThis[slot] = { ...f.runtime };
    await assert.rejects(authenticatedWebFetch(f.runtime, "docs", "https://private.example.invalid"), /STALE/);
    assert.equal(f.calls.length, 0);
  } finally { f.cleanup(); }
});
