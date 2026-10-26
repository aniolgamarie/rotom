import { randomBytes } from "node:crypto";
import path from "node:path";

// 测试原型的启动归属与观察通道；匹配元数据仍不代表严格恢复已提交。
const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const text = value => typeof value === "string" && value.trim().length > 0 && value.length <= 4096 && !value.includes("\0");
const exact = (value, keys) => object(value) && Object.keys(value).sort().join("\0") === [...keys].sort().join("\0");
const integer = value => Number.isSafeInteger(value) && value > 0;
const freeze = value => {
  if (object(value) || Array.isArray(value)) {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
};
const invalid = () => { throw Error("invalid resume probe request"); };

export function createAttempt(target, { onChange = () => {} } = {}) {
  if (!exact(target, ["sessionRef", "cwd", "scope", "profile", "runtimeIdentity", "previousRunId"])
      || !exact(target.sessionRef, ["agent", "backend", "native_home_ref", "native_ref"])
      || target.sessionRef.agent !== "dsh" || target.sessionRef.backend !== "dsh"
      || !Object.values(target.sessionRef).every(text)
      || ![target.cwd, target.scope, target.profile, target.runtimeIdentity, target.previousRunId].every(text)
      || !path.isAbsolute(target.cwd)) invalid();
  const request = freeze({ version: 1, ...structuredClone(target),
    run_id: randomBytes(16).toString("hex"), nonce: randomBytes(32).toString("hex") });
  let state = freeze({ kind: "waiting", reason: "no-observation" });
  let child;
  let closed = false;
  let rejected = false;
  let epoch;
  let sequence = 0;
  let lastMessage;
  let lastObservation;
  let observerEpoch;
  let observerSequence = 0;

  function publish(value) {
    state = freeze(value);
    try { Promise.resolve(onChange(state)).catch(() => {}); } catch { /* 不回显消费者异常。 */ }
  }
  function detach() {
    if (!child) return;
    for (const [event, listener] of [["message", receive], ["disconnect", lost], ["exit", lost], ["error", lost]]) {
      child.removeListener(event, listener);
    }
  }
  function reject(reason) {
    if (closed || rejected) return;
    rejected = true;
    detach();
    publish({ kind: "unknown", reason });
  }
  function lost() { reject("observation-channel-lost"); }
  function receive(message) {
    if (closed || rejected) return;
    if (!exact(message, ["version", "run_id", "nonce", "emitter_epoch", "sequence", "observation"])
        || message.version !== 1 || message.run_id !== request.run_id || message.nonce !== request.nonce
        || typeof message.emitter_epoch !== "string" || !/^[a-f0-9]{32}$/.test(message.emitter_epoch)
        || !integer(message.sequence)) { reject("invalid-envelope"); return; }
    let signature;
    try { signature = JSON.stringify(message); } catch { reject("invalid-envelope"); return; }
    if (signature.length > 16384) { reject("invalid-envelope"); return; }
    if (message.sequence === sequence && signature === lastMessage) return;
    if ((epoch !== undefined && epoch !== message.emitter_epoch) || message.sequence !== sequence + 1) {
      reject("observation-sequence-conflict"); return;
    }
    epoch = message.emitter_epoch;
    sequence = message.sequence;
    lastMessage = signature;
    const value = message.observation;
    if (!object(value)) { reject("invalid-observation"); return; }
    if (value.kind === "unknown") { reject("host-observation-unavailable"); return; }
    if (!integer(value.observer_epoch) || !integer(value.observer_sequence)
        || (observerEpoch !== undefined && value.observer_epoch !== observerEpoch)
        || value.observer_sequence !== observerSequence + 1) {
      reject("observer-sequence-conflict"); return;
    }
    observerEpoch = value.observer_epoch;
    observerSequence = value.observer_sequence;
    if (value.kind === "waiting") {
      if (!exact(value, ["kind", "reason", "observer_epoch", "observer_sequence"])
          || value.reason !== "not-ready" || !integer(value.observer_epoch) || !integer(value.observer_sequence)) {
        reject("invalid-observation"); return;
      }
      if (lastObservation) { reject("binding-became-unready"); return; }
      return;
    }
    if (!exact(value, ["kind", "version", "agentBindingGeneration", "status", "sessionRef", "sessionId", "cwd", "observer_epoch", "observer_sequence"])
        || value.kind !== "foreground-observed" || !Number.isSafeInteger(value.version) || value.version < 0
        || !integer(value.agentBindingGeneration) || !["idle", "running", "requires-action"].includes(value.status)
        || !integer(value.observer_epoch) || !integer(value.observer_sequence)
        || !exact(value.sessionRef, ["backendId", "sessionId"])) { reject("invalid-observation"); return; }
    if (value.sessionRef.backendId !== "dsh" || value.sessionRef.sessionId !== request.sessionRef.native_ref
        || value.sessionId !== request.sessionRef.native_ref || value.cwd !== request.cwd) {
      reject("target-mismatch"); return;
    }
    if (lastObservation && (value.observer_epoch !== lastObservation.observer_epoch
        || value.observer_sequence <= lastObservation.observer_sequence
        || value.version < lastObservation.version
        || value.agentBindingGeneration !== lastObservation.agentBindingGeneration
        || (value.version === lastObservation.version && value.status !== lastObservation.status))) {
      reject("binding-changed"); return;
    }
    lastObservation = structuredClone(value);
    // 存储归属只是父进程请求上下文；本原型没有证明官方配置实际使用了这些归属。
    publish({ kind: "foreground-matched", run_id: request.run_id,
      sessionRef: { ...request.sessionRef }, cwd: value.cwd, scope: request.scope,
      profile: request.profile, runtimeIdentity: request.runtimeIdentity,
      binding_source: "parent-request-context", launch_binding: "unproven", native_load: "unproven",
      observation: structuredClone(value) });
  }
  return Object.freeze({
    request,
    snapshot: () => state,
    launch(environment, tuiConfig, args = []) {
      if (!object(environment) || !object(tuiConfig) || !Array.isArray(args) || args.length
          || tuiConfig.backend !== "dsh"
          || (tuiConfig.sessionId !== undefined && tuiConfig.sessionId !== request.sessionRef.native_ref)) invalid();
      const env = { ...environment };
      for (const key of ["DSH_TUI_RESUME_RETRY", "DSH_TUI_BACKEND_HANDOFF", "DSH_TUI_HOST_ENTRY_PATH"]) delete env[key];
      Object.assign(env, { DSH_TUI_BACKEND: "dsh", DSH_TUI_RESUME_BACKEND: "dsh",
        DSH_TUI_RESUME_SESSION: request.sessionRef.native_ref, DSH_TUI_HOST_ENTRY: "0" });
      return freeze({ env, tuiConfig: { ...structuredClone(tuiConfig), backend: "dsh", sessionId: request.sessionRef.native_ref },
        args: [], cwd: request.cwd });
    },
    attach(process) {
      if (child || closed || rejected || !process?.connected || typeof process.send !== "function"
          || typeof process.on !== "function" || typeof process.removeListener !== "function") {
        reject("invalid-observation-channel"); return;
      }
      child = process;
      child.on("message", receive);
      child.on("disconnect", lost);
      child.on("exit", lost);
      child.on("error", lost);
      try { child.send(request, error => { if (error) lost(); }); } catch { lost(); }
    },
    close() {
      if (closed) return;
      detach();
      if (!rejected && state.kind !== "foreground-matched") publish({ kind: "unknown", reason: "closed-before-observation" });
      closed = true;
    },
  });
}

export function createEmitter(request, send) {
  if (!object(request) || !/^[a-f0-9]{32}$/.test(request.run_id) || !/^[a-f0-9]{64}$/.test(request.nonce)
      || typeof send !== "function") invalid();
  const runId = request.run_id;
  const nonce = request.nonce;
  const emitterEpoch = randomBytes(16).toString("hex");
  let sequence = 0;
  return observation => send({ version: 1, run_id: runId, nonce, emitter_epoch: emitterEpoch,
    sequence: ++sequence, observation: structuredClone(observation) });
}
