import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { isDeepStrictEqual } from "node:util";
import { gunzipSync } from "node:zlib";
import { createHash } from "node:crypto";
import { createStandalonePlugin, type StandaloneConfig } from "../agents/omp/packages/omp-permission-control/standalone";
import type { NativeBashRuntime, NativeSettingsSnapshot } from "../agents/omp/packages/omp-permission-control/native-bash";

type Decision = "allow" | "ask" | "deny";
type Path = "permission_bash" | "native-bash" | "native-zsh";
export interface ProductFixture {
  schemaVersion: 1;
  publication: "synthetic-public";
  purpose: "model-first-routing-baseline";
  tasks: Array<{ id: string; family: string; goal: string; authorization: string; fixtureFacts: unknown;
    variants: Array<{ id: string; command: string }>; expectedRoute: "model"; expectedRisk: "low" | "ask" | "deny" }>;
  exceptions: Array<{ id: string; command: string; policy: "deny" | "prompt"; pattern: string; expectedRoute: "deny" | "human" }>;
}

function fields(value: any, names: string[], label: string) {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).some(key => !names.includes(key)) || names.some(key => !(key in value)))
    throw new Error(`Invalid fields: ${label}`);
}
function textField(value: unknown, label: string) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`Invalid text: ${label}`);
}
export function validateProductFixture(value: unknown): ProductFixture {
  const f: any = value;
  fields(f, ["schemaVersion", "publication", "purpose", "tasks", "exceptions"], "fixture");
  if (f.schemaVersion !== 1 || f.publication !== "synthetic-public" || f.purpose !== "model-first-routing-baseline" ||
      !Array.isArray(f.tasks) || !f.tasks.length || !Array.isArray(f.exceptions)) throw new Error("Invalid fixture header");
  const ids = new Set<string>(); const commands = new Set<string>();
  const unique = (set: Set<string>, value: string, label: string) => {
    textField(value, label); if (set.has(value)) throw new Error(`Duplicate ${label}`); set.add(value);
  };
  for (const task of f.tasks) {
    fields(task, ["id", "family", "goal", "authorization", "fixtureFacts", "variants", "expectedRoute", "expectedRisk"], "task");
    unique(ids, task.id, "id");
    for (const key of ["family", "goal", "authorization"]) textField(task[key], key);
    if (task.fixtureFacts === null || task.fixtureFacts === undefined ||
        !["string", "object"].includes(typeof task.fixtureFacts) || !JSON.stringify(task.fixtureFacts).length ||
        !Array.isArray(task.variants) || !task.variants.length || task.expectedRoute !== "model" ||
        !["low", "ask", "deny"].includes(task.expectedRisk)) throw new Error("Invalid task expectations or facts");
    for (const variant of task.variants) {
      fields(variant, ["id", "command"], "variant"); unique(ids, variant.id, "id"); unique(commands, variant.command, "command");
    }
  }
  for (const row of f.exceptions) {
    fields(row, ["id", "command", "policy", "pattern", "expectedRoute"], "exception");
    unique(ids, row.id, "id"); unique(commands, row.command, "command"); textField(row.pattern, "pattern");
    if (!["deny", "prompt"].includes(row.policy) || row.expectedRoute !== (row.policy === "deny" ? "deny" : "human"))
      throw new Error("Invalid exception expectation");
  }
  return f;
}

export interface ProductRow {
  taskId: string; variantId: string; family: string; command: string; source: "task" | "exception";
  path: Path; expectedRoute: string; expectedRisk: string; injectedDecision: Decision;
  modelCalls: number; humanCalls: number; execCalls: number; nativeDelegateCalls: number;
  order: string[]; inputComplete: boolean | null; modelDecisionPreserved: boolean | null; originalParametersUnchanged: boolean;
  reasonCode: string; preModelGates: string[]; outcome: string; failures: string[]; passed: boolean;
}
const paths: Path[] = ["permission_bash", "native-bash", "native-zsh"];
const reviews = {
  allow: { decision: "allow", risk: "low", authorization: "sufficient", reasonCode: "LOW_RISK_AUTHORIZED" },
  ask: { decision: "ask", risk: "unknown", authorization: "unknown", reasonCode: "USER_CONFIRMATION_REQUIRED" },
  deny: { decision: "deny", risk: "high", authorization: "insufficient", reasonCode: "HIGH_RISK" },
};

