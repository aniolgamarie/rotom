import { test, assert } from "./recorded-test.ts";
import { fork } from "node:child_process";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { isolatedDirectory } from "./helpers.ts";
const fixture = fileURLToPath(new URL("./fixtures/store-startup.ts", import.meta.url));

test("[P] published state identity is already in WAL mode for an independent opener", { timeout: 15000 }, async t => {
  const root = isolatedDirectory(t), child = fork(fixture, [root, "publish"], { execArgv: ["--experimental-strip-types"], stdio: ["ignore", "ignore", "pipe", "ipc"] });
  t.after(() => child.kill("SIGKILL")); assert.equal((await once(child, "message"))[0].type, "ready");
  const published = once(child, "message"); child.send("open"); assert.equal((await published)[0].type, "published");
  const observer = new DatabaseSync(join(root, "runtime.db"), { readOnly: true });
  try { assert.equal(observer.prepare("PRAGMA journal_mode").get()!.journal_mode, "wal"); assert.equal(observer.prepare("PRAGMA user_version").get()!.user_version, 3); }
  finally { observer.close(); }
  const completed = once(child, "message"), exited = once(child, "exit"); writeFileSync(join(root, "release"), "ready");
  assert.equal((await completed)[0].type, "opened"); assert.equal((await exited)[0], 0);
});

test("[P] simultaneous first openers converge on one store without journal-mode lock errors", { timeout: 20000 }, async t => {
  const root = isolatedDirectory(t), children = Array.from({ length: 10 }, () => fork(fixture, [root, "race"], { execArgv: ["--experimental-strip-types"], stdio: ["ignore", "ignore", "pipe", "ipc"] }));
  t.after(() => { for (const child of children) child.kill("SIGKILL"); });
  assert.ok((await Promise.all(children.map(child => once(child, "message")))).every(([message]) => message.type === "ready"));
  const results = children.map(child => once(child, "message")), exits = children.map(child => once(child, "exit")); children.forEach(child => child.send("open"));
  const rows = (await Promise.all(results)).map(([message]) => message);
  assert.ok(rows.every(row => row.type === "opened" && row.mode === "wal"), JSON.stringify(rows)); assert.equal(new Set(rows.map(row => row.identity)).size, 1);
  assert.ok((await Promise.all(exits)).every(([code]) => code === 0));
});
