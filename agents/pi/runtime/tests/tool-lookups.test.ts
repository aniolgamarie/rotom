import assert from "node:assert/strict";
import { test } from "node:test";
import { registerHooks } from "node:module";

test("Base ordinary file module loads with legacy and optional service modules forbidden", async () => {
  const forbidden = /\/(?:launch|managed-backend|web-tools|web-runtime|web-listener|mcp-tools|readseek-controller|supervised-stdio|service-bindings|checkpoints|delegate-pi)\.ts(?:\?|$)/;
  const parents = new Set();
  const hooks = registerHooks({ resolve(specifier, context, next) {
    const scoped = specifier.endsWith("ordinary-operations.ts?base-import-test") || parents.has(context.parentURL);
    if (scoped && specifier.startsWith(".") && context.parentURL && forbidden.test(new URL(specifier, context.parentURL).href)) throw Error("OPTIONAL_IMPORT_FORBIDDEN:" + specifier);
    const result = next(specifier, context);
    if (scoped && result.url.startsWith("file:")) parents.add(result.url);
    return result;
  } });
  try {
    const { OrdinaryOperations } = await import("../ordinary-operations.ts?base-import-test");
    const ops = new OrdinaryOperations({}, { supervisor: {}, manifest: { profile_id: "pi-base", plugins: [], options: {} } });
    await assert.rejects(ops.preflight({ toolName: "web_unknown", input: {} }, {}), /ORDINARY_TOOL_NOT_BOUND/);
  } finally { hooks.deregister(); }
});

test("only explicitly registered adapters are queried and repeated registration is idempotent", async () => {
  const { registerToolLookup, isBoundExtensionTool } = await import("../tool-lookups.ts");
  const runtime = {}, foreign = {}; let calls = 0;
  const lookup = (selected, name) => { assert.equal(selected, runtime); calls++; return name === "known"; };
  assert.equal(isBoundExtensionTool(runtime, "known"), false);
  registerToolLookup(runtime, "synthetic", lookup); registerToolLookup(runtime, "synthetic", lookup);
  assert.equal(isBoundExtensionTool(runtime, "known"), true); assert.equal(calls, 1);
  assert.equal(isBoundExtensionTool(foreign, "known"), false); assert.equal(calls, 1);
  assert.equal(isBoundExtensionTool(runtime, "unknown"), false);
  assert.throws(() => registerToolLookup(runtime, "synthetic", () => true), /TOOL_LOOKUP_CONFLICT/);
});

test("adapter rejection and malformed results cannot become a positive service admission", async () => {
  const { registerToolLookup, isBoundExtensionTool } = await import("../tool-lookups.ts");
  const runtime = {}; registerToolLookup(runtime, "synthetic", () => { throw Error("CAPABILITY_NOT_SELECTED"); });
  assert.throws(() => isBoundExtensionTool(runtime, "known"), /CAPABILITY_NOT_SELECTED/);
  const malformed = {}; registerToolLookup(malformed, "synthetic", () => ({ allow: true }));
  assert.throws(() => isBoundExtensionTool(malformed, "known"), /TOOL_LOOKUP_INVALID/);
});
