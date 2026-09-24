import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createHash } from "node:crypto";
import { webMedia } from "../web-media.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1");
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "web-media-")), directory = join(root, "state/activity/web-files", "a".repeat(32));
  mkdirSync(directory, { recursive: true }); writeFileSync(join(directory, "input"), "fixture");
  const calls = [], validators = [], operation = { controller: new AbortController() };
  const runtime = { cwd: root, owner: { role: "manager" }, manifest: { plugins: ["pi-web"], options: {} },
    web: { current: () => operation, cleanup() {}, verifyExternal: fn => validators.push(fn), track: value => value },
    supervisor: { options: { endpoint: join(root, "state/activity/control/control.json") }, async call(method, args) {
      calls.push({ method, args });
      if (method === "ordinary_web_file_prepare") return { file_id: "b".repeat(64), directory, path: args.path, size: 7, sha256: createHash("sha256").update("fixture").digest("hex") };
      if (method === "ordinary_web_media_prepare") return { operation_id: "media-command", kind: "command", lease_id: "fixture-lease" };
      if (method === "reconcile") return { lease_id: "fixture-lease", protected: false, termination_evidence: { verified: true } };
      throw new Error("unexpected fixture method");
    } }, ordinaryOperations: { async write(ticket, _content, _digest, signal, callbacks) {
      calls.push({ method: "supervised-command", ticket, signal });
      callbacks.onCapture({ stdout: Buffer.from([0xff, 0xd8, 1, 2, 0xff, 0xd9]), stderr: Buffer.alloc(0) });
      return { stdout: "1.250000\n", stderr: "", exitCode: 0, truncated: false, terminationConfirmed: true };
    } } };
  globalThis[slot] = runtime; return { runtime, calls, validators, operation };
}
test("local frame and duration use the supervised command path and verified binary capture", async () => {
  const f = fixture();
  try {
    const frame = await webMedia("frame", "movie.mp4", 1);
    assert.equal(frame.mimeType, "image/jpeg"); assert.deepEqual(Buffer.from(frame.data, "base64"), Buffer.from([0xff, 0xd8, 1, 2, 0xff, 0xd9]));
    assert.equal(await webMedia("duration", "movie.mp4"), 1.25);
    assert.equal(f.calls.filter(row => row.method === "ordinary_web_file_prepare").length, 1);
    assert.equal(f.calls.filter(row => row.method === "supervised-command").length, 2);
    assert.equal(await f.validators[0](), true);
  } finally { delete globalThis[slot]; }
});
test("unverified, failed or truncated media cannot publish an image", async () => {
  for (const change of [{ terminationConfirmed: false }, { exitCode: 1 }, { truncated: true }]) {
    const f = fixture();
    try {
      f.runtime.ordinaryOperations.write = async () => ({ terminationConfirmed: true, exitCode: 0, truncated: false, ...change });
      await assert.rejects(webMedia("frame", "movie.mp4", 1), /WEB_MEDIA_FAILED/);
    } finally { delete globalThis[slot]; }
  }
});
