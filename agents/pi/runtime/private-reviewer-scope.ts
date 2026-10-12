import { randomBytes } from "node:crypto";
import { types } from "node:util";
// 私有RPC能力，不证明真人确认或底层调用/进程已经物理停止。
const CODE = "PI_PRIVATE_REVIEWER_SCOPE_INVALID";
const invalid = () => Object.assign(new Error(CODE), { code: CODE });
const hex = value => typeof value === "string" && /^[0-9a-f]{32}$/.test(value);
const ascii = value => typeof value === "string" && /^[!-~]{1,512}$/.test(value);
function data(value, required, optional = []) {
  if (!value || typeof value !== "object" || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype) throw invalid();
  const keys = Reflect.ownKeys(value), out = {};
  if (required.some(k => !keys.includes(k)) || keys.some(k => typeof k !== "string" || !required.includes(k) && !optional.includes(k))) throw invalid();
  for (const key of keys) {
    const d = Object.getOwnPropertyDescriptor(value, key);
    if (!d || !("value" in d) || !d.enumerable) throw invalid();
    out[key] = d.value;
  }
  return out;
}
export function createPrivateReviewerScopeAttempt(options) {
  const cfg = data(options, ["call", "sessionId", "current"], ["timeoutMs", "maxRequests"]);
  const timeout = Object.hasOwn(cfg, "timeoutMs") ? cfg.timeoutMs : 5000, cap = Object.hasOwn(cfg, "maxRequests") ? cfg.maxRequests : 4096;
  if ([cfg.call, cfg.current].some(f => typeof f !== "function" || types.isProxy(f)) || types.isAsyncFunction(cfg.current) || !ascii(cfg.sessionId) || !Number.isInteger(timeout) || timeout < 1 || timeout > 5000 || !Number.isInteger(cap) || cap < 1 || cap > 4096) throw invalid();
  const control_id = randomBytes(16).toString("hex"), confirmation_ref = randomBytes(16).toString("hex");
  let active = true, touched = false, intentPromise, refs, cleanup, cleanupFailed = false, failureDelivered = false, drainRound;
  const memo = new Map(), pending = new Map(), waits = new Set();
  const wakeups = new Set();
  const stop = Symbol("stopped");
  function raw(method, args, cancellable = true) {
    let value;
    try {
      value = cfg.call(method, Object.freeze(args));
      if (types.isProxy(value) || !types.isPromise(value)) throw invalid();
    } catch { return Promise.reject(invalid()); }
    // intrinsic then观察迟到拒绝，不访问外来then getter。
    const observed = new Promise(resolve => Promise.prototype.then.call(value,
      result => resolve({ result }), () => resolve({ error: true })));
    let timer;
    const deadline = new Promise(resolve => { timer = setTimeout(() => resolve({ error: true }), timeout); });
    let wake;
    const retired = new Promise(resolve => {
      wake = () => resolve(stop);
      if (cancellable) { if (active) wakeups.add(wake); else wake(); }
    });
    const wait = Promise.race([observed, deadline, ...(cancellable ? [retired] : [])]).then(result => {
      clearTimeout(timer); wakeups.delete(wake);
      if (result === stop || result.error) throw invalid();
      return result;
    });
    waits.add(wait);
    wait.then(() => waits.delete(wait), () => waits.delete(wait));
    return wait;
  }
  function startCleanup() {
    cleanup = raw("ordinary_reviewer_scope_retire_session", { control_id, session_id: cfg.sessionId }, false).then(value => {
      const row = data(value.result, ["control_id", "state"]);
      if (row.control_id !== control_id || row.state !== "retired") throw invalid();
      cleanupFailed = false;
    }).catch(() => { cleanupFailed = true; throw invalid(); });
    cleanup.catch(() => {});
  }
  function retire() {
    if (!active) return;
    active = false;
    for (const wake of wakeups) wake();
    wakeups.clear();
    if (touched) startCleanup();
  }
  function isCurrent() {
    if (!active) return false;
    try {
      const value = cfg.current();
      if (value === true) return active;
      if (!types.isProxy(value) && types.isPromise(value)) Promise.prototype.then.call(value, undefined, () => {});
    } catch {}
    retire(); return false;
  }
  function allocation(method, args) {
    if (!isCurrent()) throw invalid();
    touched = true;
    return raw(method, args);
  }
  function allocateIntent() {
    if (!isCurrent()) return Promise.reject(invalid());
    if (intentPromise) return intentPromise;
    // 占槽在任何受信callback之前，允许同步重入时共享同一Promise。
    let resolve, reject;
    intentPromise = new Promise((yes, no) => { resolve = yes; reject = no; });
    (async () => {
      try {
        const opened = data((await allocation("ordinary_reviewer_scope_open", { control_id, session_id: cfg.sessionId })).result, ["control_id", "session_id", "session_scope", "state"]);
        if (!isCurrent() || opened.control_id !== control_id || opened.session_id !== cfg.sessionId || opened.state !== "open" || !hex(opened.session_scope)) throw invalid();
        const intent = data((await allocation("ordinary_reviewer_scope_allocate_intent", { control_id, confirmation_ref })).result, ["session_scope", "intent_ref"]);
        if (!isCurrent() || intent.session_scope !== opened.session_scope || !hex(intent.intent_ref)) throw invalid();
        refs = Object.freeze(intent); resolve(refs);
      } catch { retire(); reject(invalid()); }
    })();
    intentPromise.catch(() => {});
    return intentPromise;
  }
  function binding(value, request = false) {
    const row = data(value, ["session_scope", "intent_ref", "tool_call_id", ...(request ? ["request_ref"] : [])]);
    if (!refs || row.session_scope !== refs.session_scope || row.intent_ref !== refs.intent_ref || !ascii(row.tool_call_id) || request && (!hex(row.request_ref) || memo.get(row.tool_call_id) !== row.request_ref)) throw invalid();
    return row;
  }
  function allocateRequestAsync(value) {
    if (!isCurrent()) return Promise.resolve(null);
    let row;
    try { row = binding(value); } catch { retire(); return Promise.resolve(null); }
    if (memo.has(row.tool_call_id)) return Promise.resolve(memo.get(row.tool_call_id));
    if (pending.has(row.tool_call_id)) return pending.get(row.tool_call_id);
    if (memo.size + pending.size >= cap) { retire(); return Promise.resolve(null); }
    let resolve;
    const promise = new Promise(yes => { resolve = yes; });
    pending.set(row.tool_call_id, promise);
    (async () => {
      try {
        const result = data((await allocation("ordinary_reviewer_scope_allocate_request", { control_id, confirmation_ref, tool_call_id: row.tool_call_id })).result, ["session_scope", "intent_ref", "request_ref"]);
        if (!isCurrent() || result.session_scope !== refs.session_scope || result.intent_ref !== refs.intent_ref || !hex(result.request_ref)) throw invalid();
        memo.set(row.tool_call_id, result.request_ref); pending.delete(row.tool_call_id); resolve(result.request_ref);
      } catch { retire(); resolve(null); }
    })();
    return promise;
  }
  async function verify(value) {
    if (!isCurrent()) return false;
    let row;
    try { row = binding(value, true); } catch { return false; }
    try {
      const result = data((await raw("ordinary_reviewer_scope_verify", { control_id, confirmation_ref, tool_call_id: row.tool_call_id, request_ref: row.request_ref })).result, ["current", "session_scope", "intent_ref", "request_ref"]);
      if (!isCurrent() || result.current !== true || result.session_scope !== refs.session_scope || result.intent_ref !== refs.intent_ref || result.request_ref !== row.request_ref) throw invalid();
      return true;
    } catch { retire(); return false; }
  }
  function drain() {
    if (drainRound) return drainRound;
    drainRound = (async () => {
      // 仅等待本组件有界观察器；不等待底层RPC物理停止。
      await Promise.allSettled([...waits]);
      if (!cleanup) return;
      if (cleanupFailed && failureDelivered) startCleanup();
      try { await cleanup; } catch { failureDelivered = true; throw invalid(); }
    })();
    const round = drainRound;
    round.then(() => { drainRound = undefined; }, () => { drainRound = undefined; });
    return round;
  }
  return Object.freeze({ allocateIntent, allocateRequestAsync, verify, isCurrent, retire, drain });
}
