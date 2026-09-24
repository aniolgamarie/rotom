import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { TaskService } from "../src/orchestration/service.ts";
import { Store } from "../src/store/database.ts";
import { DEFAULT_CONFIG, parseConfig } from "../src/config.ts";
import { SubagentsAdapter } from "../src/adapters/subagents.ts";
import { AgentManager } from "../../subagents-vendor/src/agent-manager.ts";
import { digest } from "../src/contracts/primitives.ts";

const hash = value => createHash("sha256").update(value).digest("hex");
const save = (path, value) => { fs.mkdirSync(join(path, ".."), { recursive: true, mode: 0o700 }); fs.writeFileSync(path, value, { mode: 0o600 }); };
const tree = cwd => {
  const files = [{ path: "code.txt", kind: "file", hash: hash(fs.readFileSync(join(cwd, "code.txt"))), executable: 0 }];
  return { root: cwd, commit: "a".repeat(40), files, id: "tree-" + digest({ commit: "a".repeat(40), files }) };
};

test("inspect and fix retain real-check and independent-review requirements through the new supervisor queue", async () => {
  for (const { workflow, fault } of [{ workflow: "inspect" }, { workflow: "fix" }, { workflow: "fix", fault: "zero-tests" }, { workflow: "inspect", fault: "stale-review" }]) {
    const root = fs.mkdtempSync(join(tmpdir(), "workflow-")), source = join(root, "source"), state = join(root, "instance/pi-home/task-keeper");
    fs.mkdirSync(join(source, ".git"), { recursive: true }); fs.writeFileSync(join(source, "code.txt"), "original\n");
    const store = new Store(state), manager = new AgentManager(undefined, 2), calls = [], leases = new Map();
    const runtimeRoot = join(root, "runtime"); save(join(runtimeRoot, "supervisor/scripts/pi-project-check"), "fixture verifier, never executed");
    const config = structuredClone(DEFAULT_CONFIG);
    Object.assign(config, { enabled: true, features: { ...config.features, managedWorkflows: true }, storage: { path: store.path } });
    config.limits.activeChildrenPerHost = 2; config.limits.parallelReaders = 1;
    config.network = { direct: { type: "direct" } };
    config.quotaGroups = { fixture: { classifier: "http", rules: [], baseIntervalMs: 1000, tailIntervalsMs: [1000] } };
    config.routes = { fixture: { provider: "fake", model: "selected", accountBinding: "provider:fake", quotaGroup: "fixture", transportDomain: "direct", network: "direct", protected: true } };
    config.allowedRoutes = ["fixture"]; config.projectRouteApprovals = { "*": ["fixture"] };
    for (const role of ["scout", "worker", "reviewer"]) {
      config.roles[role] = { route: "fixture", profileRef: role };
      config.executionProfiles[role] = { thinking: "off", tools: role === "worker" ? ["read", "grep", "find", "ls", "write", "edit"] : ["read", "grep", "find", "ls"],
        requiredCapabilities: ["events", "termination", "workspace"], timeoutMs: 10000, maxModelTurns: 5, toolTimeoutMs: 1000 };
    }
    const nativeChecks = {};
    for (const id of ["build", "focused-tests"]) {
      config.verificationBindings[id] = { executable: "/fixture/check", args: [id], environment: {}, timeoutMs: 10000,
        kind: id === "build" ? "build" : "tests", parser: id === "build" ? "exit-code" : "pytest", minimumTests: 1, inputs: [] };
      nativeChecks[id] = { executable: "/fixture/check", args: [id], timeout_seconds: 10, kind: config.verificationBindings[id].kind,
        parser: config.verificationBindings[id].parser, minimum_tests: 1, inputs: [] };
    }
    const model = { provider: "fake", id: "selected", api: "openai-completions", baseUrl: "https://fixture.invalid/v1", contextWindow: 10000, maxTokens: 1000,
      reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
    const context = { cwd: source, modelRegistry: { find: () => model, getAvailable: () => [model] },
      sessionManager: { getBranch: () => [], getSessionId: () => "session", getSessionFile: () => undefined, getHeader: () => ({}) } };
    const runtimeKey = Symbol.for("agentcfg.pi.runtime.v1"), managerKey = Symbol.for("agentcfg.pi.managed.v1");
    const oldRuntime = globalThis[runtimeKey], oldManager = globalThis[managerKey], originalExec = childProcess.execFileSync;
    const originalDelegate = SubagentsAdapter.prototype.execute, originalPreflight = SubagentsAdapter.prototype.preflightReview;
    childProcess.execFileSync = (_program, args) => {
      const cwd = args[args.indexOf("-C") + 1];
      if (args.includes("--git-common-dir")) return Buffer.from(join(source, ".git") + "\n");
      if (args.includes("--show-toplevel")) return Buffer.from(cwd + "\n");
      if (args.includes("--verify")) return Buffer.from("a".repeat(40) + "\n");
      if (args.includes("ls-tree") || args.includes("ls-files")) return Buffer.from("code.txt\0");
      throw Error("unapproved fixture process");
    };
    syncBuiltinESMExports();
    const supervisor = { options: { endpoint: join(root, "control-state/activity/control/control.json") }, async call(method, args) {
      if (method === "workspace_identity") return { workspace_key: hash(args.path), worktree_path: args.path };
      if (method === "workspace_snapshot") return { snapshot_digest: hash(tree(args.path).id) };
      if (method === "allocate") { const id = "lease-" + leases.size; leases.set(id, args); return { lease_id: id }; }
      if (method === "inspect" || method === "reconcile") return { lease_id: args.lease_id, state: "reclaimed", protected: false, termination_evidence: { verified: true }, process_identity: { pid: 100, boot_id: "fixture", start_time: "1", namespace: "fixture" } };
      if (method === "start") {
        const payload = args.payload; calls.push([args.program, payload.operation ?? payload.check_id]);
        if (args.program === "workspace") {
          let cwd = payload.cwd;
          if (payload.operation === "create") { cwd = join(state, "worktrees", payload.jobId); fs.mkdirSync(join(cwd, ".git"), { recursive: true }); fs.copyFileSync(join(source, "code.txt"), join(cwd, "code.txt")); }
          save(join(root, "control-state/activity/workspace-results", args.lease_id + ".json"), JSON.stringify({ path: cwd, cwd, snapshot: tree(cwd), baseline: { tree: "a".repeat(40) }, patch: "fixture patch" }));
        }
        const stdout = args.program === "check" && payload.check_id === "focused-tests" ? (fault === "zero-tests" ? "no tests ran in 0.10s\n" : "2 passed in 0.10s\n") : "fixture completed\n";
        const directory = join(root, "control-state/activity/outputs", args.lease_id);
        save(join(directory, "stdout"), stdout); save(join(directory, "stderr"), "");
        save(join(directory, "capture.json"), JSON.stringify({ complete: true, truncated: false, streams: { stdout: { sha256: hash(stdout) }, stderr: { sha256: hash("") } } }));
        save(join(root, "control-state/activity/exits", args.lease_id + ".json"), JSON.stringify({ lease_id: args.lease_id, exit_code: 0, process_identity: { pid: 100, boot_id: "fixture", start_time: "1", namespace: "fixture" } }));
        return { state: "running" };
      }
      throw Error("unexpected control method " + method);
    } };
    globalThis[runtimeKey] = { owner: { role: "manager", instance_id: "instance" }, supervisor, instanceRoot: join(root, "instance"), runtimeRoot,
      installed: { runtime_identity: "a".repeat(64), lock_identity: "b".repeat(64), slice_identity: "c".repeat(64) }, manifest: { permission_policy: {}, options: { checks: nativeChecks } } };
    globalThis[managerKey] = { manager, pi: {}, getContext: () => context };
    SubagentsAdapter.prototype.preflightReview = async () => ({});
    SubagentsAdapter.prototype.execute = async function(input, ctx, signal, onDispatch) {
      onDispatch?.(); calls.push(["model", input.role]);
      if (input.role === "worker") fs.writeFileSync(join(input.cwd, "code.txt"), "changed\n");
      const report = input.resultSchema ? { verdict: "pass", snapshot: fault === "stale-review" ? "old-snapshot" : input.resultSchema.properties.snapshot.const, summary: "fixture evidence reviewed",
        scopeComplete: true, findings: [], evidence: [{ path: "code.txt", startLine: 1, endLine: 1 }], unverified: [] } : null;
      const read = { toolCallId: "read", payloadDigest: "a".repeat(64), readRequest: 1, deliveredRequest: 2 };
      return { descriptorId: "fixture-" + input.stepId, nativeRunId: "run-" + input.stepId, status: "ended", terminationConfirmed: true, error: null,
        content: report ? { kind: "structured", value: report } : { kind: "text", text: "fixture model output" }, observations: [{ producerId: "fixture", descriptorId: "fixture-" + input.stepId,
          toolErrors: [], requestDenials: [], activeTools: [], fileReads: [{ path: "code.txt", firstLine: 1, lastLine: 2, ...read }],
          artifactReads: (input.evidenceIds ?? []).map(id => ({ id, start: 0, end: store.get("artifacts", id).bytes, total: store.get("artifacts", id).bytes, ...read })),
          structuredOutputs: report ? [{ toolCallId: "verdict", requestOrdinal: 2, valueDigest: digest(report) }] : [] }] };
    };
    let service;
    try {
      service = new TaskService({ appendEntry() {} }, store, config, context, () => {}, () => config);
      const job = service.submit(workflow, "fixture goal");
      for (let index = 0; index < 300 && !["COMPLETED", "BLOCKED", "FAILED"].includes(service.get(job.id).status); index++) await new Promise(resolve => setImmediate(resolve));
      assert.equal(service.get(job.id).status, fault ? "BLOCKED" : "COMPLETED", service.describe(job.id).reason);
      assert.equal(fs.readFileSync(join(source, "code.txt"), "utf8"), "original\n");
      if (fault !== "zero-tests") assert.ok(calls.some(([kind, role]) => kind === "model" && role === "reviewer"));
      if (workflow === "fix") {
        assert.ok(calls.some(([kind, id]) => kind === "check" && id === "focused-tests"));
        assert.equal(fs.readFileSync(join(service.get(job.id).cwd, "code.txt"), "utf8"), "changed\n");
      }
    } finally {
      await service?.dispose(); await manager.dispose(); store.close();
      globalThis[runtimeKey] = oldRuntime; globalThis[managerKey] = oldManager;
      SubagentsAdapter.prototype.execute = originalDelegate; SubagentsAdapter.prototype.preflightReview = originalPreflight;
      childProcess.execFileSync = originalExec; syncBuiltinESMExports();
    }
  }
});
