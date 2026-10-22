import { afterAll, expect, test } from "bun:test";
import { writeFileSync } from "node:fs";
import { officialHarness, officialModules } from "./omp_permission_official_wrapper_fixture";

let modules: Awaited<ReturnType<typeof officialModules>>;
let importFailure = false;
try { modules = await officialModules(); } catch (error) {
  if (error instanceof Error && /^(?:Cannot find (?:package|module)|Module not found)/u.test(error.message)) importFailure = true;
  else throw error;
}
const current = modules ? test : test.skip;
if (!modules) test.skip(importFailure ? "official SDK dependency closure unavailable" : "official SDK source unavailable", () => {});
const live: Array<Awaited<ReturnType<typeof officialHarness>>> = [];
afterAll(async () => { for (const harness of live) await harness.cleanup(); });
const create = async (options?: Parameters<typeof officialHarness>[1]) => {
  const harness = await officialHarness(modules!, options); live.push(harness); return harness;
};
function response(decision = "allow") {
  return new Response(JSON.stringify({ choices: [{ message: { content: JSON.stringify({ decision,
    risk: decision === "allow" ? "low" : "unknown", authorization: decision === "allow" ? "sufficient" : "unknown",
    reasonCode: decision === "allow" ? "LOW_RISK_AUTHORIZED" : "UNKNOWN_RISK" }) } }] }));
}

current("official adapter/wrapper/runner dispatch ten fake Cursor Bash operations beyond hook budget", async () => {
  let reviews = 0, active = 0, peak = 0;
  const harness = await create({ fetchImpl: async () => {
    active++; peak = Math.max(peak, active);
    await new Promise(resolve => setTimeout(resolve, 45)); active--;
    return response(reviews++ === 0 ? "ask" : "allow");
  }, selectImpl: async () => { await new Promise(resolve => setTimeout(resolve, 60)); return "Approve"; } });
  const inputs = Array.from({ length: 10 }, (_, i) => ({ command: `echo fixture-${i}`, timeout: 2 }));
  const started = performance.now();
  const results = await Promise.all(inputs.map((params, i) => harness.piBash(`call_sdk_${i}`, params)));
  expect(performance.now() - started).toBeGreaterThan(30);
  expect(results.every(result => result.isError !== true)).toBe(true);
  expect(harness.settings.toolCallTimeoutMs).toBe(30);
  expect(harness.h.fetchCalls).toHaveLength(10); expect(harness.h.selectCalls).toHaveLength(1);
  expect(harness.nativeCalls).toHaveLength(10); expect(peak).toBe(2); expect(harness.errors).toEqual([]);
  for (const input of inputs) expect(harness.nativeCalls.some(call => call[1] === input)).toBe(true);
  expect(harness.h.auditEntries.filter(row => row.data.outcome === "executed")).toHaveLength(10);
  if (process.env.OMP_OFFICIAL_WRAPPER_EVIDENCE) writeFileSync(process.env.OMP_OFFICIAL_WRAPPER_EVIDENCE,
    JSON.stringify({ sourceCommit: "45c35e40c46166dc726ccc52f5d27f40f2449f99", sourceHashes: modules!.hashes,
      realModules: ["RegisteredToolAdapter", "ExtensionToolWrapper", "ExtensionRunner"], calls: 10,
      reviewerCalls: 10, nativeDelegates: 10, hostHookBudgetMs: 30, reviewerDelayMs: 45, humanDelayMs: 60,
      maxReviewerConcurrency: peak, realShellCommands: 0, realHost: false, realCursorTransport: false }) + "\n");
});

for (const decision of ["deny", "prompt"] as const) current(`official native ${decision} remains prior to model`, async () => {
  const harness = await create({ nativeDecision: decision, select: "Deny" });
  expect((await harness.piBash(`call_sdk_native_${decision}`, { command: "echo fixture" })).isError).toBe(true);
  expect(harness.h.fetchCalls).toHaveLength(0); expect(harness.nativeCalls).toHaveLength(0);
  expect(harness.h.selectCalls).toHaveLength(decision === "prompt" ? 1 : 0);
});

current("official other-extension block stops before registered execute and diagnostics", async () => {
  const harness = await create({ otherHandler: () => ({ block: true, reason: "FIXTURE_OTHER_BLOCK" }) });
  await expect(harness.piBash("call_sdk_block", { command: "echo fixture" })).rejects.toThrow("FIXTURE_OTHER_BLOCK");
  expect(harness.h.fetchCalls).toHaveLength(0); expect(harness.nativeCalls).toHaveLength(0);
  expect(harness.h.auditEntries).toHaveLength(0);
});

current("official other-extension replacement is reviewed and delegated as effective input", async () => {
  const revised = { command: "echo revised-fixture", timeout: 3 };
  const harness = await create({ otherHandler: () => ({ input: revised }) });
  expect((await harness.piBash("call_sdk_revised", { command: "echo original-fixture", timeout: 1 })).isError).toBeUndefined();
  const packet = JSON.parse(JSON.parse(harness.h.fetchCalls[0][1].body).messages.at(-1).content);
  expect(packet.command).toBe(revised.command); expect(packet.parameters.timeout).toBe(3);
  expect(harness.nativeCalls[0][1]).toBe(revised);
});

current("official preflight interceptor blocks before model and native delegate", async () => {
  const harness = await create({ preflight: () => ({ block: true, reason: "FIXTURE_INTERCEPTOR_BLOCK" }) });
  await expect(harness.piBash("call_sdk_interceptor", { command: "echo fixture" })).rejects.toThrow("FIXTURE_INTERCEPTOR_BLOCK");
  expect(harness.h.fetchCalls).toHaveLength(0); expect(harness.nativeCalls).toHaveLength(0);
});

