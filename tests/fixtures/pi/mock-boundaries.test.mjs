import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import dns from "node:dns";
import { FakeHost } from "./fake-host.mjs";

test("network and hosts cannot escape the default mock runner", () => {
  assert.throws(() => fetch("https://example.invalid"), /disabled/);
  assert.throws(() => dns.resolveTxt("example.invalid", () => {}), /disabled/);
  assert.throws(() => new dns.promises.Resolver().resolveMx("example.invalid"), /disabled/);
  assert.throws(() => process.kill(1, 0), /disabled/);
  for (const host of ["pi", "dsh", "codex"]) assert.throws(() => spawnSync(host), /disabled/);
  const target = fileURLToPath(import.meta.url), before = readFileSync(target);
  // Node权限模式与bwrap只读挂载均拒写，必须保留同一个真实文件的原字节。
  assert.throws(() => writeFileSync(target, "overwrite"), error => error.code === "ERR_ACCESS_DENIED" || error.code === "EROFS");
  assert.deepEqual(readFileSync(target), before);
});

test("fake host rejects implicit success and returns only arranged results", async () => {
  const host = new FakeHost();
  await assert.rejects(host.invoke({ task: "fake" }), /queued result/);
  host.queue({ status: "failed" });
  assert.deepEqual(await host.invoke({ task: "fake" }), { status: "failed" });
  assert.equal(host.calls.length, 1);
});
