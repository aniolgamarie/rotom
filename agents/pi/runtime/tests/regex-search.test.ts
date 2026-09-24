import assert from "node:assert/strict";
import { test } from "node:test";
import { EventEmitter } from "node:events";
import { searchText } from "../regex-search.ts";

test("regex helper has a bounded lifetime and waits for its owned worker termination", async () => {
  let stopped = 0;
  const worker = new EventEmitter(); worker.terminate = async () => { stopped++; };
  await assert.rejects(searchText({ pattern: "(a+)+$", text: "a".repeat(200), literal: false, ignoreCase: false, limit: 10, context: 0 },
    { createWorker: () => worker, timeout: 5 }), /SEARCH_TIMEOUT/);
  assert.equal(stopped, 1);
  const worker2 = new EventEmitter(); worker2.terminate = worker.terminate;
  const result = searchText({ pattern: "match", text: "match", literal: true, ignoreCase: false, limit: 10, context: 0 },
    { createWorker: () => worker2, timeout: 1000 });
  worker2.emit("message", { ok: true, matches: [{ line: 1, text: "match" }] });
  assert.equal((await result)[0].line, 1); assert.equal(stopped, 2);
});