async function observe(row: { taskId: string; variantId: string; family: string; command: string; message: string;
  source: "task" | "exception"; expectedRoute: string; expectedRisk: string; policy?: "deny" | "prompt"; pattern?: string },
  path: Path, decision: Decision): Promise<ProductRow> {
  const tools = new Map<string, any>(); const events = new Map<string, any>();
  const order: string[] = []; const prompts: any[] = []; const audits: any[] = [];
  const execs: any[][] = []; const delegates: any[] = []; let humanCalls = 0;
  const diagnostics = { shellFamily: path === "native-zsh" ? "zsh" : "bash",
    executionRoute: "local-embedded", contextReason: "STANDARD_CONTEXT" } as const;
  const settings = {};
  const snapshot: NativeSettingsSnapshot = { settings, fingerprint: "synthetic-settings-1", decision: row.policy ?? "allow",
    reasonCode: row.policy === "deny" ? "NATIVE_DENY" : row.policy === "prompt" ? "NATIVE_PROMPT" : "NATIVE_ALLOW",
    diagnostics, reviewContext: { ...diagnostics, sameSettingsInstance: true, nativeDecision: row.policy ?? "allow" } };
  const runtime: NativeBashRuntime = { capture: async () => snapshot, recheck: async supplied => {
    if (supplied !== settings) throw new Error("Harness settings identity mismatch"); return snapshot;
  } };
  const digest = "a".repeat(64);
  const config: StandaloneConfig = { schemaVersion: 2, defaultMode: "smart", reviewer: "session",
    pluginId: "omp-permission-control", pluginDigest: digest, policyVersion: digest, nativeBash: true,
    nativePatterns: row.policy ? [{ approval: row.policy, match: row.pattern! }] : [] };
  const host: any = {
    typebox: { Type: { String: (extra = {}) => ({ type: "string", ...extra }), Number: (extra = {}) => ({ type: "number", ...extra }),
      Optional: (value: unknown) => value, Object: (properties: unknown, extra: object) => ({ properties, ...extra }) } },
    appendEntry: (type: string, data: any) => { if (type === "permission-control.audit.v1") audits.push(data); },
    getAllTools: () => [...tools.values()], getActiveTools: () => ["bash"], setActiveTools: async () => {},
    registerTool: (tool: any) => tools.set(tool.name, tool), registerCommand: () => {},
    on: (name: string, handler: any) => events.set(name, handler),
    exec: async (...args: any[]) => { order.push("exec"); execs.push(args); return { stdout: "synthetic result", stderr: "", code: 0, killed: false }; },
  };
  await createStandalonePlugin({ loadConfig: async () => config, loadNativeRuntime: async () => runtime,
    fetch: (async (_input: unknown, init: RequestInit) => {
      order.push("model");
      const envelope = JSON.parse(String(init.body));
      prompts.push(JSON.parse(envelope.messages.at(-1).content));
      return new Response(JSON.stringify({ choices: [{ message: { content: JSON.stringify(reviews[decision]) } }] }), { status: 200 });
    }) as typeof fetch })(host);
  const model = { provider: "synthetic", id: "reviewer", api: "openai-completions", baseUrl: "https://invalid.test/v1" };
  const ctx: any = { hasUI: true, cwd: "/synthetic/repo",
    ui: { select: async () => { humanCalls++; order.push("human"); return "Deny"; }, notify: () => {} },
    models: { current: () => model, resolve: () => model }, modelRegistry: { getApiKey: async () => "synthetic-key" },
    sessionManager: { getBranch: () => [{ type: "message", message: { role: "user", content: row.message, timestamp: 1 } }],
      getSessionId: () => "synthetic-session" },
    invokeTool: async (input: any) => { delegates.push(input); order.push("nativeDelegate"); return { content: [{ type: "text", text: "synthetic result" }] }; },
  };
  await events.get("session_start")({}, ctx);
  const toolName = path === "permission_bash" ? "permission_bash" : "bash";
  const input = Object.freeze({ command: row.command, cwd: "/synthetic/repo", timeout: 30 });
  const before = { ...input };
  const blocked = await events.get("tool_call")({ type: "tool_call", toolName, toolCallId: "call_product", input }, ctx);
  if (blocked === undefined) await tools.get(toolName).execute("call_product", input, undefined, undefined, ctx);
  const last = audits.at(-1);
  if (!last) throw new Error("Harness missing terminal audit");
  const inputComplete = prompts.length === 0 ? null : prompts.length === 1 && prompts[0].command === row.command && prompts[0].cwd === ctx.cwd &&
    isDeepStrictEqual(prompts[0].parameters, { cwd: input.cwd, timeout: input.timeout }) &&
    isDeepStrictEqual(prompts[0].genuineUserMessages, [row.message]) &&
    isDeepStrictEqual(prompts[0].executionContext, { entrypoint: toolName, baseCwd: ctx.cwd, ...snapshot.reviewContext });
  const originalParametersUnchanged = isDeepStrictEqual(input, before) && (path === "permission_bash"
    ? execs.every(args => args[0] === "bash" && isDeepStrictEqual(args[1], ["--noprofile", "--norc", "-c", row.command]) &&
      args[2].cwd === input.cwd && args[2].timeout === input.timeout * 1000)
    : delegates.every(supplied => supplied === input && isDeepStrictEqual(supplied, before)));
  const failures: string[] = [];
  const expect = (condition: boolean, code: string) => { if (!condition) failures.push(code); };
  const executions = execs.length + delegates.length;
  if (row.expectedRoute === "model") {
    expect(prompts.length === 1, "MODEL_FIRST_ROUTING");
    if (prompts.length === 1) {
      expect(inputComplete === true, "REVIEW_INPUT_INCOMPLETE");
      expect(last.reasonCode === reviews[decision].reasonCode, "MODEL_DECISION_NOT_PRESERVED");
    }
    expect(humanCalls === (decision === "ask" ? 1 : 0), "HUMAN_CALL_COUNT");
    expect(executions === (decision === "allow" ? 1 : 0), "EXECUTION_COUNT");
    expect(order[0] === "model" && last.preModelGates.length === 0, "PRE_MODEL_GATE");
    expect(last.outcome === (decision === "allow" ? "executed" : "blocked"), "TERMINAL_OUTCOME");
  } else if (row.expectedRoute === "invalid-input-rejected") {
    expect(prompts.length === 0 && humanCalls === 0 && executions === 0, "INVALID_INPUT_SIDE_EFFECT");
    expect(last.outcome === "blocked" && last.preModelGates.includes("INVALID_PARAMETERS"), "INVALID_INPUT_NOT_REJECTED");
  } else {
    expect(prompts.length === 0, "EXCEPTION_MODEL_CALL"); expect(executions === 0, "EXCEPTION_EXECUTED");
    expect(humanCalls === (row.expectedRoute === "human" ? 1 : 0), "EXCEPTION_HUMAN_CALL_COUNT");
    expect(last.outcome === "blocked", "EXCEPTION_OUTCOME");
  }
  expect(originalParametersUnchanged, "PARAMETERS_CHANGED");
  expect(path === "permission_bash" ? delegates.length === 0 : execs.length === 0, "WRONG_EXECUTION_PATH");
  return { taskId: row.taskId, variantId: row.variantId, family: row.family, command: row.command, source: row.source,
    path, expectedRoute: row.expectedRoute, expectedRisk: row.expectedRisk, injectedDecision: decision,
    modelCalls: prompts.length, humanCalls, execCalls: execs.length, nativeDelegateCalls: delegates.length, order,
    inputComplete, modelDecisionPreserved: prompts.length === 1 ? last.reasonCode === reviews[decision].reasonCode : null, originalParametersUnchanged, reasonCode: last.reasonCode, preModelGates: last.preModelGates,
    outcome: last.outcome, failures, passed: failures.length === 0 };
}

