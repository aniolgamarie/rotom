// 仅显式授权后在固定断网 namespace 运行；本文件不在默认测试中 import。
import assert from "node:assert/strict";
import { types } from "node:util";
import { writeFile, readFile } from "node:fs/promises";
import * as sdk from "@earendil-works/pi-durable";
import * as sqlite from "@earendil-works/pi-durable/storage/sqlite";
import * as nodeSqlite from "@earendil-works/pi-durable/storage/sqlite/node";
import * as chord from "@earendil-works/chord";
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { canonicalProbeJson } from "/probe/json.mjs";
import { createDurableStorageInitializer } from "/probe/storage.ts";
import { createDurableRequestAdmission } from "/probe/requests.ts";

process.umask(0o077);
const cases = ["normal", "concurrent-conflicts", "lost-submit-ack", "lost-initialize-ack", "active-missing", "old-sentinel", "late-close"];
const selected = process.argv[3];
assert.equal(process.argv.length, 4); assert.equal(process.argv[2], "--native-durable-admission-worker"); assert(cases.includes(selected));
assert.equal(process.env.PI_DURABLE_ADMISSION_NATIVE, "1"); assert.equal(process.version, "v24.14.0");
const context = BACKGROUND_CONTEXT;
const versions = { durable: JSON.parse(await readFile("/durable/package.json", "utf8")).version,
  chord: JSON.parse(await readFile("/candidate/node_modules/@earendil-works/chord/package.json", "utf8")).version,
  pi_ai: JSON.parse(await readFile("/candidate/node_modules/@earendil-works/pi-ai/package.json", "utf8")).version, node: process.versions.node };
assert.deepEqual(versions, { durable: "1.0.1", chord: "1.0.2", pi_ai: "1.0.2", node: "24.14.0" });
const request = { requestId: "synthetic-request-1", input: { text: "Synthetic admission only" },
  grant: Object.fromEntries(["sourceIdentity", "authorizationIdentity", "registryIdentity", "policyIdentity", "readCapabilityIdentity", "inputSnapshotIdentity", "artifactIdentity"].map(key => [key, (key === "registryIdentity" ? "b" : "c").repeat(64)])),
  route: { provider: "synthetic.invalid", model: "synthetic-no-model" }, budget: { scopeId: "synthetic-scope", maxCalls: 2, maxCostUnits: 30 } };
const state = { schema: 1, case: selected, nativeStarted: true, versions, seedBatches: 0, seedConversationId: null,
  componentCommits: 0, taskWrites: 0, taskBatches: 0, nativeTaskIds: [], batchTypes: [], rowCount: 0,
  nativeProxyObserved: false, sameBatch: false, frozenReceipt: false, accepted: false, submitRejected: false,
  initializeRejected: false, resubmitBlocked: false, lookupNativeTaskId: null, recordNativeTaskId: null,
  persistentDocMatched: false, docBound: false, sentinelUnchanged: false, conflictsRejected: 0, bodyCalls: 0, settings: null, closed: false };
