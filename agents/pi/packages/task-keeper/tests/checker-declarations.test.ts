// 仅 mock 自有 runAuxiliary 端口；不执行检查、Shell、SDK 或 Writer。
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { registerHooks } from "node:module";
import { DEFAULT_CONFIG, parseConfig } from "../src/config.ts";
import { fromAgentcfg } from "../src/agentcfg-config.ts";

const portKey = Symbol.for("task-keeper.test.checker-port"), runtimeKey = Symbol.for("agentcfg.pi.runtime.v1");
const hooks = registerHooks({ resolve(specifier, context, next) {
  if (specifier === "@agentcfg/pi-runtime/auxiliary-executor" && /\/verification\/supervisor\.(ts|mjs)$/.test(context.parentURL ?? "")) {
    return { url: "data:text/javascript," + encodeURIComponent(`export async function runAuxiliary(options) { return globalThis[Symbol.for("task-keeper.test.checker-port")](options); }`), shortCircuit: true };
  }
  return next(specifier, context);
} });
const { supervisedCommand } = await import("../src/verification/supervisor.ts");
const { verificationInputs } = await import("../src/verification/inputs.ts");
hooks.deregister();

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "checker-declarations-"));
  mkdirSync(join(root, "pi-home")); mkdirSync(join(root, "supervisor/scripts"), { recursive: true });
  writeFileSync(join(root, "supervisor/scripts/pi-project-check"), "inert original helper");
  writeFileSync(join(root, "pi-home/models.json"), JSON.stringify({ providers: { "agentcfg-fixture": { models: [{ id: "model" }] } } }));
  const check = { executable: process.execPath, args: ["-e", "literal fixed acceptance logic"], timeout_seconds: 5, foreground: true,
    project_root: "project", kind: "tests", parser: "json", minimum_tests: 1, inputs: [],
    read_roots: ["checker", "dependencies"], trusted_inputs: [{ root_ref: "checker", relative_path: "check.js" }] };
  const role = { managed: true, model: { provider: "agentcfg-fixture", model: "model" }, tools: ["read"], read_roots: ["project"], write_roots: [] };
  const runtime = { owner: { role: "manager", instance_id: "fixture" }, instanceRoot: root, runtimeRoot: root,
    installed: { schema_version: 2, profile_id: "pi-full", runtime_identity: "fixed-runtime" },
    manifest: { profile_id: "pi-full", role_bindings: Object.fromEntries(["reader", "writer", "reviewer"].map(name => ["task-keeper-" + name, structuredClone(role)])),
      options: { task_keeper: { enabled: true, check_ids: ["test"], second_view_enabled: false,
        limits: { model_requests: 3, model_turns: 3, wall_seconds: 30 } },
        network: { routes: { direct: { mode: "direct", provider_ids: ["fixture"] } } }, checks: { test: check } } } };
  const config = parseConfig(fromAgentcfg(DEFAULT_CONFIG, runtime));
  return { root, runtime, check, config, binding: config.verificationBindings.test };
}

async function withRuntime(f: ReturnType<typeof fixture>, run: (counters: { calls: number; dispatches: number }) => Promise<void>) {
  const previous = globalThis[runtimeKey], oldPort = globalThis[portKey], counters = { calls: 0, dispatches: 0 };
  globalThis[runtimeKey] = f.runtime;
  globalThis[portKey] = async (options: any) => {
    counters.calls++; options.onDispatch?.();
    return { stdout: "", stderr: "", truncated: false, timedOut: false, cancelled: false, started: true,
      exitCode: 0, terminationConfirmed: true, lease_id: "mock", process_identity: null };
  };
  try { await run(counters); } finally { globalThis[runtimeKey] = previous; globalThis[portKey] = oldPort; }
}
const options = { contractDigest: "a".repeat(64), maxBytes: 1000, killGraceMs: 100, checkId: "test", jobId: "job" };

