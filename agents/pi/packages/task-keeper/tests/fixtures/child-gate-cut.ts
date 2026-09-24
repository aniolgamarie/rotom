import { cpSync, symlinkSync, readFileSync, writeFileSync, watch, existsSync } from "node:fs";
import { join, basename } from "node:path";
import { createHash } from "node:crypto";

/** Instrument only a private runtime copy; the production reporter has no test bypass or fault switch. */
export function childGateCut(source: string, root: string, cut: string, targetCall = 1, parentCancellation = false) {
  const copy = join(root, "fault-package"), ready = join(root, "gate-ready.json"), release = join(root, "gate-release");
  cpSync(source, copy, { recursive: true, filter: path => !["node_modules", "test-results", "coverage", ".git"].includes(basename(path)) });
  symlinkSync(join(source, "node_modules"), join(copy, "node_modules"));
  const path = join(copy, "src/adapters/child-reporter.ts"), original = readFileSync(path, "utf8");
  const hook = "taskKeeperTestCut(ctx);";
  const substitutions: Record<string, [string, string]> = {
    "before-gate": ['pi.on("before_provider_request", (event, ctx) => {', `pi.on("before_provider_request", (event, ctx) => { ${hook}`],
    "after-reserve": ['store!.reserveRequest(descriptor!.owner, leaseId, attempt.id, descriptor!.budgetLimits);', `store!.reserveRequest(descriptor!.owner, leaseId, attempt.id, descriptor!.budgetLimits); ${hook}`],
    "after-recheck": ['try { assertRequest(); }', `try { assertRequest(); ${hook} }`],
    "after-receiver": ['record("http_response", { requestId: attempt.id, status: response.status, headers: response.headers });', `record("http_response", { requestId: attempt.id, status: response.status, headers: response.headers }); ${hook}`],
  };
  if (!Number.isSafeInteger(targetCall) || targetCall < 1) throw new Error("Invalid native gate target call");
  if (cut === "before-gate" && targetCall > 1) substitutions[cut] = ['before: (attempt) => {', `before: (attempt) => { ${hook}`];
  const [needle, replacement] = substitutions[cut];
  if (original.split(needle).length !== 2) throw new Error(`Ambiguous native gate cut ${cut}`);
  const invokeNeedle = '          invoke();';
  if (original.split(invokeNeedle).length !== 2) throw new Error("Ambiguous child invocation observation point");
  const body = original.replace(needle, replacement).replace(invokeNeedle,
    `          testAppend(${JSON.stringify(join(root, "gate-invocations.jsonl"))}, JSON.stringify({requestId:_attempt.id,databaseTransaction:store!.db.isTransaction}) + "\\n");\n${invokeNeedle}`);
  const instrumented = `import { appendFileSync as testAppend, writeFileSync as testWrite, renameSync as testRename, existsSync as testExists } from "node:fs";
let taskKeeperTestCalls = 0;
function taskKeeperTestCut(ctx: { abort(): void }) {
  if (++taskKeeperTestCalls !== ${targetCall}) return;
  testWrite(${JSON.stringify(ready + ".tmp")}, JSON.stringify({cut:${JSON.stringify(cut)},pid:process.pid,call:taskKeeperTestCalls}));
  testRename(${JSON.stringify(ready + ".tmp")}, ${JSON.stringify(ready)});
  const until=Date.now()+10000;
  while(!testExists(${JSON.stringify(release)})) {
    if(Date.now()>until) throw new Error("Native gate cut was not released by test observer");
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,5);
  }
  if (!${parentCancellation}) ctx.abort();
}
` + body;
  writeFileSync(path, instrumented);
  if (parentCancellation) {
    const harnessPath = join(copy, "tests/fixtures/subagents-harness.ts"), harness = readFileSync(harnessPath, "utf8");
    const needle = 'const adapter = new SubagentsAdapter(pi, store, config, owner), cancellation = new AbortController();';
    if (harness.split(needle).length !== 2) throw new Error("Ambiguous parent cancellation fixture");
    writeFileSync(harnessPath, harness.replace(needle, needle + `
        let cutCancelled = false;
        const cutWatcher = watch(${JSON.stringify(root)}, () => {
          if (!cutCancelled && existsSync(${JSON.stringify(ready)})) {
            cutCancelled = true; cancellation.abort();
            writeFileSync(${JSON.stringify(release)}, "public adapter cancellation delivered before child resumes");
          }
        });
        removeFaultObserver = () => cutWatcher.close();
    `));
  }

  const sha = (value: string) => createHash("sha256").update(value).digest("hex");
  writeFileSync(join(root, "gate-fault-manifest.json"), JSON.stringify({ cut, targetCall, parentCancellation, parentHarness: parentCancellation ? { originalSha256: sha(readFileSync(join(source, "tests/fixtures/subagents-harness.ts"), "utf8")), instrumentedSha256: sha(readFileSync(join(copy, "tests/fixtures/subagents-harness.ts"), "utf8")) } : null, originalSha256: sha(original), instrumentedSha256: sha(instrumented), path }));
  let reached: { cut: string; pid: number; call: number } | null = null;
  const observer = watch(root, () => {
    if (!reached && existsSync(ready)) { reached = JSON.parse(readFileSync(ready, "utf8")); if (!parentCancellation) writeFileSync(release, "observer releases cancellation at the recorded native cut"); }
  });
  return { copy, observed: () => reached, close: () => observer.close() };
}
