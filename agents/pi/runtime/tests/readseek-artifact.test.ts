import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { readseekArtifact, writeReadseekArtifact } from "../readseek-artifact.ts";

test("artifact binds the exact computed tree and uses an exclusive private result file", () => {
  const root = mkdtempSync(join(tmpdir(), "readseek-artifact-"));
  const snapshot = join(root, "snapshot"); mkdirSync(snapshot); writeFileSync(join(snapshot, "source"), "fixture");
  const output = readseekArtifact({ schema_version: 1 }, snapshot);
  assert.deepEqual(output.computed_entries.map(row => [row.path, row.size]), [["source", 7]]);
  const target = join(root, "result.json"), receipt = writeReadseekArtifact(output, target);
  assert.equal(receipt.bytes, readFileSync(target).length); assert.equal(receipt.sha256.length, 64);
  assert.throws(() => writeReadseekArtifact(output, target), /EEXIST/);
  // symlink 拒绝由 Python 真实临时文件测试覆盖；Node 权限模式禁止创建链接。
  mkdirSync(join(snapshot, ".git"));
  assert.throws(() => readseekArtifact({}, snapshot), /UNEXPECTED_FILE/);
});