export async function evaluateProductAcceptance(input: unknown) {
  const fixture = validateProductFixture(input);
  // 生产审批入口只能使用上面的假传输和委派，阻断意外全局网络和进程执行。
  const savedFetch = globalThis.fetch; const savedSpawn = Bun.spawn; const savedSpawnSync = Bun.spawnSync;
  const reject = () => { throw new Error("Harness forbids external network or process execution"); };
  globalThis.fetch = reject as typeof fetch; Bun.spawn = reject as typeof Bun.spawn; Bun.spawnSync = reject as typeof Bun.spawnSync;
  const rows: ProductRow[] = [];
  try {
    for (const task of fixture.tasks) for (const variant of task.variants) {
      const message = `Goal: ${task.goal}\nUser permits: ${task.authorization}\nKnown synthetic fixture facts: ${JSON.stringify(task.fixtureFacts)}`;
      for (const path of paths) for (const decision of task.expectedRisk === "low" ? ["allow", "ask", "deny"] as const : [task.expectedRisk])
        rows.push(await observe({ taskId: task.id, variantId: variant.id, family: task.family, command: variant.command,
          message, source: "task", expectedRoute: task.expectedRoute, expectedRisk: task.expectedRisk }, path, decision));
    }
    for (const exception of fixture.exceptions) for (const path of paths)
      rows.push(await observe({ taskId: exception.id, variantId: exception.id, family: "configured-exception", command: exception.command,
        message: "Apply the explicit synthetic policy before any execution.", source: "exception", expectedRoute: exception.expectedRoute,
        expectedRisk: exception.policy, policy: exception.policy, pattern: exception.pattern }, path, "allow"));
  } finally { globalThis.fetch = savedFetch; Bun.spawn = savedSpawn; Bun.spawnSync = savedSpawnSync; }
  const failureCategories: Record<string, number> = {};
  for (const row of rows) for (const failure of row.failures) failureCategories[failure] = (failureCategories[failure] ?? 0) + 1;
  return { schemaVersion: 1, publication: "synthetic-public", purpose: fixture.purpose,
    fixtureDigest: createHash("sha256").update(JSON.stringify(fixture)).digest("hex"),
    evidence: "fake-model-public-plugin-entrypoints", realModelQuality: "not-verified", realHostEffects: "not-verified",
    taskCount: fixture.tasks.length, variantCount: fixture.tasks.reduce((sum, task) => sum + task.variants.length, 0),
    rows, totals: { rows: rows.length, passed: rows.filter(row => row.passed).length,
      failed: rows.filter(row => !row.passed).length, modelCalls: rows.reduce((sum, row) => sum + row.modelCalls, 0),
      humanCalls: rows.reduce((sum, row) => sum + row.humanCalls, 0), executions: rows.reduce((sum, row) => sum + row.execCalls + row.nativeDelegateCalls, 0) },
    failureCategories, productPassed: rows.every(row => row.passed) };
}