let initialized, originalSession, admission, token, seed = true, inserted = false;
// 诊断仅使用自有固定阶段名，绝不包含 SDK 异常、正文、路径或原始 ID。
let phase = "storage-initialize";
function fixedFailure(failure) { assert(["recovery-required", "store-exists"].includes(Object.getOwnPropertyDescriptor(failure, "code")?.value)); }
async function rejected(call) { await assert.rejects(call, failure => { fixedFailure(failure); return true; }); }
try {
  initialized = await createDurableStorageInitializer({ nodeSqlite, sqlite, path: "/work/database.sqlite", options: { busyTimeoutMs: 1000, walAutoCheckpointPages: 1000 }, verifyOwner: () => true, closeContext: context })();
  state.settings = initialized.settings;
  const originalStorage = initialized.storage;
  // 只选公开 methods，固定 original receiver；不修改 SDK 对象或原型。
  const storageFacade = Object.create(null);
  for (const name of ["mintId", "conversation", "task", "findDocument", "document"]) {
    const captured = originalStorage[name]; storageFacade[name] = (...args) => captured.apply(originalStorage, args);
  }
  const originalCommit = originalStorage.commit;
  storageFacade.commit = async (writes, ctx) => {
    const types = writes.map(write => write.type);
    const tasks = writes.filter(write => write.type === "task");
    const receipt = await originalCommit.call(originalStorage, writes, ctx);
    if (seed) { state.seedBatches++; }
    else {
      state.batchTypes.push(types); state.taskWrites += tasks.length;
      if (tasks.length) { state.taskBatches++; state.nativeTaskIds.push(...tasks.map(write => write.value.id));
        state.sameBatch = types.includes("document.change") || types.includes("document.create"); }
    }
    return receipt;
  };
  storageFacade.close = () => initialized.close();
  phase = "session-create";
  originalSession = sdk.createSession(storageFacade);
  phase = "conversation-seed";
  const conversation = await originalSession.commit(tx => tx.createConversation({ ownership: { kind: "ownerless" } }), context);
  state.seedConversationId = conversation.id; assert(Number.isSafeInteger(conversation.id) && conversation.id > 0); seed = false;
  phase = "task-token";
  const rootTask = sdk.defineTask({ name: "rotom.durable.request", version: 1, initial: () => ({ phase: "synthetic" }),
    phases: { async synthetic(_task, runtime, ctx) { state.bodyCalls++; await runtime.commit(() => ({ status: "terminal", outcome: { status: "completed", result: { synthetic: true } } }), ctx); } },
    async abort(_task, runtime, ctx) { state.bodyCalls++; await runtime.commit(() => ({ status: "terminal", outcome: { status: "aborted" } }), ctx); } });
  const originalSessionCommit = originalSession.commit, originalSnapshot = originalSession.snapshot, originalTask = originalStorage.task;
  const facade = {
    async commit(callback, ctx) {
      state.componentCommits++;
      const result = await originalSessionCommit.call(originalSession, async tx => {
        const doc = tx.doc, task = tx.task, createTask = tx.createTask;
        return callback({ async doc(...args) { const draft = await doc.apply(tx, args); state.nativeProxyObserved ||= types.isProxy(draft); return draft; },
          task: (...args) => task.apply(tx, args), createTask: (...args) => createTask.apply(tx, args) });
      }, ctx);
      if (selected === "lost-initialize-ack" && state.componentCommits === 1) throw Error("synthetic lost initialize acknowledgment");
      if (selected === "lost-submit-ack" && state.componentCommits === 2) throw Error("synthetic lost submit acknowledgment");
      if (selected === "late-close" && state.componentCommits === 2) admission.close();
      return result;
    },
    async snapshot(doc, ctx) {
      const value = await originalSnapshot.call(originalSession, doc, ctx);
      if (selected === "old-sentinel" && value === undefined && !inserted) {
        inserted = true; await originalSessionCommit.call(originalSession, tx => tx.doc(doc), ctx);
      }
      return value;
    },
    getTask: (id, ctx) => originalTask.call(originalStorage, id, ctx),
  };
  const durableFacade = { defineDoc(definition) { token = sdk.defineDoc(definition); return token; } };
  phase = "admission-create";
  admission = createDurableRequestAdmission({ session: facade, durable: durableFacade, chord, rootTask, context,
    mode: selected === "active-missing" ? "active" : "create", verifyCurrent: () => true, deploymentIdentity: "a".repeat(64), registryIdentity: "b".repeat(64), conversationId: conversation.id });
  phase = "admission-initialize";
  if (["active-missing", "old-sentinel", "lost-initialize-ack"].includes(selected)) {
    await rejected(admission.initialize()); state.initializeRejected = true;
    if (selected === "lost-initialize-ack") { await rejected(admission.initialize()); await rejected(admission.submit(request)); state.resubmitBlocked = true; assert.equal(await admission.lookup(request), null); }
  } else {
    await admission.initialize();
    phase = "admission-submit";
    if (["lost-submit-ack", "late-close"].includes(selected)) {
      await rejected(admission.submit(request)); state.submitRejected = true;
      phase = "admission-lookup";
      const found = await admission.lookup(request); state.lookupNativeTaskId = found.nativeTaskId;
      phase = "resubmit-deny";
      await rejected(admission.submit({ ...request, requestId: "synthetic-new" })); state.resubmitBlocked = true;
    } else {
      const receipts = selected === "concurrent-conflicts" ? await Promise.all(Array.from({ length: 12 }, () => admission.submit(request))) : [await admission.submit(request)];
      const receipt = receipts[0]; assert(receipts.every(value => value.nativeTaskId === receipt.nativeTaskId)); state.frozenReceipt = receipts.every(Object.isFrozen); state.accepted = true;
      phase = "admission-lookup";
      state.lookupNativeTaskId = (await admission.lookup(request)).nativeTaskId;
      phase = "conflicts-deny";
      if (selected === "concurrent-conflicts") {
        for (const mutate of [value => value.input.text += "changed", value => value.route.model += "changed", value => value.grant.policyIdentity = "d".repeat(64), value => value.budget.maxCostUnits++]) {
          const conflicting = structuredClone(request); mutate(conflicting);
          await assert.rejects(admission.submit(conflicting), failure => Object.getOwnPropertyDescriptor(failure, "code")?.value === "request-conflict"); state.conflictsRejected++;
        }
      }
    }
  }
  phase = "document-snapshot";
  const snapshot = await originalSnapshot.call(originalSession, token, context);
  phase = "document-address";
  const persistentRecord = await originalStorage.findDocument({ kind: "rotom.durable.requests", scope: { kind: "session" } }, "current", context);
  phase = "document-materialize";
  const persistent = persistentRecord === undefined ? undefined : await originalStorage.document(persistentRecord.id, "current", context);
  phase = "document-compare";
  assert.equal(persistent === undefined, snapshot === undefined);
  if (persistent !== undefined) assert.equal(canonicalProbeJson(chord.copyJson(persistent.value)), canonicalProbeJson(chord.copyJson(snapshot)));
  state.persistentDocMatched = true;
  phase = "document-observations";
  if (snapshot !== undefined) {
    const own = chord.copyJson(snapshot); state.rowCount = own.rows.length;
    state.docBound = own.deploymentIdentity === "a".repeat(64) && own.registryIdentity === "b".repeat(64) && own.conversationId === conversation.id;
    state.sentinelUnchanged = own.schema === 1 && own.deploymentIdentity === null && own.registryIdentity === null && own.conversationId === null && own.rows.length === 0;
    if (own.rows.length) {
      state.recordNativeTaskId = own.rows[0].nativeTaskId;
      phase = "task-readback";
      const native = await originalTask.call(originalStorage, own.rows[0].nativeTaskId, context);
      assert.equal(native.id, state.lookupNativeTaskId); assert.equal(native.kind, "rotom.durable.request"); assert.equal(native.version, 1);
      assert.equal(native.state.status, "pending"); assert.equal(native.background, false); assert.equal(Object.hasOwn(native, "owner"), false);
      assert.equal(native.conversationId, conversation.id); assert.deepEqual(chord.copyJson(native.input.request), chord.copyJson(request));
      assert.equal(native.input.taskId, own.rows[0].taskId); assert.equal(native.input.inputIdentity, own.rows[0].inputIdentity);
    }
  }
  assert.equal(state.bodyCalls, 0);
  phase = "session-close";
  admission.close(); await originalSession.close(context); state.closed = true;
  phase = "state-write";
  await writeFile("/work/state.json", JSON.stringify(state) + "\n", { flag: "wx", mode: 0o600 });
  process.stdout.write(JSON.stringify(state) + "\n");
} catch {
  // 不外泄原始 SDK 错误、SQL、路径或请求；保留父进程捕获的固定失败。
  process.stderr.write("durable-admission-worker-failed:" + phase + "\n"); process.exitCode = 1;
} finally {
  if (initialized) { try { await initialized.close(); } catch { process.stderr.write("durable-admission-cleanup-unknown\n"); process.exitCode = 1; } }
}
