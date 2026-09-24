import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";
import { createGuardedTools } from "../guarded-tools.ts";
import { descriptor } from "./fixtures.ts";

function setup() {
  const value = { ...descriptor(), allowed_tools: ["tk_read", "tk_edit", "tk_write"] }, calls = [];
  let content = "original value\n", changed = false, sequence = 0;
  const supervisor = { async call(method, args) {
    calls.push({ method, args });
    const action = args.action, data = Buffer.from(content);
    if (action.operation === "read") return { data_b64: data.subarray(action.offset, action.offset + action.limit).toString("base64"),
      offset: action.offset, total_bytes: data.length, content_digest: createHash("sha256").update(content).digest("hex") };
    if (changed) throw Error("FILE_CHANGED");
    if (action.expected_digest !== null) assert.equal(action.expected_digest, createHash("sha256").update(content).digest("hex"));
    content = Buffer.from(action.data_b64, "base64").toString();
    return { changed: true, candidate_digest: createHash("sha256").update(content).digest("hex"), mutation_sequence: ++sequence };
  } };
  const tools = createGuardedTools({ descriptor: value, context: { lease_id: "lease" }, supervisor });
  return { tools: Object.fromEntries(tools.map(tool => [tool.name, tool])), calls, value, content: () => content, drift() { changed = true; } };
}

test("edit reads through supervisor and writes only with the observed content digest", async () => {
  const f = setup();
  await f.tools.tk_edit.execute("call", { path: "src/a", old_text: "original", new_text: "new" });
  assert.equal(f.content(), "new value\n");
  assert.deepEqual(f.calls.map(call => call.args.action.operation), ["read", "write"]);
  assert.ok(f.calls.every(call => call.method === "file_action" && call.args.lease_id === "lease" && call.args.grant_generation === 1));
  f.drift();
  await assert.rejects(f.tools.tk_edit.execute("another", { path: "src/a", old_text: "new", new_text: "replace" }), /FILE_CHANGED/);
  assert.equal(f.content(), "new value\n");
});

test("write operation identity is stable for a tool call and no hidden shell tools are exposed", async () => {
  const f = setup(), args = { path: "src/a", content: "replacement" };
  await f.tools.tk_write.execute("same-call", args);
  await f.tools.tk_write.execute("same-call", args);
  assert.equal(f.calls[0].args.operation_id, f.calls[1].args.operation_id);
  assert.deepEqual(Object.keys(f.tools).sort(), ["tk_edit", "tk_read", "tk_write"]);
  assert.throws(() => createGuardedTools({ descriptor: { ...f.value, allowed_tools: ["bash"] }, context: {}, supervisor: {} }), /WORKER_TOOLS_MISMATCH/);
});
