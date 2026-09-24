import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, chmodSync, statSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { webCacheDirectory } from "../web-config.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1");
test("Web cached result writes require their live operation and in-memory results belong to one runtime", async () => {
  const first = { owner: { role: "manager" }, instanceRoot: "/fixture/one", manifest: { plugins: ["pi-web"], options: {} },
    web: { current() { return { id: "operation" }; } } };
  globalThis[slot] = first;
  try {
    const { storeResult, storeFetchedContentResult, getAllResults, getResult } = await import("../../packages/web-vendor/storage.ts");
    const row = { id: "fixture", type: "search", timestamp: Date.now(), queries: [] };
    storeResult("fixture", row); assert.deepEqual(getResult("fixture"), row);
    const second = { ...first, instanceRoot: "/fixture/two", web: { current() { throw new Error("WEB_OPERATION_CLOSED"); } } };
    globalThis[slot] = second;
    assert.deepEqual(getAllResults(), []);
    assert.throws(() => storeResult("late", row), /WEB_OPERATION_CLOSED/);
    assert.throws(() => storeFetchedContentResult("late", { ...row, type: "fetch", urls: [] }), /WEB_OPERATION_CLOSED/);
    assert.deepEqual(getAllResults(), []);
    globalThis[slot] = first;
    assert.deepEqual(getResult("fixture"), row);
  } finally { delete globalThis[slot]; }
});

test("Web cache creates only private instance directories and does not repair unsafe existing ownership", () => {
  const root = mkdtempSync(join(tmpdir(), "web-cache-")); chmodSync(root, 0o700);
  const runtime = { owner: { role: "manager" }, instanceRoot: root, manifest: { plugins: ["pi-web"] } };
  globalThis[slot] = runtime;
  try {
    assert.equal(webCacheDirectory(false), null);
    mkdirSync(join(root, "pi-home"), { mode: 0o700 }); chmodSync(join(root, "pi-home"), 0o755);
    assert.throws(() => webCacheDirectory(true), /WEB_CACHE_OWNERSHIP/);
    assert.equal(statSync(join(root, "pi-home")).mode & 0o777, 0o755);
    chmodSync(join(root, "pi-home"), 0o700);
    const path = webCacheDirectory(true);
    assert.equal(path, join(root, "pi-home/web/web-search-cache")); assert.equal(statSync(path).mode & 0o777, 0o700);
  } finally { delete globalThis[slot]; rmSync(root, { recursive: true, force: true }); }
});
