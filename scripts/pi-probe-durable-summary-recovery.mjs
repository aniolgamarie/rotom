// 仅另行授权的三个 guest；默认 Python 检查不加载 Node 或 SDK。
import assert from "node:assert/strict";
import { open, readFile } from "node:fs/promises";
const invoke = Reflect.apply;
const aborted = Object.getOwnPropertyDescriptor(AbortSignal.prototype, "aborted").get;
const add = EventTarget.prototype.addEventListener, remove = EventTarget.prototype.removeEventListener;
function deferred() { let resolve; const promise = new Promise(yes => { resolve = yes; }); return { promise, resolve }; }
async function main() {
  const cases = ["summarize-before-send-fresh-bounded-authority", "summarize-before-send-denied", "summarize-unknown-sending-denied"], selected = process.argv[3];
  assert.equal(process.argv.length, 4); assert.equal(process.argv[2], "--native-durable-summary-recovery-worker"); assert(cases.includes(selected));
  assert.equal(process.env.PI_DURABLE_SUMMARY_RECOVERY_NATIVE, "1"); assert.equal(process.version, "v24.14.0"); process.umask(0o077);
  const [sdk, sqlite, nodeSqlite, ai, contextExport, ownJson, ownStorage, ownLedger, ownRegistry] = await Promise.all([
    import("@earendil-works/pi-durable"), import("@earendil-works/pi-durable/storage/sqlite"), import("@earendil-works/pi-durable/storage/sqlite/node"),
    import("@earendil-works/pi-ai"), import("@earendil-works/chord/context"), import("/probe/json.mjs"), import("/probe/storage.ts"), import("/probe/model-attempts.ts"), import("/probe/registry.ts"),
  ]);
  const ctx = contextExport.BACKGROUND_CONTEXT, canonical = ownJson.canonicalProbeJson;
  const fixture = JSON.parse(await readFile("/probe/fixture/oracle.json", "utf8")), intent = fixture.intents[selected]; assert(intent);
  const unknownSending = selected === cases[2], allowFresh = selected === cases[0];
  const versions = { durable: JSON.parse(await readFile("/durable/package.json", "utf8")).version,
    chord: JSON.parse(await readFile("/candidate/node_modules/@earendil-works/chord/package.json", "utf8")).version,
    pi_ai: JSON.parse(await readFile("/candidate/node_modules/@earendil-works/pi-ai/package.json", "utf8")).version, node: process.versions.node };
  assert.deepEqual(versions, { durable: "1.0.1", chord: "1.0.2", pi_ai: "1.0.2", node: "24.14.0" });
  const counter = () => ({ authorize: 0, prepare: 0, commitSending: 0, stream: 0, complete: 0, resultFacts: 0, recordResult: 0, settle: 0 });
  const state = { schema: 1, case: selected, versions, nativeStarted: true, phase: "complete", nativeTaskId: null, nativeConversationId: null,
    firstKeptEntryId: null, historyEntryIds: [], summarySubmissionId: null, summaryEntryId: null, summaryHeadEntryId: null,
    metadataGetModel: { old: 0, fresh: 0 }, counters: { old: counter(), fresh: counter() }, sendingReceipts: { old: [], fresh: [] }, trace: [],
    settings: [], oldTask: null, freshStoredTask: null, freshOpenTask: null, checkpointMatched: false, oldClosed: false, heldSettled: false,
    oldSignalAborted: false, newSignalDifferent: false, newEnvelopeDifferent: false, crossEnvelopeMatched: false, withinEnvelopeMatched: { old: false, fresh: false },
    sameSignal: { old: false, fresh: false }, normalizedOptions: null, beforeResumeZero: false, ledgerBeforeClose: null, ledgerFreshPassive: null, ledgerFinal: null,
    taskOutcome: null, summaryMatched: false, errorMatched: false, rootBodyCalls: 0, backendCalls: 0, reportCalls: 0, closed: false,
    runtimeReference: "unknown", chordContextReference: "unknown" };
  const model = { provider: intent.route.provider, id: intent.route.model, name: "Synthetic", api: "openai-completions", baseUrl: "https://synthetic.invalid", reasoning: false,
    input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 8192, maxTokens: 64 };
  const settings = { retry: { enabled: false, maxRetries: 0, baseDelayMs: 0 }, stream: { maxRetries: 0, transport: "sse", cacheRetention: "none" }, compaction: { enabled: false, reserveTokens: 80, keepRecentTokens: 0, backgroundTokens: 0 } };
  const fixedNow = () => 1234567890, entered = deferred(), settled = deferred();
  let old, fresh, phase = "old-open", oldEnvelope, oldEnvelopeKey, oldSignal, oldCheckpointKey;
  const cycles = [], originalOpen = nodeSqlite.openNodeSqliteDatabase;
  function code(failure, expected) { return Object.getOwnPropertyDescriptor(failure, "code")?.value === expected; }
  async function missing(ledger, id) { await assert.rejects(ledger.observe(id), error => code(error, "attempt-missing")); }
  async function projection(cycle) {
    const ledger = cycle.ledger;
    let a1 = null, a2 = null, budget = null;
    for (const [name, id] of [["a1", intent.a1], ["a2", intent.a2]]) {
      try {
        const row = await ledger.observe(id);
        const value = { state: row.state, sendOutcome: row.sendOutcome, outcome: row.result?.outcome ?? null, estimatedCostUnits: row.settlement?.estimatedCostUnits ?? null };
        if (name === "a1") a1 = value; else a2 = value;
      } catch (error) { if (!code(error, "attempt-missing")) throw error; }
    }
    try {
      const row = await ledger.snapshot(intent.logicalTaskId); budget = { calls: row.calls, reservedCostUnits: row.reservedCostUnits, settledCostUnits: row.settledCostUnits, outstanding: row.outstandingAttemptId === intent.a1 || row.outstandingAttemptId === intent.a2 };
    } catch (error) { if (!code(error, "task-missing")) throw error; }
    return { a1, a2, budget };
  }
  async function hold(signal) {
    assert.equal(invoke(aborted, signal, []), false); let listener;
    try {
      state.trace.push("old:held");
      await new Promise((resolve, reject) => {
        listener = () => reject(Error("synthetic held authorizer closed"));
        invoke(add, signal, ["abort", listener, { once: true }]);
        entered.resolve();
        if (invoke(aborted, signal, [])) listener();
      });
    } finally { if (listener) invoke(remove, signal, ["abort", listener]); settled.resolve(); }
  }
  async function createCycle(name) {
    const cycle = { name, storage: null, ledger: null, harness: null, wrapper: null, database: null, envelopes: [], keys: [], signals: [], trueACK: false, closed: false };
    cycles.push(cycle);
    const counts = state.counters[name];
    const nodeFacade = { async openNodeSqliteDatabase(...args) { cycle.database = await invoke(originalOpen, nodeSqlite, args); return cycle.database; } };
    cycle.storage = await ownStorage.createDurableStorageInitializer({ nodeSqlite: nodeFacade, sqlite, path: "/work/database.sqlite", options: { busyTimeoutMs: 1000, walAutoCheckpointPages: 1000 }, verifyOwner: () => true, closeContext: ctx })();
    state.settings.push(cycle.storage.settings);
    cycle.ledger = await ownLedger.createModelAttemptStore({ database: cycle.database, deploymentIdentity: intent.deploymentIdentity, mode: name === "old" ? "create" : "active" })();
    const store = {
      async prepare(...args) { counts.prepare++; state.trace.push(name + ":prepare"); return invoke(cycle.ledger.prepare, cycle.ledger, args); },
      async commitSending(...args) { counts.commitSending++; const receipt = await invoke(cycle.ledger.commitSending, cycle.ledger, args); assert.equal(typeof receipt.committedNow, "boolean"); state.sendingReceipts[name].push(receipt.committedNow); state.trace.push(name + ":commitSending:" + receipt.committedNow); if (receipt.committedNow === true) cycle.trueACK = true; return receipt; },
      async recordResult(...args) { counts.recordResult++; const receipt = await invoke(cycle.ledger.recordResult, cycle.ledger, args); state.trace.push(name + ":recordResult"); return receipt; },
      async settle(...args) { counts.settle++; const receipt = await invoke(cycle.ledger.settle, cycle.ledger, args); state.trace.push(name + ":settle"); return receipt; },
    };
    const actual = { role: "assistant", content: [{ type: "text", text: "synthetic recovered summary" }], api: model.api, provider: model.provider, model: model.id,
      usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: "stop", timestamp: fixedNow() };
    const models = {
      streamSimple() { counts.stream++; throw Error("synthetic stream forbidden"); },
      async completeSimple(given, context, options) {
        counts.complete++; state.trace.push(name + ":completeEntry"); assert.equal(name, "fresh"); assert(cycle.trueACK); assert.equal(options.signal, cycle.signals[0]); assert.equal(options.maxTokens, 64);
        const row = await cycle.ledger.observe(intent.a2); assert.equal(row.state, "sending"); assert.equal(row.sendOutcome, "unknown"); state.trace.push("fresh:sendingObserved"); return actual;
      },
    };
    const rootTask = sdk.defineTask({ name: "rotom.durable.request", version: 1, initial: () => ({ phase: "unused" }), phases: { unused() { state.rootBodyCalls++; throw Error("synthetic root forbidden"); } }, abort() { state.rootBodyCalls++; throw Error("synthetic root forbidden"); } });
    cycle.wrapper = ownRegistry.createDurableReadonlyPhaseModelRegistry({ durable: sdk, rootTask, control: {
      prepare() { state.backendCalls++; throw Error("synthetic backend forbidden"); }, check() { state.backendCalls++; return false; }, execute() { state.backendCalls++; throw Error("synthetic backend forbidden"); },
    }, verifyCurrent: () => true, sourceIdentity: intent.sourceIdentity, registryIdentity: intent.registryIdentity, modelDispatch: { model, models, ai, store, limits: { timeoutMs: 10000, maxEvents: 32 },
      async authorize(envelope, signal) {
        counts.authorize++; state.trace.push(name + ":authorize:" + counts.authorize); assert(Object.isFrozen(envelope)); cycle.envelopes.push(envelope); cycle.keys.push(canonical(envelope)); cycle.signals.push(signal);
        assert.equal(envelope.identity.call_kind, "compaction"); assert.equal(envelope.options.maxTokens, 64); state.normalizedOptions = envelope.options;
        if (name === "old") {
          oldEnvelope = envelope; oldEnvelopeKey = canonical(envelope); oldSignal = signal; state.nativeTaskId = envelope.identity.nativeTaskId;
          assert.equal(envelope.identity.nativeConversationId, state.nativeConversationId);
          if (counts.authorize === (unknownSending ? 3 : 1)) return hold(signal);
        } else {
          state.newSignalDifferent = signal !== oldSignal; state.newEnvelopeDifferent = envelope !== oldEnvelope; state.crossEnvelopeMatched = canonical(envelope) === oldEnvelopeKey;
          assert(state.oldClosed && state.heldSettled && state.oldSignalAborted && state.checkpointMatched && state.beforeResumeZero);
          assert(state.newSignalDifferent && state.newEnvelopeDifferent && state.crossEnvelopeMatched);
          if (unknownSending) { assert.deepEqual(await projection(cycle), state.ledgerBeforeClose); throw Error("synthetic unknown reservation denied"); }
          if (!allowFresh) throw Error("synthetic authority denied");
          assert.deepEqual(state.ledgerFreshPassive, { a1: null, a2: null, budget: null });
          await missing(cycle.ledger, intent.a1);
        }
        return { attemptId: name === "old" ? intent.a1 : intent.a2, taskId: intent.logicalTaskId, phase: "compaction", nativeTaskId: envelope.identity.nativeTaskId, nativeConversationId: envelope.identity.nativeConversationId,
          registryIdentity: intent.registryIdentity, inputIdentity: intent.inputIdentity, policyIdentity: intent.policyIdentity, route: intent.route, budget: intent.budget };
      },
      resultFacts(envelope, message, signal) {
        counts.resultFacts++; state.trace.push(name + ":resultFacts"); assert.equal(message, actual); assert.equal(signal, cycle.signals[0]);
        return { result: { resultRef: intent.resultRef, outcome: "completed", observedRoute: intent.route }, settlement: { usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0 }, estimatedCostUnits: 2 } };
      },
    } });
    const getModel = cycle.wrapper.models.getModel;
    cycle.models = { ...cycle.wrapper.models, getModel(...args) { state.metadataGetModel[name]++; return invoke(getModel, cycle.wrapper.models, args); } };
    cycle.options = { registry: cycle.wrapper.registry, models: cycle.models, settings, now: fixedNow, onReport() { state.reportCalls++; } };
    return cycle;
  }
  function within(cycle) {
    state.withinEnvelopeMatched[cycle.name] = cycle.envelopes.length > 0 && cycle.envelopes.every(item => item === cycle.envelopes[0]) && cycle.keys.every(key => key === cycle.keys[0]) && cycle.envelopes.every(item => canonical(item) === cycle.keys[0]);
    state.sameSignal[cycle.name] = cycle.signals.length > 0 && cycle.signals.every(item => item === cycle.signals[0]);
  }
  function taskView(task, status) {
    assert.equal(task.id, state.nativeTaskId); assert.equal(task.conversationId, state.nativeConversationId); assert.equal(task.kind, "pi.compaction"); assert.equal(task.version, 1); assert.equal(task.abortRequested, false); assert.equal(task.state.status, status);
    assert.equal(task.state.checkpoint.phase, "summarize"); assert.equal(task.state.checkpoint.attempt, 1); assert.equal(task.state.checkpoint.firstKept, state.firstKeptEntryId);
    return { status, phase: task.state.checkpoint.phase, attempt: task.state.checkpoint.attempt };
  }
  try {
    old = await createCycle("old"); old.harness = await sdk.Harness.open(old.storage.storage, old.options, ctx);
    const conversation = await old.harness.root(ctx, { agent: { model: { provider: model.provider, modelId: model.id }, thinkingLevel: "off", tools: [] } }); state.nativeConversationId = conversation.id;
    phase = "history";
    for (const [index, text] of ["synthetic alpha", "synthetic beta"].entries()) {
      const submission = await conversation.submit({ type: "write", requestId: "synthetic-history-" + index, entry: { kind: sdk.UserEntry.kind, model: [{ role: "user", content: text, timestamp: index + 1 }] } }, ctx);
      const record = await submission.wait(ctx); assert.equal(record.id, submission.id); assert.equal(record.conversationId, conversation.id); assert.equal(record.type, "write"); assert.equal(record.status, "done"); assert(Number.isSafeInteger(record.entry) && record.entry > 0); state.historyEntryIds.push(record.entry);
    }
    const history = await conversation.context(ctx); assert.equal(history.head, undefined); assert.equal(history.entries.length, 2); assert(history.entries.every((entry, index) => entry.id === state.historyEntryIds[index] && entry.kind === sdk.UserEntry.kind && entry.head === undefined)); assert.equal(state.counters.old.authorize, 0);
    state.firstKeptEntryId = state.historyEntryIds[1]; phase = "genuine-compact";
    const taskId = await conversation.compact(undefined, ctx); await entered.promise; assert.equal(taskId, state.nativeTaskId);
    const originalTask = await old.harness.getTask(taskId, ctx); state.oldTask = taskView(originalTask, "running"); oldCheckpointKey = canonical(originalTask.state.checkpoint); state.trace.push("old:runningCheckpoint");
    state.ledgerBeforeClose = await projection(old);
    if (unknownSending) assert.deepEqual(state.ledgerBeforeClose, { a1: { state: "sending", sendOutcome: "unknown", outcome: null, estimatedCostUnits: null }, a2: null,
      budget: { calls: 1, reservedCostUnits: "10", settledCostUnits: "0", outstanding: true } });
    else assert.deepEqual(state.ledgerBeforeClose, { a1: null, a2: null, budget: null });
    state.trace.push("old:ledgerObserved"); within(old);
    phase = "old-full-close";
    await Promise.all([old.harness.close(ctx), settled.promise]); old.closed = true; state.oldClosed = true; state.heldSettled = true;
    state.oldSignalAborted = invoke(aborted, oldSignal, []); assert.equal(state.oldSignalAborted, true); state.trace.push("old:closed", "old:heldSettled");
    old.wrapper.close(); old.ledger.close();
    phase = "fresh-storage"; fresh = await createCycle("fresh");
    const surviving = await fresh.storage.storage.task(taskId, ctx); state.freshStoredTask = taskView(surviving, "running"); assert.equal(canonical(surviving.state.checkpoint), oldCheckpointKey); state.trace.push("fresh:storedRunning");
    state.ledgerFreshPassive = await projection(fresh); assert.deepEqual(state.ledgerFreshPassive, state.ledgerBeforeClose);
    phase = "fresh-harness-paused"; fresh.harness = await sdk.Harness.open(fresh.storage.storage, fresh.options, ctx);
    const pending = await fresh.harness.getTask(taskId, ctx); state.freshOpenTask = taskView(pending, "pending"); state.checkpointMatched = canonical(pending.state.checkpoint) === oldCheckpointKey; assert(state.checkpointMatched); state.trace.push("fresh:openedPending");
    const inspection = await fresh.harness.inspect(ctx); assert.equal(inspection.scheduling, "paused");
    const recoveredConversation = await fresh.harness.conversation(state.nativeConversationId, ctx); assert(recoveredConversation); await recoveredConversation.context(ctx); await recoveredConversation.entries({}, 100, undefined, ctx);
    state.beforeResumeZero = Object.values(state.counters.fresh).every(count => count === 0) && state.metadataGetModel.fresh === 0; assert(state.beforeResumeZero); state.trace.push("fresh:passiveZero");
    phase = "explicit-resume"; state.trace.push("fresh:resume"); fresh.harness.resume(); const terminal = await fresh.harness.waitForTask(taskId, ctx); await recoveredConversation.waitForIdle(ctx);
    assert.equal(terminal.id, taskId); assert.equal(terminal.conversationId, state.nativeConversationId); assert.equal(terminal.state.status, "terminal"); state.taskOutcome = terminal.state.outcome.status; state.trace.push("fresh:taskTerminal");
    if (allowFresh) {
      assert.equal(state.taskOutcome, "completed"); assert.equal(terminal.state.outcome.result.entryId, undefined); const id = terminal.state.outcome.result.submissionId; assert(Number.isSafeInteger(id) && id > 0);
      const submission = await fresh.harness.submission(id, ctx); assert(submission); const record = await submission.status(ctx); assert.equal(record.id, id); assert.equal(submission.id, id); assert.equal(record.type, "write"); assert.equal(record.status, "done"); assert.equal(record.conversationId, state.nativeConversationId); assert(Number.isSafeInteger(record.entry) && record.entry > 0);
      state.summarySubmissionId = id; state.summaryEntryId = record.entry;
      const entries = await recoveredConversation.entries({}, 100, undefined, ctx), summary = entries.items.find(entry => entry.id === record.entry); assert(summary); state.summaryHeadEntryId = summary.head;
      state.summaryMatched = summary.kind === sdk.CompactionEntry.kind && summary.head === state.firstKeptEntryId && summary.model?.some(message => message.role === "user" && message.content?.some(block => block.type === "text" && block.text === "The conversation history before this point was compacted into the following summary:\n\n<summary>\nsynthetic recovered summary\n</summary>"));
      assert(state.summaryMatched);
    } else { assert.equal(state.taskOutcome, "faulted"); state.errorMatched = terminal.state.outcome.error.message === "dispatch-unknown"; assert(state.errorMatched); }
    within(fresh); assert(Object.values(state.withinEnvelopeMatched).every(Boolean) && Object.values(state.sameSignal).every(Boolean));
    state.ledgerFinal = await projection(fresh); state.trace.push("fresh:ledgerObserved");
    phase = "fresh-close"; await fresh.harness.close(ctx); fresh.closed = true; fresh.wrapper.close(); fresh.ledger.close(); state.closed = true; state.trace.push("fresh:closed");
    assert.equal(state.rootBodyCalls, 0); assert.equal(state.backendCalls, 0); assert.equal(state.reportCalls, 0);
    phase = "publish"; const raw = canonical(state) + "\n"; assert(Buffer.byteLength(raw) <= 65536);
    const file = await open("/work/state.json", "wx", 0o600); try { await file.writeFile(raw); await file.sync(); } finally { await file.close(); } process.stdout.write(raw);
  } catch {
    // cleanup 只尝试捕获的本周期资源；失败不输出原 SDK/SQL/路径/正文。
    for (const cycle of [...cycles].reverse()) {
      if (cycle.closed) continue;
      try { if (cycle.harness) await cycle.harness.close(ctx); else await cycle.storage?.close(); } catch {}
      try { cycle.wrapper?.close(); cycle.ledger?.close(); } catch {}
    }
    process.stderr.write("durable summary recovery worker failed stage=" + phase + "\n"); process.exitCode = 2;
  }
}
void main().catch(() => { process.stderr.write("durable summary recovery worker failed stage=guest-preflight\n"); process.exitCode = 2; });
