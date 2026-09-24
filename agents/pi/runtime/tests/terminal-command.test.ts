import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { test } from "node:test";
import { runTerminalCommand } from "../terminal-command.ts";

function fixture(lost = false) {
  const input = new EventEmitter(), output = new EventEmitter(), calls = [], raw = [], frames = [];
  Object.assign(input, { isTTY: true, isRaw: false, readableFlowing: false, setRawMode(value) { raw.push(value); this.isRaw = value; }, resume() {}, pause() {} });
  Object.assign(output, { isTTY: true, rows: 24, columns: 80, write(value) { frames.push(Buffer.from(value)); } });
  let ended = false, aborted = false;
  const runtime = { supervisor: { async call(method, args) {
    calls.push([method, args]);
    if (method === "ordinary_command_output") return { dropped: lost, next_cursor: 1, has_more: false, complete: ended,
      events: args.cursor === 0 ? [{ stream: "stdout", data_b64: Buffer.from("fixture terminal").toString("base64") }] : [] };
    if (method === "ordinary_command_stdin") return { accepted_bytes: Buffer.byteLength(args.data), stdin_closed: false };
    if (method === "ordinary_command_resize") return { resized: true };
    throw Error("unexpected method");
  } }, ordinaryOperations: {
    async abort() { aborted = true; },
    async write(ticket, _content, _digest, _signal, callbacks) {
      await callbacks.onStarted({ lease_id: ticket.lease_id, process_identity: { pid: 123 } });
      input.emit("data", Buffer.from("输入\n"));
      output.rows = 40; output.columns = 100; output.emit("resize");
      await new Promise(resolve => setTimeout(resolve, 5));
      ended = true;
      return { exitCode: 0, terminationConfirmed: true, truncated: true };
    },
  } };
  return { input, output, calls, raw, frames, runtime, aborted: () => aborted,
    ticket: { operation_id: "editor", lease_id: "lease", terminal_size: [24, 80] } };
}

test("terminal editor relays owned input/output/resize and restores parent input after verified exit", async () => {
  const f = fixture();
  const code = await runTerminalCommand(f.runtime, f.ticket, { input: f.input, output: f.output, pause: () => new Promise(resolve => setTimeout(resolve, 1)) });
  assert.equal(code, 0); assert.equal(f.aborted(), false);
  assert.equal(Buffer.concat(f.frames).toString(), "fixture terminal");
  assert.equal(f.calls.find(([name]) => name === "ordinary_command_stdin")[1].data, "输入\n");
  assert.equal(f.calls.find(([name]) => name === "ordinary_command_resize")[1].rows, 40);
  assert.deepEqual(f.raw, [true, false]);
  assert.equal(f.input.listenerCount("data"), 0); assert.equal(f.output.listenerCount("resize"), 0);
});

test("lost terminal output cancels the owned command and never becomes success", async () => {
  const f = fixture(true);
  await assert.rejects(runTerminalCommand(f.runtime, f.ticket, { input: f.input, output: f.output }), /UNVERIFIED/);
  assert.equal(f.aborted(), true); assert.deepEqual(f.raw, [true, false]);
  assert.equal(f.input.listenerCount("data"), 0);
});
