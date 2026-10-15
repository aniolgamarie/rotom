import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, symlinkSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { assertSessionCompatibility, sessionCompatibility } from "../session-compatibility.ts";

test("public pre-switch and pre-fork events cancel incompatible or busy sessions without SDK writes", async () => {
  const root = mkdtempSync(join(tmpdir(), "session-compatibility-")), sessions = join(root, "sessions"); mkdirSync(sessions, { mode: 0o700 });
  const file = join(sessions, "current.jsonl"), header = { type: "session", version: 3, id: "fixture", cwd: root };
  writeFileSync(file, JSON.stringify(header) + "\n" + "not parsed conversation body\n", { mode: 0o600 });
  assert.deepEqual(assertSessionCompatibility(file, sessions), { version: 3 });
  const handlers = new Map(), notifications = [];
  let blocked = false;
  const extension = sessionCompatibility({ CURRENT_SESSION_VERSION: 3 }, sessions, async () => { if (blocked) throw Error("activity"); });
  extension.factory({ on: (name, handler) => handlers.set(name, handler) });
  const context = { sessionManager: { getSessionFile: () => file }, ui: { notify: message => notifications.push(message) } };
  const resume = targetSessionFile => handlers.get("session_before_switch")({ type: "session_before_switch", reason: "resume", targetSessionFile }, context);
  assert.deepEqual(await resume(file), {});
  writeFileSync(file, JSON.stringify({ ...header, version: 2 }) + "\nold data\n");
  const before = readFileSync(file);
  assert.deepEqual(await resume(file), { cancel: true });
  assert.deepEqual(await handlers.get("session_before_fork")({ type: "session_before_fork" }, context), { cancel: true });
  assert.deepEqual(readFileSync(file), before);
  const outside = join(root, "outside.jsonl"); writeFileSync(outside, JSON.stringify(header) + "\n", { mode: 0o600 });
  assert.deepEqual(await resume(outside), { cancel: true });
  const link = join(sessions, "link.jsonl"); symlinkSync(outside, link);
  assert.deepEqual(await resume(link), { cancel: true });
  assert.deepEqual(await resume(undefined), { cancel: true });
  blocked = true;
  assert.deepEqual(await handlers.get("session_before_switch")({ type: "session_before_switch", reason: "new" }, context), { cancel: true });
  assert.ok(notifications.length >= 6);
});

test("empty or oversized headers do not become new sessions during resume", () => {
  const root = mkdtempSync(join(tmpdir(), "session-invalid-")), file = join(root, "empty.jsonl");
  for (const body of ["", "x".repeat(17000) + "\n", JSON.stringify({ type: "session", version: 99, id: "future", cwd: root }) + "\n"]) {
    writeFileSync(file, body, { mode: 0o600 });
    assert.throws(() => assertSessionCompatibility(file, root), /SESSION_/);
    assert.equal(readFileSync(file, "utf8"), body);
  }
});
