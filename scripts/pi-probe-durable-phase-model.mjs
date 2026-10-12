// 只在另行明确授权的 guest 中运行；默认 Python 测试不得 import 本 worker。
import assert from "node:assert/strict";
import { open, readFile } from "node:fs/promises";

const invoke = Reflect.apply;
async function main() {
  const cases = ["generation-success", "generation-denied", "generation-error-no-retry", "compaction-success", "compaction-denied", "compaction-error-no-retry", "generation-lost-sending-ack", "generation-replayed-sending-ack"];
  const selected = process.argv[3];
  assert.equal(process.argv.length, 4); assert.equal(process.argv[2], "--native-durable-phase-model-worker"); assert(cases.includes(selected));
  assert.equal(process.env.PI_DURABLE_PHASE_MODEL_NATIVE, "1"); assert.equal(process.version, "v24.14.0"); process.umask(0o077);
  // 固定 guest 参数核验后才加载公开 SDK；无默认第三方加载路径。
  const [sdk, sqlite, nodeSqlite, ai, chordContext] = await Promise.all([
    import("@earendil-works/pi-durable"), import("@earendil-works/pi-durable/storage/sqlite"),
    import("@earendil-works/pi-durable/storage/sqlite/node"), import("@earendil-works/pi-ai"), import("@earendil-works/chord/context"),
  ]);
  const ctx = chordContext.BACKGROUND_CONTEXT;
  const [{ canonicalProbeJson }, { createDurableStorageInitializer }, { createModelAttemptStore }, { createDurableReadonlyPhaseModelRegistry }] = await Promise.all([
    import("/probe/json.mjs"), import("/probe/storage.ts"), import("/probe/model-attempts.ts"), import("/probe/registry.ts"),
  ]);
  const compaction = selected.startsWith("compaction"), denied = selected.endsWith("denied"), modelError = selected.endsWith("error-no-retry"), lost = selected.endsWith("lost-sending-ack"), replay = selected.endsWith("replayed-sending-ack");
  const versions = { durable: JSON.parse(await readFile("/durable/package.json", "utf8")).version,
    chord: JSON.parse(await readFile("/candidate/node_modules/@earendil-works/chord/package.json", "utf8")).version,
    pi_ai: JSON.parse(await readFile("/candidate/node_modules/@earendil-works/pi-ai/package.json", "utf8")).version, node: process.versions.node };
  assert.deepEqual(versions, { durable: "1.0.1", chord: "1.0.2", pi_ai: "1.0.2", node: "24.14.0" });
  const state = { schema: 1, case: selected, versions, nativeStarted: true, phase: "complete", settings: null,
    nativeTaskId: null, nativeConversationId: null, nativeTaskKind: null, nativeTaskStatus: null, nativeTaskOutcome: null, errorReason: null, resultBindingsMatched: false, nativeResultEntryId: null, answerEntryId: null, nativeResultSubmissionId: null, summaryEntryId: null, historyWrites: 0, historyEntryIds: [], selectedFirstKeptEntryId: null, summaryHeadEntryId: null, nativeIdentity: null, observedCheckpoint: null,
    metadataGetModel: 0, counters: { authorize: 0, prepare: 0, commitSending: 0, stream: 0, complete: 0, resultFacts: 0, recordResult: 0, settle: 0 },
    sendingReceipts: [], trace: [], envelopeMatched: false, sameSignal: false, normalizedOptions: null, cap: null,
    ledger: null, ledgerReadSources: [], summaryObserved: false, submissionStatus: null, sanitizedErrorObserved: false,
    runtimeReference: "unknown", chordContextReference: "unknown", rootBodyCalls: 0, backendCalls: 0, modelBodyFailed: false, reportCalls: 0, closed: false };
  const model = { provider: "synthetic.invalid", id: "synthetic-model", name: "Synthetic", api: "openai-completions", baseUrl: "https://synthetic.invalid", reasoning: false,
    input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 8192, maxTokens: 64 };
  const attemptId = "synthetic-attempt-" + selected, logicalTaskId = "synthetic-logical-" + selected, scopeId = "synthetic-scope-" + selected;
  let storage, harness, ledger, wrapper, database, originalSignal, phase = "storage";
  const envelopes = [], envelopeKeys = [], signals = [];
  let trueACK = false;
  const actual = { role: "assistant", content: modelError ? [] : [{ type: "text", text: compaction ? "synthetic summary" : "synthetic answer" }], api: model.api, provider: model.provider, model: model.id,
    usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
    stopReason: modelError ? "error" : "stop", timestamp: 1, ...(modelError ? { errorMessage: "503 synthetic failure" } : {}) };
  async function observedSending() {
    const row = await ledger.observe(attemptId); state.ledgerReadSources.push("model-body"); assert.equal(row.state, "sending"); assert.equal(row.sendOutcome, "unknown"); state.trace.push("sendingObserved");
  }
  const models = {
    streamSimple(given, context, options) {
      // 第一同步步骤计原入口，不能把等待账本后的数量冒作入口数。
      state.counters.stream++; state.trace.push("streamEntry"); assert(trueACK); assert.equal(options.maxTokens, 64); assert.equal(options.signal, originalSignal);
      const stream = ai.createAssistantMessageEventStream();
      void (async () => { await observedSending(); stream.push(modelError ? { type: "error", reason: "error", error: actual } : { type: "done", reason: "stop", message: actual }); stream.end(actual); })()
        .catch(() => { state.modelBodyFailed = true; const failure = { ...actual, content: [], stopReason: "error", errorMessage: "synthetic-model-body-failed" }; stream.push({ type: "error", reason: "error", error: failure }); stream.end(failure); });
      return stream;
    },
    async completeSimple(given, context, options) {
      state.counters.complete++; state.trace.push("completeEntry"); assert(trueACK); assert.equal(options.maxTokens, 64); assert.equal(options.cacheRetention, "none"); assert.equal(options.signal, originalSignal);
      await observedSending(); return actual;
    },
  };
  try {
    const originalOpen = nodeSqlite.openNodeSqliteDatabase;
    const selectedNodeSqlite = { async openNodeSqliteDatabase(...args) { database = await invoke(originalOpen, nodeSqlite, args); return database; } };
    storage = await createDurableStorageInitializer({ nodeSqlite: selectedNodeSqlite, sqlite, path: "/work/database.sqlite", options: { busyTimeoutMs: 1000, walAutoCheckpointPages: 1000 }, verifyOwner: () => true, closeContext: ctx })();
    state.settings = storage.settings; phase = "ledger";
    ledger = await createModelAttemptStore({ database, deploymentIdentity: "a".repeat(64), mode: "create" })();
    const store = {
      async prepare(...args) { state.counters.prepare++; state.trace.push("prepare"); return invoke(ledger.prepare, ledger, args); },
      async commitSending(...args) {
        async function original() {
          state.counters.commitSending++; const receipt = await invoke(ledger.commitSending, ledger, args);
          state.sendingReceipts.push(receipt.committedNow); state.trace.push("commitSending:" + receipt.committedNow); if (receipt.committedNow === true) trueACK = true; return receipt;
        }
        const receipt = await original(); if (lost) throw Error("synthetic lost ACK"); if (replay) return original(); return receipt;
      },
      async recordResult(...args) { state.counters.recordResult++; const receipt = await invoke(ledger.recordResult, ledger, args); state.trace.push("recordResult"); return receipt; },
      async settle(...args) { state.counters.settle++; const receipt = await invoke(ledger.settle, ledger, args); state.trace.push("settle"); return receipt; },
    };
    const rootTask = sdk.defineTask({ name: "rotom.durable.request", version: 1, initial: () => ({ phase: "unused" }),
      phases: { unused() { state.rootBodyCalls++; throw Error("synthetic root forbidden"); } }, abort() { state.rootBodyCalls++; throw Error("synthetic root forbidden"); } });
    phase = "registry";
    wrapper = createDurableReadonlyPhaseModelRegistry({ durable: sdk, rootTask, control: {
      prepare() { state.backendCalls++; throw Error("synthetic backend forbidden"); }, check() { state.backendCalls++; return false; }, execute() { state.backendCalls++; throw Error("synthetic backend forbidden"); },
    }, verifyCurrent: () => true, sourceIdentity: "a".repeat(64), registryIdentity: "b".repeat(64), modelDispatch: { models, ai, store, model, limits: { timeoutMs: 10000, maxEvents: 32 },
      async authorize(envelope, signal) {
        state.counters.authorize++; state.trace.push("authorize:" + state.counters.authorize);
        assert(Object.isFrozen(envelope)); envelopes.push(envelope); signals.push(signal); envelopeKeys.push(canonicalProbeJson(envelope));
        if (originalSignal === undefined) originalSignal = signal; assert.equal(signal, originalSignal);
        state.nativeIdentity = envelope.identity; state.nativeTaskId = envelope.identity.nativeTaskId; state.nativeConversationId = envelope.identity.nativeConversationId;
        state.normalizedOptions = envelope.options; state.cap = envelope.options.maxTokens;
        const task = await harness.getTask(state.nativeTaskId, ctx); assert(task); assert.equal(task.id, state.nativeTaskId); assert.equal(task.conversationId, state.nativeConversationId);
        state.observedCheckpoint = { phase: task.state.checkpoint.phase, attempt: task.state.checkpoint.attempt };
        if (compaction) { assert.equal(task.state.checkpoint.firstKept, state.historyEntryIds[1]); state.selectedFirstKeptEntryId = task.state.checkpoint.firstKept; }
        if (denied) throw Error("synthetic authority denied");
        return { attemptId, taskId: logicalTaskId, phase: compaction ? "compaction" : "generation", nativeTaskId: envelope.identity.nativeTaskId, nativeConversationId: envelope.identity.nativeConversationId,
          registryIdentity: "b".repeat(64), inputIdentity: "c".repeat(64), policyIdentity: "d".repeat(64), route: { provider: model.provider, model: model.id }, budget: { scopeId, maxCalls: 1, maxCostUnits: 20, reservationUnits: 10 } };
      },
      resultFacts(envelope, message, signal) {
        state.counters.resultFacts++; state.trace.push("resultFacts"); assert.equal(message, actual); assert.equal(signal, originalSignal);
        return { result: { resultRef: "e".repeat(64), outcome: modelError ? "failed" : "completed", observedRoute: { provider: model.provider, model: model.id } }, settlement: { usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0 }, estimatedCostUnits: 2 } };
      },
    } });
    const originalGetModel = wrapper.models.getModel;
    const harnessModels = { ...wrapper.models, getModel(...args) { state.metadataGetModel++; return invoke(originalGetModel, wrapper.models, args); } };
    phase = "harness-open";
    harness = await sdk.Harness.open(storage.storage, { registry: wrapper.registry, models: harnessModels,
      settings: { retry: { enabled: false, maxRetries: 0, baseDelayMs: 0 }, stream: { maxRetries: 0, transport: "sse", timeoutMs: 1000, cacheRetention: "none" }, compaction: { enabled: false, backgroundTokens: 0, reserveTokens: 80, keepRecentTokens: 0 } }, onReport() { state.reportCalls++; } }, ctx);
    const conversation = await harness.root(ctx, { agent: { model: { provider: model.provider, modelId: model.id }, thinkingLevel: "off", tools: [] } });
    state.nativeConversationId = conversation.id;
    phase = "public-trigger";
    let submission, taskId;
    if (compaction) {
      for (const [index, text] of ["synthetic alpha", "synthetic beta"].entries()) {
        const write = await conversation.submit({ type: "write", requestId: "synthetic-history-" + selected + "-" + index,
          entry: { kind: sdk.UserEntry.kind, model: [{ role: "user", content: text, timestamp: index + 1 }] } }, ctx);
        const record = await write.wait(ctx); assert.equal(record.id, write.id); assert.equal(record.type, "write"); assert.equal(record.status, "done"); assert(Number.isSafeInteger(record.entry) && record.entry > 0);
        state.historyWrites++; state.historyEntryIds.push(record.entry);
      }
      const history = await conversation.context(ctx); assert.equal(history.head, undefined); assert.equal(history.entries.length, 2);
      assert(history.entries.every((entry, index) => entry.id === state.historyEntryIds[index] && entry.kind === sdk.UserEntry.kind && entry.head === undefined)); assert.equal(state.counters.authorize, 0);
      taskId = await conversation.compact(undefined, ctx);
    } else {
      submission = await conversation.submit({ type: "input", requestId: "synthetic-request-" + selected, content: "synthetic request", whenBusy: "reject" }, ctx);
      await submission.wait(ctx); taskId = state.nativeTaskId; assert(Number.isSafeInteger(taskId) && taskId > 0);
    }
    phase = "task-terminal";
    const task = await harness.waitForTask(taskId, ctx); assert.equal(task.id, state.nativeTaskId); assert.equal(task.conversationId, conversation.id);
    state.nativeTaskKind = task.kind; state.nativeTaskStatus = task.state.status; state.nativeTaskOutcome = task.state.outcome.status;
    state.trace.push("taskTerminal"); await conversation.waitForIdle(ctx); assert.equal((await harness.inspect(ctx)).tasks.length, 0);
    if (submission) {
      const record = await submission.status(ctx); assert.equal(record.id, submission.id); assert.equal(record.conversationId, conversation.id); state.submissionStatus = record.status;
      if (task.state.outcome.status === "completed") {
        const entryId = task.state.outcome.result.entryId; assert(Number.isSafeInteger(entryId) && entryId > 0); assert.equal(record.status, "done"); assert.equal(record.answer, entryId);
        state.nativeResultEntryId = entryId; state.answerEntryId = record.answer;
      } else { assert.equal(record.status, "unanswered"); assert.equal(record.reason, "model_error"); assert.equal(task.state.outcome.error.detail.reason, "model_error"); state.errorReason = record.reason; }
      state.resultBindingsMatched = true;
    } else if (task.state.outcome.status === "completed") {
      const id = task.state.outcome.result.submissionId; assert(Number.isSafeInteger(id) && id > 0); assert.equal(task.state.outcome.result.entryId, undefined);
      const write = await harness.submission(id, ctx); assert(write); const record = await write.status(ctx); assert.equal(record.id, id); assert.equal(record.conversationId, conversation.id); assert.equal(record.type, "write"); assert.equal(record.status, "done"); assert(Number.isSafeInteger(record.entry) && record.entry > 0);
      state.nativeResultSubmissionId = id; state.summaryEntryId = record.entry; state.resultBindingsMatched = true;
    } else {
      if (denied) { assert.equal(task.state.outcome.status, "faulted"); assert.equal(task.state.outcome.error.message, "dispatch-unknown"); }
      else { assert.equal(task.state.outcome.status, "failed"); assert.equal(task.state.outcome.error.detail.reason, "model_error"); state.errorReason = "model_error"; }
      state.resultBindingsMatched = true;
    }
    const page = await conversation.entries({}, 100, undefined, ctx);
    if (compaction && !denied && !modelError) {
      const summary = page.items.find(entry => entry.id === state.summaryEntryId); assert(summary); state.summaryHeadEntryId = summary.head; assert.equal(summary.head, state.historyEntryIds[1]);
      state.summaryObserved = page.items.some(entry => entry.id === state.summaryEntryId && entry.kind === sdk.CompactionEntry.kind && entry.model?.some(message => message.role === "user" && Array.isArray(message.content) && message.content.some(block => block.type === "text" && block.text === "The conversation history before this point was compacted into the following summary:\n\n<summary>\nsynthetic summary\n</summary>")));
    }
    if (!compaction && (denied || modelError || lost || replay)) state.sanitizedErrorObserved = page.items.some(entry => entry.conversationId === conversation.id && entry.byTaskId === state.nativeTaskId && entry.kind === sdk.AssistantEntry.kind && entry.model?.some(message => message.errorMessage === "dispatch-unknown"));
    if (compaction && (denied || modelError)) state.sanitizedErrorObserved = task.state.outcome.error.message.includes("dispatch-unknown");
    state.envelopeMatched = envelopes.length === state.counters.authorize && envelopes.length > 0 && envelopes.every(value => value === envelopes[0]) && envelopeKeys.every(value => value === envelopeKeys[0]) && envelopes.every(value => canonicalProbeJson(value) === envelopeKeys[0]);
    state.sameSignal = signals.length > 0 && signals.every(value => value === originalSignal);
    phase = "ledger-final";
    if (denied) { await assert.rejects(ledger.observe(attemptId), failure => Object.getOwnPropertyDescriptor(failure, "code")?.value === "attempt-missing"); state.ledgerReadSources.push("final-absent"); }
    else {
      const row = await ledger.observe(attemptId), budget = await ledger.snapshot(logicalTaskId); state.ledgerReadSources.push("final");
      state.ledger = { state: row.state, sendOutcome: row.sendOutcome, resultOutcome: row.result?.outcome ?? null, estimatedCostUnits: row.settlement?.estimatedCostUnits ?? null,
        reservedCostUnits: budget.reservedCostUnits, settledCostUnits: budget.settledCostUnits, calls: budget.calls, outstanding: budget.outstandingAttemptId === attemptId };
    }
    assert.equal(state.rootBodyCalls, 0); assert.equal(state.backendCalls, 0); assert.equal(state.modelBodyFailed, false); assert.equal(state.reportCalls, 0); assert(state.envelopeMatched && state.sameSignal);
    phase = "cleanup"; wrapper.close(); ledger.close(); await harness.close(ctx); state.closed = true;
    phase = "publish"; const raw = canonicalProbeJson(state) + "\n"; assert(Buffer.byteLength(raw) <= 65536); const output = await open("/work/state.json", "wx", 0o600); try { await output.writeFile(raw); await output.sync(); } finally { await output.close(); } process.stdout.write(raw);
  } catch {
    // 仅固定自有阶段，原 SDK/SQL/路径/正文不进错误输出。
    try { wrapper?.close(); ledger?.close(); if (harness) await harness.close(ctx); else await storage?.close(); } catch {}
    process.stderr.write("durable phase model worker failed stage=" + phase + "\n"); process.exitCode = 2;
  }

}
void main().catch(() => { process.stderr.write("durable phase model worker failed stage=guest-preflight\n"); process.exitCode = 2; });
