import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import dns from "node:dns";
import { FakeHost } from "./fake-host.mjs";

test("network and hosts cannot escape the default mock runner", () => {
  assert.throws(() => fetch("https://example.invalid"), /disabled/);
  assert.throws(() => dns.resolveTxt("example.invalid", () => {}), /disabled/);
  assert.throws(() => new dns.promises.Resolver().resolveMx("example.invalid"), /disabled/);
  assert.throws(() => process.kill(1, 0), /disabled/);
  for (const host of ["pi", "dsh", "codex"]) assert.throws(() => spawnSync(host), /disabled/);
  assert.throws(() => writeFileSync(fileURLToPath(import.meta.url), "overwrite"), { code: "ERR_ACCESS_DENIED" });
});

test("fake host rejects implicit success and returns only arranged results", async () => {
  const host = new FakeHost();
  await assert.rejects(host.invoke({ task: "fake" }), /queued result/);
  host.queue({ status: "failed" });
  assert.deepEqual(await host.invoke({ task: "fake" }), { status: "failed" });
  assert.equal(host.calls.length, 1);
});