test("actual modern fromAgentcfg preserves optional declarations and schema7 rejects forged fields", () => {
  const f = fixture();
  assert.deepEqual(f.binding.read_roots, f.check.read_roots); assert.deepEqual(f.binding.trusted_inputs, f.check.trusted_inputs);
  f.binding.trusted_inputs![0].relative_path = "changed.js"; assert.equal(f.check.trusted_inputs[0].relative_path, "check.js");
  const mutations = [
    (b: any) => b.read_roots = "checker", (b: any) => b.read_roots = ["checker", "checker"],
    (b: any) => b.trusted_inputs = [{ root_ref: "checker", relative_path: "check.js", selfApproved: true }],
    (b: any) => b.trusted_inputs = [{ root_ref: "checker" }], (b: any) => b.trusted_inputs = [{ root_ref: 3, relative_path: "check.js" }],
    (b: any) => b.trusted_inputs = [b.trusted_inputs[0], b.trusted_inputs[0]], (b: any) => b.trusted_inputs = null,
    (b: any) => b.approved = true,
  ];
  for (const mutate of mutations) { const config = structuredClone(f.config); mutate(config.verificationBindings.test); assert.throws(() => parseConfig(config)); }
});

test("absent old declarations stay absent and retain the original verification digest", async () => {
  const f = fixture(); delete (f.check as any).read_roots; delete (f.check as any).trusted_inputs;
  const config = parseConfig(fromAgentcfg(DEFAULT_CONFIG, f.runtime)), binding = config.verificationBindings.test;
  assert.equal(Object.hasOwn(binding, "read_roots"), false); assert.equal(Object.hasOwn(binding, "trusted_inputs"), false);
  await withRuntime(f, async () => {
    const inputs = verificationInputs({ test: binding }, f.root);
    assert.equal(inputs.files.some(row => row.path === "@trusted-input-declaration"), false);
  });
});

test("dispatch compares ordered declarations with current manifest before the fake auxiliary port", async () => {
  const f = fixture();
  await withRuntime(f, async counters => {
    const execute = (binding: any) => supervisedCommand(binding, f.root, {}, { ...options, onDispatch: () => counters.dispatches++ });
    await execute(f.binding); assert.deepEqual(counters, { calls: 1, dispatches: 1 });
    const mutations = [
      (b: any) => b.read_roots.reverse(), (b: any) => delete b.read_roots,
      (b: any) => b.trusted_inputs[0].relative_path = "other.js", (b: any) => b.trusted_inputs[0].root_ref = "dependencies",
      (b: any) => b.trusted_inputs[0].selfApproved = true, (b: any) => b.trusted_inputs = [],
    ];
    for (const mutate of mutations) {
      const binding = structuredClone(f.binding); mutate(binding); counters.calls = 0; counters.dispatches = 0;
      await assert.rejects(execute(binding), /CHECK_BINDING_CHANGED/); assert.deepEqual(counters, { calls: 0, dispatches: 0 });
    }
    f.check.trusted_inputs[0].relative_path = "fresh-manifest.js";
    await assert.rejects(execute(f.binding), /CHECK_BINDING_CHANGED/); assert.deepEqual(counters, { calls: 0, dispatches: 0 });
  });
});

test("verification digest binds only declaration metadata and original candidate acceptance inputs", async () => {
  const f = fixture(), subject = join(f.root, "subject.js"); writeFileSync(subject, "before");
  await withRuntime(f, async () => {
    const before = verificationInputs({ test: f.binding }, f.root); writeFileSync(subject, "changed subject");
    assert.equal(verificationInputs({ test: f.binding }, f.root).digest, before.digest);
    assert.equal(before.files.some(row => row.path === "@trusted-input-declaration"), true);
    f.binding.trusted_inputs![0].relative_path = "not-a-readable-authority-file.js";
    assert.notEqual(verificationInputs({ test: f.binding }, f.root).digest, before.digest);
    const explicit = { ...f.binding, inputs: ["subject.js"] }, pinned = verificationInputs({ test: explicit }, f.root);
    writeFileSync(subject, "changed acceptance input"); assert.notEqual(verificationInputs({ test: explicit }, f.root).digest, pinned.digest);
  });
});


test("modern required IDs propagate exactly and changed declaration dispatches zero auxiliary calls", async () => {
  const f=fixture();f.check.required_test_ids=["critical"] as any;
  const binding=parseConfig(fromAgentcfg(DEFAULT_CONFIG,f.runtime)).verificationBindings.test;
  assert.deepEqual(binding.requiredTestIds,["critical"]);binding.requiredTestIds![0]="changed";assert.deepEqual(f.check.required_test_ids,["critical"]);
  await withRuntime(f,async counters=>{await assert.rejects(supervisedCommand(binding,f.root,{},options),/CHECK_BINDING_CHANGED/);assert.deepEqual(counters,{calls:0,dispatches:0});});
});
