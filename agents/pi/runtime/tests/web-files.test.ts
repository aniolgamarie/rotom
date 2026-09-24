import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createHash } from "node:crypto";
import { webLocalFile, webReadLocalFile } from "../web-files.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1");
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "web-file-")), directory = join(root, "state/activity/web-files", "a".repeat(32));
  mkdirSync(directory, { recursive: true, mode: 0o700 }); writeFileSync(join(directory, "input"), "fixture media");
  const calls = [], cleanups = [], operation = { controller: new AbortController() };
  const runtime = { cwd: join(root, "project"), owner: { role: "manager" }, manifest: { plugins: ["pi-web"], options: {} },
    web: { current: () => operation, cleanup: callback => cleanups.push(callback) },
    supervisor: { options: { endpoint: join(root, "state/activity/control/control.json") }, async call(method, args) {
      calls.push({ method, args });
      if (method === "ordinary_web_file_prepare") return { file_id: "b".repeat(64), directory, path: args.path, size: 13,
        sha256: createHash("sha256").update("fixture media").digest("hex") };
      if (method === "ordinary_web_file_finish") return { released: true };
      throw new Error("unexpected fixture method");
    } } };
  globalThis[slot] = runtime; return { runtime, directory, calls, cleanups, operation };
}
test("local media snapshots are shared only within one operation and verify byte identity before use", async () => {
  const f = fixture();
  try {
    const one = await webLocalFile("./video.mp4"), two = await webLocalFile(one.path);
    assert.equal(one, two); assert.equal(f.calls.length, 1);
    assert.equal((await webReadLocalFile(one.path)).toString(), "fixture media");
    assert.equal(f.cleanups.length, 1); await f.cleanups[0]();
    assert.equal(f.calls.at(-1).method, "ordinary_web_file_finish");
    writeFileSync(join(f.directory, "input"), "changed media");
    assert.throws(() => one.bytes(), /CHANGED/);
  } finally { delete globalThis[slot]; }
});
test("foreign file URLs and old operation handles cannot read local files", async () => {
  const f = fixture();
  try {
    await assert.rejects(webLocalFile("file://unselected.invalid/private/video.mp4"), /PATH/); assert.equal(f.calls.length, 0);
    const one = await webLocalFile("./video.mp4");
    f.runtime.web.current = () => ({ controller: new AbortController() });
    assert.throws(() => one.bytes(), /STALE/);
  } finally { delete globalThis[slot]; }
});
