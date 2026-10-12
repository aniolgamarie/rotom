// 仅可信控制器内存能力；持久引用分配与真实公开SDK事件传播由宿主负责。
import { AsyncLocalStorage } from "node:async_hooks";
import { types } from "node:util";
const CODE = "PI_CONFIRMED_INTENT_SCOPE_INVALID";
const hex32 = /^[0-9a-f]{32}$/;
const hex64 = /^[0-9a-f]{64}$/;
function invalid() { return Object.assign(new Error(CODE), { code: CODE }); }
function object(value, required, optional = []) {
  if (!value || typeof value !== "object" || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype) throw invalid();
  const keys = Reflect.ownKeys(value);
  if (keys.some(k => typeof k !== "string" || !required.includes(k) && !optional.includes(k)) || required.some(k => !keys.includes(k))) throw invalid();
  const result = {};
  for (const key of keys) {
    const d = Object.getOwnPropertyDescriptor(value, key);
    if (!d || !("value" in d)) throw invalid();
    result[key] = d.value;
  }
  return result;
}
function text(value, limit, controls = true) {
  return typeof value === "string" && value.length > 0 && value.length <= limit && !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value) && !value.includes("\0") && (!controls || !/[\p{Cc}\p{Cf}]/u.test(value)) && Buffer.byteLength(value, "utf8") <= limit;
}
function integer(value, min, max) { return Number.isSafeInteger(value) && value >= min && value <= max; }
function currentValue(value) {
  const v = object(value, ["profile", "session_id", "cwd", "runtime_identity", "config_identity", "policy_generation", "cancel_epoch"]);
  if (!["pi-base", "pi-full"].includes(v.profile) || !text(v.session_id, 512) || !text(v.cwd, 4096) || !v.cwd.startsWith("/") || v.cwd !== "/" && (v.cwd.endsWith("/") || v.cwd.split("/").slice(1).some(x => !x || x === "." || x === "..")) || typeof v.runtime_identity !== "string" || !hex64.test(v.runtime_identity) || typeof v.config_identity !== "string" || !hex64.test(v.config_identity) || !integer(v.policy_generation, 1, Number.MAX_SAFE_INTEGER) || !integer(v.cancel_epoch, 0, Number.MAX_SAFE_INTEGER)) throw invalid();
  return Object.freeze(v);
}
const result = (status, failed = false) => Object.freeze({ status, code: failed ? CODE : null });
export function createConfirmedIntentScope(options) {
  const cfg = object(options, ["enabled", "current", "allocateIntent", "submit", "confirmationMessage"], ["allocateRequest", "allocateRequestAsync", "now", "monotonic", "confirmTimeoutMs", "scopeTimeoutMs", "maxRequests"]);
  const now = cfg.now === undefined ? Date.now : cfg.now, monotonic = cfg.monotonic === undefined ? (() => performance.now()) : cfg.monotonic;
  const confirmTimeout = cfg.confirmTimeoutMs === undefined ? 30000 : cfg.confirmTimeoutMs, scopeTimeout = cfg.scopeTimeoutMs === undefined ? 300000 : cfg.scopeTimeoutMs, maxRequests = cfg.maxRequests === undefined ? 4096 : cfg.maxRequests;
  if (typeof cfg.enabled !== "boolean" || [cfg.current, cfg.allocateIntent, cfg.submit, now, monotonic].some(v => typeof v !== "function") || !text(cfg.confirmationMessage, 4096, false) || !integer(confirmTimeout, 1, 60000) || !integer(scopeTimeout, 1, 300000) || !integer(maxRequests, 1, 4096)) throw invalid();
  const asynchronous = Object.hasOwn(cfg, "allocateRequestAsync");
  if (Object.hasOwn(cfg, "allocateRequest") === asynchronous || typeof (asynchronous ? cfg.allocateRequestAsync : cfg.allocateRequest) !== "function" || types.isProxy(asynchronous ? cfg.allocateRequestAsync : cfg.allocateRequest)) throw invalid();
  const als = new AsyncLocalStorage();
  let active = null, busy = false, permanent = false;
  function drop(r, reason, failure = false) {
    if (!r) return;
    if (failure) r.failure = true;
    if (r.phase === "retired") return;
    r.phase = "retired"; r.reason = reason;
    // 公开UI接受取消signal；权限退役同时关闭本控制器的阻塞确认，迟到应答不能复活。
    r.dialog.abort();
    r.wake();
  }
  function clocks() {
    const wall = now(), mono = monotonic();
    if (typeof wall !== "number" || typeof mono !== "number" || !Number.isFinite(wall) || !Number.isFinite(mono) || wall < 0 || mono < 0) throw invalid();
    return { wall, mono };
  }
  function fresh(r, idle = false) {
    try {
      const c = currentValue(cfg.current()), t = clocks();
      if (Object.keys(c).some(k => c[k] !== r.current[k]) || t.wall < r.wall || t.mono < r.mono || t.wall - r.wall >= scopeTimeout || t.mono - r.mono >= scopeTimeout || r.ctx.cwd !== c.cwd || r.ctx.sessionManager.getSessionId() !== c.session_id || idle && (r.ctx.isIdle() !== true || r.ctx.hasPendingMessages() !== false)) { drop(r, "changed"); return false; }
      return r.phase !== "retired";
    } catch { drop(r, "invalid", true); return false; }
  }
  async function pending(r, value) {
    return Promise.race([Promise.resolve(value), r.stopped.then(() => stopped)]);
  }
  const stopped = Symbol("stopped");
  async function run(objective, ctx) {
    if (permanent) return result("retired");
    if (busy) return result("busy");
    busy = true;
    let r;
    try {
      if (!text(objective, 16384, false)) throw invalid();
      const c = currentValue(cfg.current());
      if (!cfg.enabled || c.profile === "pi-base") return result("not-called");
      if (!ctx || ctx.hasUI !== true || typeof ctx.ui?.confirm !== "function") return result("unavailable");
      if (typeof ctx.isIdle !== "function" || typeof ctx.hasPendingMessages !== "function" || typeof ctx.sessionManager?.getSessionId !== "function") throw invalid();
      if (ctx.isIdle() !== true || ctx.hasPendingMessages() !== false) return result("busy");
      const t = clocks(); let wake;
      const stoppedPromise = new Promise(resolve => { wake = resolve; });
      r = { current: c, ctx, objective, ...t, phase: "confirming", started: false, submitAccepted: false, seenInput: false, finishedByOriginalSettle: false, failure: false, memo: new Map(), pendingRequests: new Map(), stopped: stoppedPromise, wake, dialog: new AbortController() };
      active = r;
      if (!fresh(r, true)) return result(r.failure ? "failed" : "retired", r.failure);
      r.confirmTimer = setTimeout(() => drop(r, "confirmation-timeout"), confirmTimeout);
      r.scopeTimer = setTimeout(() => drop(r, "scope-timeout"), scopeTimeout);
      const answer = await pending(r, ctx.ui.confirm(cfg.confirmationMessage, JSON.stringify(objective),
        { signal: r.dialog.signal, timeout: confirmTimeout }));
      clearTimeout(r.confirmTimer);
      if (answer === stopped || r.phase === "retired") return result(r.failure ? "failed" : "retired", r.failure);
      const ct = clocks();
      if (ct.wall - r.wall >= confirmTimeout || ct.mono - r.mono >= confirmTimeout || !fresh(r, true)) return result(r.failure ? "failed" : "retired", r.failure);
      if (answer !== true) return result("declined");
      r.phase = "allocating";
      const allocationPromise = cfg.allocateIntent();
      if (!types.isPromise(allocationPromise)) throw invalid();
      const allocation = await pending(r, allocationPromise);
      if (allocation === stopped || r.phase === "retired") return result(r.failure ? "failed" : "retired", r.failure);
      const refs = object(allocation, ["session_scope", "intent_ref"]);
      if (typeof refs.session_scope !== "string" || typeof refs.intent_ref !== "string" || !hex32.test(refs.session_scope) || !hex32.test(refs.intent_ref)) throw invalid();
      r.refs = Object.freeze(refs);
      if (!fresh(r, true)) return result(r.failure ? "failed" : "retired", r.failure);
      r.phase = "starting";
      const submitted = als.run(r, () => cfg.submit(objective));
      if (!types.isPromise(submitted)) throw invalid();
      r.submitAccepted = true;
      // 忙状态一直保持到真实Promise退出；退役不等于底层任务已停止。
      await submitted;
      if (r.failure) return result("failed", true);
      if (r.finishedByOriginalSettle) return result("settled");
      return result(r.started ? "retired" : "not-started");
    } catch { if (r) drop(r, "invalid", true); return result("failed", true); }
    finally {
      if (r) { clearTimeout(r.confirmTimer); clearTimeout(r.scopeTimer); drop(r, "run-exited"); r.objective = null; r.memo.clear(); r.pendingRequests.clear(); }
      if (active === r) active = null;
      busy = false;
    }
  }
  function onInput(event) {
    const r = active;
    if (!r || r.phase === "retired") return;
    try {
      const e = object(event, ["type", "text", "source"], ["images", "streamingBehavior"]);
      const emptyImages = e.images === undefined || Array.isArray(e.images) && !types.isProxy(e.images) && Object.getPrototypeOf(e.images) === Array.prototype && Reflect.ownKeys(e.images).length === 1 && e.images.length === 0;
      if (als.getStore() !== r || r.phase !== "starting" || r.seenInput || e.type !== "input" || e.source !== "extension" || e.text !== r.objective || !emptyImages || e.streamingBehavior !== undefined || !fresh(r)) { drop(r, "input"); return; }
      r.seenInput = true;
    } catch { drop(r, "input"); }
  }
  function onAgentStart() {
    const r = active;
    if (!r || r.phase === "retired") return;
    if (als.getStore() !== r || r.phase !== "starting" || !r.seenInput || r.started || !fresh(r)) { drop(r, "start"); return; }
    r.started = true; r.phase = "running";
  }
  function onAgentSettled() {
    const r = active;
    if (!r || r.phase === "retired") return;
    if (als.getStore() === r && r.phase === "running" && fresh(r)) { r.finishedByOriginalSettle = true; drop(r, "original-settled"); }
    else drop(r, "settled");
  }
  function bindingForTool(toolCallId) {
    if (asynchronous) return null;
    const r = active;
    if (!r || !r.submitAccepted || r.phase !== "running" || als.getStore() !== r || !fresh(r)) return null;
    if (!text(toolCallId, 512)) { drop(r, "tool-id"); return null; }
    if (r.memo.has(toolCallId)) return r.memo.get(toolCallId);
    if (r.memo.size >= maxRequests) { drop(r, "capacity"); return null; }
    try {
      const request = Object.freeze({ ...r.refs, tool_call_id: toolCallId });
      const ref = cfg.allocateRequest(request);
      if (types.isPromise(ref)) {
        // 同步allocator误接异步函数仍拒绝授权；观察其拒绝，避免向宿主泄漏原始错误。
        Promise.prototype.then.call(ref, () => {}, () => {});
        throw invalid();
      }
      if (typeof ref !== "string" || !hex32.test(ref)) throw invalid();
      if (!fresh(r) || als.getStore() !== r || r.phase !== "running") return null;
      const binding = Object.freeze({ ...r.refs, request_ref: ref });
      r.memo.set(toolCallId, binding); return binding;
    } catch { drop(r, "allocator", true); return null; }
  }
  async function bindingForToolAsync(toolCallId) {
    if (!asynchronous) return null;
    const r = active;
    const eligible = () => active === r && r && r.submitAccepted && r.phase === "running" && als.getStore() === r && fresh(r);
    if (!eligible()) return null;
    if (typeof toolCallId !== "string" || !/^[!-~]{1,512}$/.test(toolCallId)) { drop(r, "tool-id"); return null; }
    if (r.memo.has(toolCallId)) return r.memo.get(toolCallId);
    let operation = r.pendingRequests.get(toolCallId);
    if (!operation) {
      if (r.memo.size + r.pendingRequests.size >= maxRequests) { drop(r, "capacity"); return null; }
      let resolve;
      operation = new Promise(done => { resolve = done; });
      // 在可信callback之前占槽；同ID重入不能重复持久分配，失败槽不开放重试。
      r.pendingRequests.set(toolCallId, operation);
      (async () => {
        try {
          const request = Object.freeze({ ...r.refs, tool_call_id: toolCallId });
          const value = cfg.allocateRequestAsync(request);
          if (types.isProxy(value) || !types.isPromise(value)) throw invalid();
          // 使用intrinsic观察原生Promise，绝不读取thenable的then/getter。
          const observed = new Promise((done, reject) => { Promise.prototype.then.call(value, done, reject); });
          const ref = await pending(r, observed);
          if (ref === stopped || !eligible()) { resolve(null); return; }
          if (typeof ref !== "string" || !hex32.test(ref)) throw invalid();
          const binding = Object.freeze({ ...r.refs, request_ref: ref });
          r.memo.set(toolCallId, binding); r.pendingRequests.delete(toolCallId); resolve(binding);
        } catch { drop(r, "allocator", true); resolve(null); }
      })();
    }
    const binding = await operation;
    return eligible() ? binding : null;
  }
  return Object.freeze({ run, onInput, onAgentStart, onAgentSettled, bindingForTool, bindingForToolAsync, invalidate() { drop(active, "invalidated"); }, retire() { permanent = true; drop(active, "retired"); } });
}