export async function evaluateSyntheticMessageRouting(command: string, message: string) {
  textField(command, "command"); textField(message, "message");
  const savedFetch = globalThis.fetch; const savedSpawn = Bun.spawn; const savedSpawnSync = Bun.spawnSync;
  const reject = () => { throw new Error("Harness forbids external network or process execution"); };
  globalThis.fetch = reject as typeof fetch; Bun.spawn = reject as typeof Bun.spawn; Bun.spawnSync = reject as typeof Bun.spawnSync;
  try {
    const rows: ProductRow[] = [];
    for (const path of paths) rows.push(await observe({ taskId: "synthetic-message", variantId: "synthetic-message", family: "message-privacy",
      command, message, source: "task", expectedRoute: "model", expectedRisk: "low" }, path, "ask"));
    return { command, syntheticMessage: message, rows, productPassed: rows.every(row => row.passed) };
  } finally { globalThis.fetch = savedFetch; Bun.spawn = savedSpawn; Bun.spawnSync = savedSpawnSync; }
}

export function validateRoutingPolicy(input: unknown): any {
  const p: any = input;
  fields(p, ["schemaVersion", "publication", "purpose", "defaultRoute", "corpus", "routingContract", "exceptions", "inputValidationCases", "scope"], "routing policy");
  fields(p.corpus, ["path", "sha256", "publication", "recordCount", "categories", "representedScenarioCount"], "policy corpus");
  fields(p.routingContract, ["modelReachCount", "inputValidationCount", "preModelExceptionCount", "fakeModelDecision", "expectedExecutedCommandCount", "rationale"], "routing contract");
  if (p.schemaVersion !== 1 || p.publication !== "synthetic-public" || p.purpose !== "model-first-routing-baseline" ||
      p.defaultRoute !== "model" || p.corpus.publication !== "synthetic-public" ||
      p.corpus.path !== "tests/fixtures/omp/command-scenarios/corpus.json.gz" || !/^[a-f0-9]{64}$/u.test(p.corpus.sha256) ||
      !Number.isSafeInteger(p.corpus.recordCount) || p.corpus.recordCount < 1 ||
      !Number.isSafeInteger(p.corpus.representedScenarioCount) || p.corpus.representedScenarioCount < p.corpus.recordCount ||
      p.routingContract.modelReachCount + p.routingContract.inputValidationCount !== p.corpus.recordCount || p.routingContract.preModelExceptionCount !== 0 ||
      p.routingContract.fakeModelDecision !== "ask" || p.routingContract.expectedExecutedCommandCount !== 0 ||
      !Number.isSafeInteger(p.routingContract.inputValidationCount) || p.routingContract.inputValidationCount < 0 ||
      !Array.isArray(p.inputValidationCases) || p.inputValidationCases.length !== p.routingContract.inputValidationCount ||
      !Array.isArray(p.exceptions) || p.exceptions.length !== 0) throw new Error("Invalid routing policy contract");
  const validationIds = new Set<string>();
  for (const row of p.inputValidationCases) {
    fields(row, ["id", "reason", "expectedRoute"], "input validation case");
    if (typeof row.id !== "string" || !/^[a-f0-9]{64}$/u.test(row.id) || validationIds.has(row.id) ||
        row.reason !== "EMPTY_COMMAND" || row.expectedRoute !== "invalid-input-rejected") throw new Error("Invalid input validation policy");
    validationIds.add(row.id);
  }
  fields(p.corpus.categories, ["compound", "control-flow", "dynamic", "glob", "multiline", "redirection", "simple"], "policy categories");
  if (Object.values(p.corpus.categories).some(count => !Number.isSafeInteger(count) || Number(count) < 0))
    throw new Error("Invalid policy categories");
  textField(p.scope, "scope"); textField(p.routingContract.rationale, "rationale");
  return p;
}

