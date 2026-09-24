import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, symlinkSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { assertSessionCompatibility, installSessionCompatibility } from "../session-compatibility.ts";

test("session restore reads a current header but refuses migration, links and external history before SDK writes", () => {
  const root = mkdtempSync(join(tmpdir(), "session-compatibility-")), sessions = join(root, "sessions"); mkdirSync(sessions, { mode: 0o700 });
  const file = join(sessions, "current.jsonl"), header = { type: "session", version: 3, id: "fixture", cwd: root };
  writeFileSync(file, JSON.stringify(header) + "\n" + "not parsed conversation body\n", { mode: 0o600 });
  assert.deepEqual(assertSessionCompatibility(file, sessions), { version: 3 });
  let calls = 0;
  class SessionManager {
    static open(path) { calls++; return path; }
    static forkFrom(path) { calls++; return path; }
    _setSessionFile() { calls++; }
  }
  installSessionCompatibility({ SessionManager, CURRENT_SESSION_VERSION: 3 }, sessions);
  assert.equal(SessionManager.open(file), file);
  writeFileSync(file, JSON.stringify({ ...header, version: 2 }) + "\nold data\n");
  const before = readFileSync(file);
  assert.throws(() => SessionManager.open(file), /SESSION_MIGRATION_REQUIRED/);
  assert.throws(() => SessionManager.forkFrom(file), /SESSION_MIGRATION_REQUIRED/);
  assert.throws(() => new SessionManager()._setSessionFile(file), /SESSION_MIGRATION_REQUIRED/);
  assert.equal(calls, 1); assert.deepEqual(readFileSync(file), before);
  const outside = join(root, "outside.jsonl"); writeFileSync(outside, JSON.stringify(header) + "\n", { mode: 0o600 });
  assert.throws(() => SessionManager.open(outside), /SESSION_SCOPE_REQUIRED/);
  const link = join(sessions, "link.jsonl"); symlinkSync(outside, link);
  assert.throws(() => SessionManager.open(link));
});

test("empty or oversized headers do not become new sessions during resume", () => {
  const root = mkdtempSync(join(tmpdir(), "session-invalid-")), file = join(root, "empty.jsonl");
  for (const body of ["", "x".repeat(17000) + "\n", JSON.stringify({ type: "session", version: 99, id: "future", cwd: root }) + "\n"]) {
    writeFileSync(file, body, { mode: 0o600 });
    assert.throws(() => assertSessionCompatibility(file, root), /SESSION_/);
    assert.equal(readFileSync(file, "utf8"), body);
  }
});
