import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { runtimeModule } from "../runtime-module.ts";

test("worker runtime modules resolve from the selected slice and cannot escape via package entrypoints", async () => {
  const key = Symbol.for("agentcfg.pi.runtime.v1"), previous = globalThis[key], root = mkdtempSync(join(tmpdir(), "runtime-module-"));
  const inside = join(root, "runtime"), outside = join(root, "ambient");
  const write = (path, body) => { mkdirSync(join(path, ".."), { recursive: true }); writeFileSync(path, body); };
  const entry = "profile/node_modules/synthetic-sdk/index.js";
  write(join(inside, entry), "throw new Error('SDK must not execute during dependency resolution');");
  write(join(inside, "profile/node_modules/http-proxy-agent/package.json"), '{"name":"http-proxy-agent","type":"module","main":"index.js"}');
  write(join(inside, "profile/node_modules/http-proxy-agent/index.js"), 'export const fixture = "selected-profile";');
  write(join(outside, "package.json"), '{"name":"https-proxy-agent","type":"module","main":"index.js"}');
  write(join(outside, "index.js"), 'throw new Error("ambient dependency must not execute");');
  write(join(inside, "profile/node_modules/https-proxy-agent/package.json"), '{"name":"https-proxy-agent","type":"module","main":"../../../../ambient/index.js"}');
  globalThis[key] = { runtimeRoot: inside, installed: { entrypoint: entry } };
  try {
    assert.equal((await runtimeModule("http-proxy-agent")).fixture, "selected-profile");
    await assert.rejects(runtimeModule("https-proxy-agent"), /BOUNDARY/);
    await assert.rejects(runtimeModule("unselected"), /UNDECLARED/);
  } finally { globalThis[key] = previous; }
});