// 只读冻结历史语料；历史解析标签只用于对照，不参与新路由预期。
export async function evaluateHistoricalRouting(corpusBytes: Uint8Array, policyInput: unknown,
  options: { recordIds?: string[] } = {}) {
  const policy = validateRoutingPolicy(policyInput);
  const corpusDigest = createHash("sha256").update(corpusBytes).digest("hex");
  if (corpusDigest !== policy.corpus.sha256) throw new Error("Frozen corpus digest mismatch");
  const corpus = JSON.parse(gunzipSync(corpusBytes).toString("utf8"));
  fields(corpus, ["schemaVersion", "publication", "oracleVersion", "summary", "records"], "historical corpus");
  if (corpus.schemaVersion !== 1 || corpus.oracleVersion !== 1 || corpus.publication !== "synthetic-public" ||
      !Array.isArray(corpus.records) || corpus.records.length !== policy.corpus.recordCount) throw new Error("Invalid frozen corpus");
  fields(corpus.summary, ["expectedUnsupported", "representedScenarios", "publicCases", "expectedComplete", "mergedRebuiltCases", "inputScenarios", "categories"], "historical summary");
  const ids = new Set<string>(); const commands = new Set<string>(); const categories: Record<string, number> = {};
  let represented = 0;
  for (const row of corpus.records) {
    fields(row, ["id", "command", "category", "features", "representedScenarios", "expected", "expectedGate"], "historical row");
    if (typeof row.id !== "string" || !/^[a-f0-9]{64}$/u.test(row.id) || ids.has(row.id) ||
        typeof row.command !== "string" || commands.has(row.command) ||
        !Object.keys(policy.corpus.categories).includes(row.category) || !Array.isArray(row.features) ||
        row.features.some((value: unknown) => typeof value !== "string") ||
        !Number.isSafeInteger(row.representedScenarios) || row.representedScenarios < 1 ||
        !["model", "human"].includes(row.expectedGate) || !["complete", "unsupported"].includes(row.expected?.status))
      throw new Error("Invalid historical record");
    ids.add(row.id); commands.add(row.command); represented += row.representedScenarios;
    categories[row.category] = (categories[row.category] ?? 0) + 1;
  }
  const invalidCommands = corpus.records.filter((row: any) => !row.command.trim());
  if (invalidCommands.length !== policy.inputValidationCases.length ||
      invalidCommands.some((row: any) => !policy.inputValidationCases.some((entry: any) => entry.id === row.id)))
    throw new Error("Input validation cases do not match frozen corpus");
  if (!isDeepStrictEqual(categories, policy.corpus.categories) || represented !== policy.corpus.representedScenarioCount ||
      !isDeepStrictEqual(corpus.summary.categories, categories) || corpus.summary.publicCases !== corpus.records.length ||
      corpus.summary.representedScenarios !== represented) throw new Error("Frozen corpus counts mismatch");
  fields(options, options.recordIds === undefined ? [] : ["recordIds"], "evaluation options");
  if (options.recordIds !== undefined && (!Array.isArray(options.recordIds) || !options.recordIds.length ||
      new Set(options.recordIds).size !== options.recordIds.length || options.recordIds.some(id => !ids.has(id))))
    throw new Error("Invalid selected corpus IDs");
  const selected = options.recordIds ? corpus.records.filter((row: any) => options.recordIds!.includes(row.id)) : corpus.records;
  const rows: Array<Omit<ProductRow, "command" | "order" | "taskId" | "variantId" | "source" | "expectedRisk" | "injectedDecision"> & { recordId: string; historicalExpected: unknown; historicalExpectedGate: string }> = [];
  const savedFetch = globalThis.fetch; const savedSpawn = Bun.spawn; const savedSpawnSync = Bun.spawnSync;
  const reject = () => { throw new Error("Harness forbids external network or process execution"); };
  globalThis.fetch = reject as typeof fetch; Bun.spawn = reject as typeof Bun.spawn; Bun.spawnSync = reject as typeof Bun.spawnSync;
  try {
    for (const record of selected) for (const path of paths) {
      const result = await observe({ taskId: record.id, variantId: record.id, family: record.category, command: record.command,
        message: "Review this frozen synthetic-public command before execution. Its effects and authorization are uncertain; ask the user when needed. All paths and identifiers are synthetic fixture inputs.",
        source: "task", expectedRoute: policy.inputValidationCases.some((entry: any) => entry.id === record.id) ? "invalid-input-rejected" : "model", expectedRisk: "unknown" }, path, "ask");
      const { command: _command, order: _order, taskId: _taskId, variantId: _variantId, source: _source,
        expectedRisk: _expectedRisk, injectedDecision: _decision, ...measurement } = result;
      rows.push({ ...measurement, recordId: record.id, historicalExpected: { status: record.expected.status }, historicalExpectedGate: record.expectedGate });
    }
  } finally { globalThis.fetch = savedFetch; Bun.spawn = savedSpawn; Bun.spawnSync = savedSpawnSync; }
  const byPath: Record<string, any> = {}; const byCategory: Record<string, any> = {}; const byGate: Record<string, number> = {};
  const failureCategories: Record<string, number> = {};
  for (const row of rows) {
    for (const [group, key] of [[byPath, row.path], [byCategory, row.family]] as const) {
      group[key] ??= { rows: 0, modelReached: 0, passed: 0, failed: 0, humanCalls: 0, executions: 0 };
      group[key].rows++; group[key].modelReached += row.modelCalls === 1 ? 1 : 0;
      group[key][row.passed ? "passed" : "failed"]++; group[key].humanCalls += row.humanCalls;
      group[key].executions += row.execCalls + row.nativeDelegateCalls;
    }
    for (const gate of row.preModelGates) byGate[gate] = (byGate[gate] ?? 0) + 1;
    for (const failure of row.failures) failureCategories[failure] = (failureCategories[failure] ?? 0) + 1;
  }
  return { schemaVersion: 1, publication: "synthetic-public", purpose: policy.purpose, corpusDigest,
    routingPolicyDigest: createHash("sha256").update(JSON.stringify(policy)).digest("hex"),
    evidence: "fake-model-public-plugin-entrypoints", realModelQuality: "not-verified", realHostEffects: "not-verified",
    corpusRecordCount: corpus.records.length, evaluatedRecordCount: selected.length, subset: options.recordIds !== undefined,
    injectedDecision: "ask", rows, byPath, byCategory, byGate, failureCategories,
    totals: { rows: rows.length, passed: rows.filter(row => row.passed).length, failed: rows.filter(row => !row.passed).length,
      modelCalls: rows.reduce((sum, row) => sum + row.modelCalls, 0), humanCalls: rows.reduce((sum, row) => sum + row.humanCalls, 0),
      executions: rows.reduce((sum, row) => sum + row.execCalls + row.nativeDelegateCalls, 0) },
    productPassed: rows.every(row => row.passed) };
}

