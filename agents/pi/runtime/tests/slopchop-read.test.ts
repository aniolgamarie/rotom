import assert from "node:assert/strict";
import { test } from "node:test";
import { parseNameStatus, parseUntrackedPaths, parseNumStat, parseRawDiff } from "../../packages/slopchop-vendor/src/git.ts";
import { reviewGit, readReviewFile, statReviewFile } from "../review-files.ts";

test("slopchop parses NUL records without losing Unicode, newlines or trailing spaces", () => {
  const name = "src/中文\nname ";
  assert.deepEqual(parseNameStatus("M\0" + name + "\0"), [{ status: "modified", oldPath: name, newPath: name }]);
  assert.equal(parseUntrackedPaths(name + "\0")[0].newPath, name);
  assert.deepEqual(parseNumStat("3\t2\t\0old\0" + name + "\0").get(name), { additions: 3, deletions: 2 });
  assert.equal(parseRawDiff(":100644 100644 abc1234 def1234 M\0" + name + "\0")[0].newPath, name);
  assert.throws(() => parseNameStatus("M\0truncated"), /TRUNCATED/);
  assert.throws(() => parseRawDiff("unexpected\0name\0"), /INVALID/);
});

test("concurrent review queries serialize workspace ownership and file reads retain exact admissions", async () => {
  const key = Symbol.for("agentcfg.pi.runtime.v1"), previous = globalThis[key], calls = [];
  let active = 0, maximum = 0;
  const runtime = { cwd: "/fixture/project", owner: { role: "manager" }, manifest: { plugins: ["pi-slopchop"], options: {} },
    supervisor: { async call(method, args) {
      calls.push([method, args]);
      if (method === "ordinary_git_review_prepare") { active++; maximum = Math.max(maximum, active); return { operation_id: args.operation_id }; }
      if (method === "ordinary_command_finish") { active--; return { finished: true }; }
      if (method === "ordinary_prepare") { assert.equal(args.tool_name, "read"); return { operation_id: args.operation_id, path: args.input.path }; }
      if (method === "ordinary_stat") return { size: 7, identity: "fixture" };
      if (method === "ordinary_finish") return { finished: true };
      throw Error("unexpected method");
    } }, ordinaryOperations: {
      async write() { return { exitCode: 0, stdout: "fixture", stderr: "", truncated: false, terminationConfirmed: true }; },
      async read(ticket, path) { assert.equal(path, ticket.path); return { bytes: Buffer.from("fixture") }; },
    } };
  globalThis[key] = runtime;
  try {
    await Promise.all([reviewGit(runtime.cwd, ["ls-files", "--cached"]), reviewGit(runtime.cwd, ["ls-files", "--deleted"])]);
    assert.equal(maximum, 1); assert.equal(active, 0);
    assert.equal((await statReviewFile("src/a.txt")).size, 7);
    assert.equal((await readReviewFile("src/a.txt")).toString(), "fixture");
    assert.equal(calls.filter(([method]) => method === "ordinary_finish").length, 2);
    runtime.ordinaryOperations.write = async () => ({ exitCode: 0, stdout: "", stderr: "", truncated: true, terminationConfirmed: true });
    await assert.rejects(reviewGit(runtime.cwd, ["ls-files", "--cached"]), /GIT_REVIEW_FAILED/);
    assert.equal(active, 0);
  } finally { globalThis[key] = previous; }
});
