import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";
import { ReadseekController } from "../readseek-controller.ts";
import { readseekAvailability } from "../readseek-context.ts";

function fixture({ broken = null, text = "fixture" } = {}) {
  const calls = [], sent = [], output = []; let alive = true, accepted = false, pending = "", finishJob;
  const result = { content: [{ type: "text", text }] }, body = Buffer.from(JSON.stringify(result));
  const sha256 = createHash("sha256").update(body).digest("hex");
  const admission = { kind: "readseek", operation_id: "call", lease_id: "lease", write: true, timeout_seconds: 10 };
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-readseek"], options: { readseek: { node_tool_ref: "node" } } },
    permissionAccess: { take(id, name) { assert.equal(id, "tool-call"); assert.equal(name, "readSeek_write"); return admission; } },
    ordinaryOperations: {
      write(ticket, _a, _b, _s, hooks) {
        calls.push("started");
        const job = new Promise(resolve => { finishJob = resolve; });
        hooks.onStarted({ lease_id: "lease", process_identity: { pid: 123 } });
        const ready = { jsonrpc: "2.0", type: "ready", operation_id: broken === "identity" ? "other" : "call", sha256: "a".repeat(64), bytes: 100 };
        output.push(ready); if (broken === "duplicate") output.push(ready);
        return job;
      },
      async abort() { calls.push("abort"); alive = false; finishJob?.({ terminationConfirmed: true, truncated: false, exitCode: 5 }); },
    },
    supervisor: { async call(method, args) {
      calls.push(method);
      if (method === "ordinary_readseek_stage") return { ...admission, kind: "command" };
      if (method === "ordinary_command_output") return { dropped: false, next_cursor: output.length, has_more: false, complete: !alive,
        events: output.slice(args.cursor).map(value => ({ stream: "stdout", data_b64: Buffer.from(JSON.stringify(value) + "\n").toString("base64") })) };
      if (method === "ordinary_readseek_accept") {
        if (broken === "accept") throw new Error("accept rejected");
        accepted = true; return { accepted: true, operation_id: "call" };
      }
      if (method === "ordinary_command_stdin") {
        pending += args.data;
        if (pending.endsWith("\n")) {
          assert.equal(accepted, true); const message = JSON.parse(pending); pending = ""; sent.push(message);
          alive = false; finishJob({ terminationConfirmed: true, truncated: false, exitCode: broken === "exit" ? 5 : 0 });
        }
        return { accepted_bytes: Buffer.byteLength(args.data), stdin_closed: false };
      }
      if (method === "reconcile") return { lease_id: "lease", protected: alive || broken === "termination",
        termination_evidence: !alive && broken !== "termination" ? { verified: true } : null };
      if (method === "ordinary_command_finish") return { finished: true };
      if (method === "ordinary_readseek_finalize") {
        assert.equal(alive, false); assert.equal(accepted, true);
        return { operation_id: "call", termination_confirmed: true, bytes: body.length, sha256 };
      }
      if (method === "ordinary_readseek_result") return { offset: args.offset, bytes: body.length, sha256: broken === "chunk" ? "0".repeat(64) : sha256,
        data_b64: body.subarray(args.offset, args.offset + args.limit).toString("base64") };
      if (method === "ordinary_readseek_discard") { assert.equal(alive, false); return { discarded: true }; }
      throw new Error("unexpected " + method);
    } },
  };
  return { runtime, controller: new ReadseekController(runtime, { installed: true }), calls, sent, result };
}

test("ReadSeek uses the existing supervised transport, accepts before acknowledgment and awaits verified exit", async () => {
  const f = fixture({ text: "large output ".repeat(90000) });
  const result = await f.controller.execute("readSeek_write", "tool-call", {}, undefined, undefined, {});
  assert.deepEqual(result, f.result);
  assert.equal(f.sent.length, 1); assert.equal(f.sent[0].type, "accepted");
  assert.ok(f.calls.indexOf("ordinary_readseek_accept") < f.calls.indexOf("ordinary_command_stdin"));
  assert.ok(f.calls.indexOf("ordinary_readseek_finalize") < f.calls.indexOf("ordinary_readseek_result"));
  assert.ok(f.calls.filter(name => name === "ordinary_readseek_result").length > 1);
  assert.ok(f.calls.includes("ordinary_readseek_discard"));
});

test("bad identities, duplicate ready, rejected commits, failed exits and changed chunks never return success", async () => {
  for (const broken of ["identity", "duplicate", "accept", "exit", "chunk"]) {
    const f = fixture({ broken });
    await assert.rejects(f.controller.execute("readSeek_write", "tool-call", {}, undefined, undefined, {}));
    assert.ok(f.calls.includes("abort"));
    if (["identity", "duplicate", "accept", "exit"].includes(broken)) assert.ok(!f.calls.includes("ordinary_readseek_finalize"));
  }
});

test("pre-aborted calls release reservations without starting a process; readonly preflight is refused", async () => {
  const f = fixture(); const abort = new AbortController(); abort.abort();
  await assert.rejects(f.controller.execute("readSeek_write", "tool-call", {}, abort.signal, undefined, {}), /abort/i);
  assert.ok(!f.calls.includes("started")); assert.ok(f.calls.includes("ordinary_readseek_discard"));
  await assert.rejects(f.controller.prepare({ toolName: "readSeek_write" }, {}, "scout"), /ROLE_CEILING/);
});

test("bootstrap and active managed work expose unavailable metadata without breaking session hooks", async () => {
  const f = fixture(), slot = Symbol.for("agentcfg.pi.runtime.v1");
  f.runtime.readseek = f.controller; globalThis[slot] = f.runtime;
  try {
    f.runtime.manifest.bootstrap = true;
    assert.deepEqual(readseekAvailability(), { available: false, reason: "UNBOUND_MODEL" });
    await assert.rejects(f.controller.prepare({ toolName: "readSeek_write" }, {}, "main"), /UNBOUND_MODEL/);
    f.runtime.manifest.bootstrap = false; f.runtime.managedRequestScope = { getStore: () => ({ task: "fixture" }) };
    assert.deepEqual(readseekAvailability(), { available: false, reason: "UNMETERED_PARENT_HELPER" });
    assert.deepEqual(f.calls, []);
  } finally { delete globalThis[slot]; }
});