if (import.meta.main) {
  try {
    const args = process.argv.slice(2);
    if (args.length !== 2 || args[0] !== "--report" || !args[1]) throw new Error("Usage: check-omp-permission-product.ts --report PATH");
    const policyPath = resolve(import.meta.dir, "../tests/fixtures/omp/permission-product-acceptance/routing-policy.json");
    const policy = validateRoutingPolicy(JSON.parse(readFileSync(policyPath, "utf8")));
    const corpusPath = resolve(import.meta.dir, "..", policy.corpus.path);
    const baseline = await evaluateHistoricalRouting(readFileSync(corpusPath), policy);
    const messageObservations = [
      await evaluateSyntheticMessageRouting("pwd", "Authorization: read-only query"),
      await evaluateSyntheticMessageRouting("pwd", "User permits: read-only query"),
    ];
    const report = { ...baseline, baselineProductPassed: baseline.productPassed, messageObservations,
      productPassed: baseline.productPassed && messageObservations.every(observation => observation.productPassed) };
    const reportPath = resolve(args[1]); mkdirSync(dirname(reportPath), { recursive: true });
    writeFileSync(reportPath, JSON.stringify(report) + "\n");
    console.log(JSON.stringify({ ...report.totals, byPath: report.byPath, byCategory: report.byCategory,
      byGate: report.byGate, messageObservations: report.messageObservations.map(observation => ({ message: observation.syntheticMessage,
        rows: observation.rows.map(row => ({ path: row.path, modelCalls: row.modelCalls, preModelGates: row.preModelGates, passed: row.passed })) })), failureCategories: report.failureCategories, productPassed: report.productPassed }));
    process.exitCode = report.productPassed ? 0 : 1;
  } catch { console.error("Product acceptance harness/fixture error; no product pass recorded."); process.exitCode = 2; }
}
