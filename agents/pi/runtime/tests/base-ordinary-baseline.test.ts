// Base独立加载普通工具；不导入Task Keeper/subagents或模拟其管理器。
import assert from "node:assert/strict";
import { test } from "node:test";
import { resolve } from "node:path";
import { OrdinaryOperations } from "../ordinary-operations.ts";
import { captureOperationInput } from "../private-operation-input.ts";

function fixture({ failAt, denied = false } = {}) {
  const cwd = resolve(process.env.HOME, "project"), calls = [], sdkError = Error("own SDK edit mismatch"), ioError = Error("own supervisor IO failure");
  const supervisor = { async call(name) {
    calls.push(name);
    if (name === failAt) throw ioError;
    if (name === "ordinary_read") return { data_b64: Buffer.from("needle\n").toString("base64"), total_bytes: 7, content_digest: "a".repeat(64) };
    if (name === "ordinary_list") return { entries: [{ path: "source.txt", directory: false }], truncated: false };
    if (name === "inspect") return { lease_id: "lease", state: "allocating" };
    if (["ordinary_finish", "abort_allocation"].includes(name)) return {};
    throw Error("unexpected process/service operation");
  } };
  const sdk = {};
  for (const name of ["Read", "Write", "Edit"]) sdk["create" + name + "ToolDefinition"] = (_cwd, { operations } = {}) => ({
    name: name.toLowerCase(), parameters: {}, async execute(_id, input) {
      calls.push("sdk-" + name.toLowerCase());
      const body = await operations.readFile(resolve(cwd, input.path));
      if (name === "Edit") throw sdkError;
      return { content: [{ type: "text", text: body.toString() }] };
    },
  });
  for (const name of ["Ls", "Find", "Grep"]) sdk["create" + name + "ToolDefinition"] = () => ({ name: name.toLowerCase(), parameters: {} });
  sdk.createBashToolDefinition = () => { throw Error("unselected command factory"); };
  const runtime = { supervisor, manifest: { profile_id: "pi-base", plugins: [], options: {} },
    get readseek() { throw Error("unselected Readseek service"); }, get manager() { throw Error("unselected Full manager"); } };
  const admission = { async admit({ toolName, input }) {
    calls.push("admit"); if (denied) throw Error("OPERATION_DENIED");
    return { input: captureOperationInput(input).value, ticket: { kind: "file", state: "consumed", operation_id: "operation", lease_id: "lease",
      path: resolve(cwd, toolName === "grep" ? "." : input.path ?? "."), tool_name: toolName, write: ["write", "edit", "rename"].includes(toolName) } };
  } };
  const tools = new OrdinaryOperations(sdk, runtime, { fileAdmission: admission }).tools(cwd, "main", { filesOnly: true });
  const ctx = { cwd, sessionManager: { getSessionId: () => "own-session" } };
  return { calls, sdkError, ioError, tools, execute: (name, input) => tools.find(tool => tool.name === name).execute("call", input, new AbortController().signal, undefined, ctx) };
}

test("Base constructs exactly ordinary files without Full services or command factories", () => {
  const f = fixture();
  assert.deepEqual(f.tools.map(tool => tool.name), ["read", "write", "edit", "rename", "ls", "find", "grep"]);
  assert.deepEqual(f.calls, []);
});

for (const name of ["read", "ls", "find", "grep"]) test("Base " + name + " returns admitted result without model or Full service", async () => {
  const f = fixture(), result = await f.execute(name, name === "grep" ? { pattern: "needle", literal: true } : { path: "source.txt" });
  assert.match(result.content[0].text, name === "read" ? /needle/ : /source\.txt/);
  assert.equal(result.isError, undefined);
  assert.equal(f.calls[0], "admit"); assert.equal(f.calls.at(-1), "ordinary_finish");
});

for (const name of ["read", "ls", "find", "grep"]) test("Base " + name + " IO failure is propagated with no successful result", async () => {
  const f = fixture({ failAt: name === "read" ? "ordinary_read" : "ordinary_list" });
  await assert.rejects(f.execute(name, { path: "source.txt", pattern: "needle", literal: true }), error => error === f.ioError);
  assert.equal(f.calls.at(-1), "ordinary_finish");
});

test("Base SDK edit mismatch preserves the error and releases only unused allocation", async () => {
  const f = fixture();
  await assert.rejects(f.execute("edit", { path: "source.txt", oldText: "absent", newText: "replacement" }), error => error === f.sdkError);
  assert.equal(f.calls.includes("abort_allocation"), true);
  assert.equal(f.calls.includes("start"), false); assert.equal(f.calls.includes("ordinary_stage_write"), false);
});

for (const name of ["read", "write", "edit", "rename", "ls", "find", "grep"]) test("Base denied " + name + " never reaches SDK or supervisor IO", async () => {
  const f = fixture({ denied: true });
  await assert.rejects(f.execute(name, { path: "source.txt", pattern: "needle", literal: true }), /OPERATION_DENIED/);
  assert.deepEqual(f.calls, ["admit"]);
});
