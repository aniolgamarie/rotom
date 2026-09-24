import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createWorkspace } from "../src/workspace/worktree.ts";

test("workspace copy uses no-checkout and never reads or copies a known credential file", () => {
  const directory = fs.mkdtempSync(join(tmpdir(), "workspace-copy-"));
  const source = join(directory, "source"), state = join(directory, "state");
  fs.mkdirSync(source); fs.mkdirSync(state, { mode: 0o700 }); fs.mkdirSync(join(source, ".git"));
  fs.writeFileSync(join(source, "code.txt"), "business source");
  const secret = join(source, "local.toml"); fs.writeFileSync(secret, "synthetic credential sentinel");
  const originalExec = childProcess.execFileSync, originalRead = fs.readFileSync, calls = [];
  const target = join(state, "worktrees/job");
  childProcess.execFileSync = (program, args, options) => {
    calls.push(args);
    assert.equal(program, "/usr/bin/git");
    const at = args.indexOf("-C"), cwd = args[at + 1], command = args.slice(at + 2);
    if (command[0] === "rev-parse") {
      if (command.includes("--show-toplevel")) return Buffer.from(cwd + "\n");
      if (command.includes("--git-common-dir")) return Buffer.from(join(source, ".git") + "\n");
      return Buffer.from("a".repeat(40) + "\n");
    }
    if (["ls-tree", "ls-files"].includes(command[0])) return Buffer.from("code.txt\0local.toml\0");
    if (command[0] === "worktree") {
      assert.ok(command.includes("--no-checkout"));
      fs.mkdirSync(target); fs.writeFileSync(join(target, ".git"), "gitdir: synthetic"); return Buffer.alloc(0);
    }
    throw Error("unexpected Git command");
  };
  fs.readFileSync = (path, ...args) => {
    if (String(path) === secret || String(path) === join(target, "local.toml")) throw Error("credential read forbidden");
    return originalRead(path, ...args);
  };
  syncBuiltinESMExports();
  try {
    const result = createWorkspace(source, state, "job", [], [secret]);
    assert.deepEqual(result.snapshot.files.map(file => file.path), ["code.txt"]);
    assert.equal(originalRead(join(target, "code.txt"), "utf8"), "business source");
    assert.equal(fs.existsSync(join(target, "local.toml")), false);
    assert.equal(calls.some(args => args.includes("diff")), false);
  } finally { childProcess.execFileSync = originalExec; fs.readFileSync = originalRead; syncBuiltinESMExports(); }
});
