import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { privatePluginStore } from "../plugin-storage.ts";

test("plugin credentials are isolated private instance files and cannot use an unselected capability", () => {
  const key = Symbol.for("agentcfg.pi.runtime.v1"), previous = globalThis[key];
  const root = mkdtempSync(join(tmpdir(), "plugin-store-")); mkdirSync(join(root, "pi-home"), { mode: 0o700 });
  globalThis[key] = { owner: { role: "manager" }, instanceRoot: root, manifest: { plugins: ["pi-mcp"], options: {} } };
  try {
    const store = privatePluginStore("pi-mcp", "mcp-auth");
    assert.equal(store.read("fixture"), undefined);
    store.write("fixture", "synthetic-private-token");
    assert.equal(store.read("fixture"), "synthetic-private-token");
    const files = readdirSync(join(root, "pi-home/mcp-auth"));
    assert.equal(files.length, 1); assert.match(files[0], /^[a-f0-9]{64}\.json$/);
    assert.equal(statSync(join(root, "pi-home/mcp-auth", files[0])).mode & 0o777, 0o600);
    globalThis[key].manifest.plugins = [];
    assert.throws(() => store.read("fixture"), /CAPABILITY_NOT_SELECTED/);
    globalThis[key].manifest.plugins = ["pi-mcp"];
    store.remove("fixture"); assert.equal(store.read("fixture"), undefined);
  } finally { globalThis[key] = previous; }
});