current("official native delegation retains progress, abort channel and worktree evidence", async () => {
  let started!: () => void, finish!: () => void;
  const entered = new Promise<void>(resolve => { started = resolve; });
  const wait = new Promise<void>(resolve => { finish = resolve; });
  const plan = { backend: "auto", operations: [{ target: "../fixture-target", branch: "fixture-branch" }], effects: ["may copy ignored fixture data"] };
  const harness = await create({ worktreePlan: plan, nativeImpl: async () => { started(); await wait; return { content: [{ type: "text", text: "ok" }] }; } });
  const controller = new AbortController(), updates: any[] = [];
  const input = { command: "git worktree add ../fixture-target -b fixture-branch" };
  const running = harness.piBash("call_sdk_progress", input, controller.signal, value => updates.push(value));
  await entered;
  expect(updates).toHaveLength(1); expect(updates[0].content[0].text).toBe("fixture-progress");
  expect(harness.nativeCalls[0][1]).toBe(input); expect(harness.nativeCalls[0][2].aborted).toBe(false);
  controller.abort(); expect(harness.nativeCalls[0][2].aborted).toBe(true);
  finish(); await running;
  const packet = JSON.parse(JSON.parse(harness.h.fetchCalls[0][1].body).messages.at(-1).content);
  expect(packet.executionContext.worktreePlan).toEqual(plan);
});

for (const policy of ["deny", "prompt"] as const) current(`official outer ${policy} gate is enforced independently`, async () => {
  const harness = await create({ hostPolicy: policy, select: "Deny" });
  await expect(harness.piBash(`call_sdk_outer_${policy}`, { command: "echo fixture" })).rejects.toThrow();
  expect(harness.h.fetchCalls).toHaveLength(0); expect(harness.nativeCalls).toHaveLength(0);
  expect(harness.h.selectCalls).toHaveLength(policy === "prompt" ? 1 : 0);
});

current("official native interceptor helper still blocks inside the fake native delegate", async () => {
  let shellExecutions = 0;
  const harness = await create({ nativeImpl: async (_id, params) => {
    const interception = modules!.interceptor.checkBashInterception(params.command, ["read"],
      [{ pattern: "^cat\\s", tool: "read", message: "FIXTURE_USE_READ" }]);
    if (interception.block) return { content: [{ type: "text", text: interception.message }], isError: true };
    shellExecutions++; return { content: [{ type: "text", text: "unexpected" }] };
  } });
  const result = await harness.piBash("call_sdk_native_interceptor", { command: "cat fixture.txt" });
  expect(result.isError).toBe(true); expect(result.content[0].text).toContain("FIXTURE_USE_READ");
  expect(harness.h.fetchCalls).toHaveLength(1); expect(harness.nativeCalls).toHaveLength(1); expect(shellExecutions).toBe(0);
  expect(harness.h.auditEntries.at(-1).data.reasonCode).toBe("NATIVE_RESULT_ERROR");
});

current("official native worktree helper rewrites only within the fake native delegate", async () => {
  let executionCommand: string | undefined;
  const input = { command: "git worktree add ../fixture-target -b fixture-branch" };
  const harness = await create({ nativeImpl: async (_id, params) => {
    executionCommand = modules!.worktree.rewriteGitWorktreeAdd(params.command, ["/fixture/omp"]);
    return { content: [{ type: "text", text: "fixture-plan-only" }] };
  } });
  expect((await harness.piBash("call_sdk_native_worktree", input)).isError).toBeUndefined();
  expect(executionCommand).toBe("/fixture/omp worktree add -b fixture-branch -- ../fixture-target");
  expect(harness.nativeCalls[0][1]).toBe(input);
  const packet = JSON.parse(JSON.parse(harness.h.fetchCalls[0][1].body).messages.at(-1).content);
  expect(packet.command).toBe(input.command);
});

current("official snapshot context rejects a live session cwd change during model review", async () => {
  let started!: (packet: any) => void;
  const entered = new Promise<any>(resolve => { started = resolve; });
  let finishFetch!: () => void;
  const fetchFinished = new Promise<void>(resolve => { finishFetch = resolve; });
  const harness = await create({ fetchImpl: async (_url, init) => {
    const packet = JSON.parse(JSON.parse(init.body as string).messages.at(-1).content);
    started(packet);
    await new Promise(resolve => setTimeout(resolve, 45));
    finishFetch();
    return response();
  } });
  // actual runner创建的ctx.cwd是快照，SessionManager.getCwd仍引用实时目录。
  const snapshotCtx = harness.runner.createContext();
  expect(snapshotCtx.cwd).toBe("/repo");
  const pending = harness.piBash("call_sdk_live_cwd", { command: "echo fixture" });
  const packet = await entered;
  expect(packet.cwd).toBe("/repo"); expect(packet.executionContext.baseCwd).toBe("/repo");
  harness.h.ctx.cwd = "/fixture-moved";
  expect(snapshotCtx.cwd).toBe("/repo");
  expect(snapshotCtx.sessionManager.getCwd()).toBe("/fixture-moved");
  const result = await pending;
  expect(result.isError).toBe(true);
  expect(["STALE_REVIEW", "CANCELLED"]).toContain(result.details.reasonCode);
  expect(harness.nativeCalls).toHaveLength(0); expect(harness.h.execCalls).toHaveLength(0);
  expect(harness.h.selectCalls).toHaveLength(0); expect(harness.h.fetchCalls).toHaveLength(1);
  // 即使不能取消的假fetch稍后返回allow，也不能重新取得执行权。
  await fetchFinished; await Promise.resolve();
  expect(harness.nativeCalls).toHaveLength(0); expect(harness.h.auditEntries).toHaveLength(1);
});
