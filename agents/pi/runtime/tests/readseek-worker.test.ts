import assert from "node:assert/strict";
import { test } from "node:test";
import { executeReadseek } from "../readseek-worker.ts";
import { recordReadseekAnchor, readseekWorker } from "../readseek-context.ts";

const names = ["edit", "grep", "search", "refs", "rename", "def", "digest", "view", "write"].map(name => "readSeek_" + name);
const contracts = { schema_version: 1, tools: names.map(name => ({ name, parameters: { type: "object", additionalProperties: false } })) };
function request() {
  return { schema_version: 1, operation_id: "call", tool: "readSeek_digest", params: { path: "/snapshot/src/file" },
    snapshot_digest: "a".repeat(64), snapshot_root: "/snapshot", working_directory: "/snapshot", cache_root: "/cache", native_binary: "/tools/readseek", settings: {}, anchors: [] };
}
function loader(execute, changed) {
  return async () => pi => { for (const row of contracts.tools) pi.registerTool({ ...row, ...(changed?.(row) ?? {}), execute }); };
}
test("worker runs exactly the selected original tool with a private cwd and supplied anchors", async () => {
  let count = 0;
  const input = request(); input.anchors = [input.params.path];
  const output = await executeReadseek(input, contracts, loader(async (id, params, signal, update, ctx) => {
    count++;
    assert.equal(ctx.cwd, "/snapshot"); assert.equal(ctx.hasUI, false); assert.equal(update, undefined);
    assert.deepEqual(readseekWorker().anchors, [params.path]);
    recordReadseekAnchor("mark", params.path);
    return { content: [{ type: "text", text: "fixture" }] };
  }));
  assert.equal(count, 1); assert.equal(output.operation_id, "call");
  assert.deepEqual(output.anchor_events, [{ action: "mark", path: input.params.path }]);
  assert.equal(readseekWorker(), null);
});
test("worker rejects changed contracts, paths and incomplete factories before tool execution", async () => {
  let count = 0;
  const execute = async () => { count++; return { content: [] }; };
  const bad = request(); bad.params.path = "/snapshot/../outside";
  await assert.rejects(executeReadseek(bad, contracts, loader(execute)), /PROTOCOL/);
  await assert.rejects(executeReadseek(request(), contracts, loader(execute, row => row.name === "readSeek_edit"
    ? { parameters: { type: "object" } } : {})), /PROTOCOL/);
  await assert.rejects(executeReadseek(request(), contracts, async () => () => {}), /PROTOCOL/);
  assert.equal(count, 0); assert.equal(readseekWorker(), null);
});
test("abort or failure cannot return a successful artifact or retain worker context", async () => {
  const abort = new AbortController();
  await assert.rejects(executeReadseek(request(), contracts, loader(async () => {
    abort.abort(); return { content: [] };
  }), { signal: abort.signal }), /abort/i);
  assert.equal(readseekWorker(), null);
  await assert.rejects(executeReadseek(request(), contracts, loader(async () => { throw new Error("fixture failure"); })), /fixture failure/);
  assert.equal(readseekWorker(), null);
});
