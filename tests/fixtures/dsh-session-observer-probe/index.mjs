// 隔离原型：只观察公开前台元数据，不证明历史加载、恢复或 writer 排他。
let nextEpoch = 0;
const MAX_ATTEMPTS = 3;
const ACTIVE = new Set(["idle", "running", "requires-action"]);

export function observeBinding(channel, onObservation, { schedule = queueMicrotask } = {}) {
  const epoch = ++nextEpoch;
  let sequence = 0;
  let disposed = false;
  let pending = false;
  let subscriptionFailed = false;
  let unsubscribe;
  let previous;
  let highVersion = -1;
  let highGeneration = -1;
  let inconsistent = false;
  let lastEmission;

  function publish(value) {
    if (disposed) return;
    const signature = JSON.stringify(value);
    if (signature === lastEmission) return;
    lastEmission = signature;
    onObservation(Object.freeze({ ...value, observer_epoch: epoch, observer_sequence: ++sequence }));
  }
  const unknown = reason => publish({ kind: "unknown", reason });

  function sample() {
    const version = channel.version;
    const generation = channel.agentBindingGeneration;
    const ready = channel.ready;
    const failure = channel.startupFailure !== undefined;
    const status = channel.status;
    const ref = channel.sessionRef;
    // 逐字段复制，不持有宿主对象；最后再读一次带 owner 守卫的水位。
    const backendId = ref?.backendId;
    const nativeId = ref?.sessionId;
    const sessionId = channel.sessionId;
    const cwd = channel.cwd;
    const generationAfter = channel.agentBindingGeneration;
    const versionAfter = channel.version;
    if (![version, versionAfter, generation, generationAfter].every(value => Number.isSafeInteger(value) && value >= 0)
        || typeof ready !== "boolean" || typeof status !== "string"
        || typeof backendId !== "string" || typeof nativeId !== "string"
        || typeof sessionId !== "string" || typeof cwd !== "string") return { invalid: true };
    // 即使本次切面被撕裂，也不能忘掉已读到的水位回退。
    if (version < highVersion || versionAfter < version
        || generation < highGeneration || generationAfter < generation) inconsistent = true;
    highVersion = Math.max(highVersion, version, versionAfter);
    highGeneration = Math.max(highGeneration, generation, generationAfter);
    if (version !== versionAfter || generation !== generationAfter) return { race: true };
    const value = { version, generation, ready, failure, status, backendId, nativeId, sessionId, cwd };
    if (previous && (version < previous.version || generation < previous.generation
        || (version === previous.version && JSON.stringify(value) !== JSON.stringify(previous)))) {
      inconsistent = true;
    }
    previous = value;
    return value;
  }

  function attempt(count, candidate) {
    if (disposed) return;
    if (subscriptionFailed) {
      pending = false;
      unknown("binding-unavailable");
      return;
    }
    let value;
    try { value = sample(); } catch {
      pending = false;
      unknown("binding-unavailable");
      return;
    }
    if (inconsistent || value.invalid) {
      pending = false;
      unknown(inconsistent ? "inconsistent-binding" : "invalid-metadata");
      return;
    }
    if (value.race || !candidate || JSON.stringify(value) !== JSON.stringify(candidate)) {
      if (count >= MAX_ATTEMPTS) {
        pending = false;
        unknown("unstable-binding");
      } else {
        // 再让出一次执行权，避开 adoption emit 后仍在执行的同步 tail。
        schedule(() => attempt(count + 1, value.race ? undefined : value));
      }
      return;
    }
    pending = false;
    if (value.failure) { unknown("startup-failed"); return; }
    if (value.status === "disposed") { unknown("binding-disposed"); return; }
    if (!value.ready || value.status === "starting") {
      publish({ kind: "waiting", reason: "not-ready" });
      return;
    }
    if (!ACTIVE.has(value.status) || !value.backendId || !value.nativeId
        || value.nativeId !== value.sessionId || !value.cwd || value.cwd.includes("\0")) {
      unknown("invalid-metadata");
      return;
    }
    publish({ kind: "foreground-observed", version: value.version,
      agentBindingGeneration: value.generation, status: value.status,
      sessionRef: Object.freeze({ backendId: value.backendId, sessionId: value.nativeId }),
      sessionId: value.sessionId, cwd: value.cwd });
  }

  function enqueue() {
    if (disposed || pending) return;
    pending = true;
    schedule(() => attempt(1));
  }
  // 订阅先于初始采样；回调只排队，不在宿主的同步状态更新里发布。
  try {
    unsubscribe = channel.subscribe(enqueue);
    if (typeof unsubscribe !== "function") throw Error("invalid subscription");
    enqueue();
  } catch {
    subscriptionFailed = true;
    schedule(() => { if (!disposed) unknown("binding-unavailable"); });
  }
  return function dispose() {
    if (disposed) return;
    disposed = true;
    if (typeof unsubscribe === "function") unsubscribe();
  };
}
