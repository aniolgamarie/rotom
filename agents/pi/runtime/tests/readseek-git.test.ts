import assert from "node:assert/strict";
import { test } from "node:test";
import { readseekGitQuery } from "../readseek-git.ts";

const selection = { schema_version: 1, snapshot_root: "/snapshot", snapshot_digest: "a".repeat(64), categories: {
  cached: ["node_modules/tracked.ts", "target/tracked.ts", "src/space name"], others: ["src/new"] } };
test("tracked build/dependency files and unusual filenames retain Git semantics in a snapshot", () => {
  assert.equal(readseekGitQuery(selection, ["-C", "/snapshot", "ls-files", "-z", "--cached"]).toString(),
    "node_modules/tracked.ts\0src/space name\0target/tracked.ts\0");
  assert.equal(readseekGitQuery(selection, ["-C", "/snapshot/src", "ls-files", "-z", "--others", "--exclude-standard"]).toString(), "new\0");
});
test("the Git shim rejects extra operations, unavailable categories and escaping roots", () => {
  for (const argv of [["status"], ["-C", "/outside", "ls-files", "-z", "--cached"],
    ["-C", "/snapshot", "ls-files", "-z", "--cached", "--debug"],
    ["-C", "/snapshot", "ls-files", "-z", "--others", "--ignored", "--exclude-standard"]]) {
    assert.throws(() => readseekGitQuery(selection, argv), /INVALID/);
  }
});
